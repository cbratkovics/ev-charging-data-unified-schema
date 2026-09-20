"""Source contracts and the schema-drift policy (docs/BRIEF.md § 5, ADR-0008).

A contract declares, per source and per file family, the columns the publisher's file is
expected to carry, the *logical type* of the values in each column (everything lands as a
string; the type is what the values parse as: integer, decimal, datetime, date, duration_hms,
text), whether the column is required, an alias map for renamed columns, the literal null
tokens, and the user-level columns silver must never select (ADR-0003).

On every ingest run each landed file is compared with its family's contract:

* an unknown column -> ``warn`` (the file is landed, the column rides along in bronze);
* a required column missing, or a required column whose values no longer parse as the declared
  type -> ``quarantine`` (the file is landed under ``_quarantined/`` with a reason code so
  bronze never reads it, and the run continues);
* a renamed column named in the alias map -> ``aliased`` (renamed on landing, recorded);
* an optional column missing -> ``info``.

The outcome for every file is written to ``artifacts/drift/<run_id>.json``. Pure functions,
unit-tested on the fixture: tests/test_contracts.py.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import pandas as pd

from ev_charging_data_unified_schema import profiling as pr

LogicalType = Literal["integer", "decimal", "datetime", "date", "duration_hms", "text", "empty"]
Severity = Literal["ok", "info", "warn", "quarantine"]

# a column whose values parse as one of these still satisfies a declared type further right
# (an integer column is a valid decimal; a wholly empty column cannot be judged)
COMPATIBLE: dict[str, set[str]] = {
    "integer": {"integer"},
    "decimal": {"decimal", "integer"},
    "datetime": {"datetime"},
    "date": {"date"},
    "duration_hms": {"duration_hms"},
    "text": {"text", "integer", "decimal", "datetime", "date", "duration_hms"},
}


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    logical_type: LogicalType
    required: bool = True
    description: str = ""


@dataclass(frozen=True)
class FamilyContract:
    family: str
    file_pattern: str
    """Substring of the file name that selects this family."""
    columns: tuple[ColumnSpec, ...]
    aliases: dict[str, str] = field(default_factory=dict)
    """``{published_name: canonical_name}`` for columns the publisher renamed."""
    null_tokens: tuple[str, ...] = ()
    """Literal strings that mean null in this family (kept as-is in bronze; nulled in silver)."""
    duration_unit: str | None = None
    """Unit of the published duration column, when it is numeric (minutes | hours)."""

    def required_names(self) -> set[str]:
        return {c.name for c in self.columns if c.required}

    def names(self) -> set[str]:
        return {c.name for c in self.columns}

    def spec(self, name: str) -> ColumnSpec | None:
        return next((c for c in self.columns if c.name == name), None)


@dataclass(frozen=True)
class SourceContract:
    source: str
    families: tuple[FamilyContract, ...]
    user_level_columns: tuple[str, ...] = ()
    timezone: str = "UTC"

    def family_for(self, file_name: str) -> FamilyContract | None:
        for fam in self.families:
            if fam.file_pattern in file_name:
                return fam
        return None


@dataclass
class ColumnFinding:
    column: str
    severity: Severity
    code: str
    detail: str


@dataclass
class FileDrift:
    source: str
    file_name: str
    family: str | None
    outcome: Severity
    reason_codes: list[str]
    findings: list[ColumnFinding]
    columns_seen: list[str]
    rows: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def apply_aliases(
    frame: pd.DataFrame, fam: FamilyContract
) -> tuple[pd.DataFrame, list[ColumnFinding]]:
    findings = []
    renames: dict[str, str] = {}
    for old, new in fam.aliases.items():
        if old not in frame.columns:
            continue
        if new in frame.columns:
            findings.append(
                ColumnFinding(
                    old,
                    "warn",
                    "alias_target_present",
                    f"{old!r} and its alias target {new!r} both present; {old!r} kept as is",
                )
            )
        else:
            renames[old] = new
            findings.append(
                ColumnFinding(
                    old, "info", "aliased", f"renamed to {new!r} per the contract alias map"
                )
            )
    return frame.rename(columns=renames), findings


def check_file(
    frame: pd.DataFrame, contract: SourceContract, file_name: str
) -> tuple[pd.DataFrame, FileDrift]:
    """Compare one raw frame with its family contract. Returns the frame with aliases applied
    and the drift record; ``outcome`` decides where the file lands."""
    fam = contract.family_for(file_name)
    if fam is None:
        return frame, FileDrift(
            contract.source,
            file_name,
            None,
            "quarantine",
            ["unknown_family"],
            [
                ColumnFinding(
                    "*",
                    "quarantine",
                    "unknown_family",
                    "no family in the contract matches this file name",
                )
            ],
            [str(c) for c in frame.columns],
            int(len(frame)),
        )
    frame, findings = apply_aliases(frame, fam)
    seen = [str(c) for c in frame.columns]
    for spec in fam.columns:
        if spec.name not in frame.columns:
            sev: Severity = "quarantine" if spec.required else "info"
            findings.append(
                ColumnFinding(
                    spec.name,
                    sev,
                    "missing_required" if spec.required else "missing_optional",
                    "declared column absent",
                )
            )
            continue
        col = frame[spec.name]
        if fam.null_tokens:
            col = col.mask(col.isin(fam.null_tokens))
        actual, _ = pr.infer_type(col)
        if actual == "empty":
            findings.append(
                ColumnFinding(
                    spec.name, "info", "all_null", "every value null or blank; type not judged"
                )
            )
        elif actual not in COMPATIBLE[spec.logical_type]:
            sev = "quarantine" if spec.required else "warn"
            findings.append(
                ColumnFinding(
                    spec.name,
                    sev,
                    "retyped_required" if spec.required else "retyped_optional",
                    f"declared {spec.logical_type}, values parse as {actual}",
                )
            )
    for name in seen:
        if name not in fam.names():
            findings.append(
                ColumnFinding(
                    name,
                    "warn",
                    "unknown_column",
                    "not declared in the contract; landed and carried through bronze",
                )
            )
    order = {"ok": 0, "info": 1, "warn": 2, "quarantine": 3}
    outcome: Severity = max((f.severity for f in findings), key=lambda s: order[s], default="ok")
    codes = sorted({f.code for f in findings if f.severity == "quarantine"})
    return frame, FileDrift(
        contract.source, file_name, fam.family, outcome, codes, findings, seen, int(len(frame))
    )


def drift_artifact(run_id: str, code_commit: str, files: list[FileDrift]) -> dict[str, Any]:
    return {
        "artifact": "drift",
        "run_id": run_id,
        "generated_at_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "code_commit": code_commit,
        "policy": {
            "unknown_column": "warn: landed, carried through bronze",
            "missing_required": "quarantine: file landed under _quarantined/, bronze does not read it, run continues",
            "retyped_required": "quarantine: as missing_required",
            "renamed_column": "aliased on landing per the contract alias map, recorded as info",
            "missing_optional": "info",
            "retyped_optional": "warn",
        },
        "summary": {
            "files": len(files),
            "by_outcome": {
                o: sum(1 for f in files if f.outcome == o)
                for o in ("ok", "info", "warn", "quarantine")
            },
            "quarantined_files": [
                f"{f.source}/{f.file_name}" for f in files if f.outcome == "quarantine"
            ],
        },
        "files": [f.as_dict() for f in files],
    }


# --- the contracts ---------------------------------------------------------------------------

CARY = SourceContract(
    source="cary",
    timezone="America/New_York",
    families=(
        FamilyContract(
            family="sessions",
            file_pattern="electric-vehicle-charging-stations",
            columns=(
                ColumnSpec(
                    "start_date",
                    "datetime",
                    description="session start, ISO 8601 with +00:00 (true UTC, ADR-0005 c)",
                ),
                ColumnSpec(
                    "station_name",
                    "text",
                    description="station display name; the only station identifier",
                ),
                ColumnSpec(
                    "charging_time_hh_mm_ss",
                    "duration_hms",
                    description="charging duration hh:mm:ss",
                ),
                ColumnSpec("energy_kwh", "decimal", description="energy delivered, kWh"),
                ColumnSpec("address_1", "text", False, "station street address"),
                ColumnSpec("address_2", "text", False, "station address line 2"),
                ColumnSpec("city", "text", False, "station city"),
                ColumnSpec("state_province", "text", False, "station state"),
                ColumnSpec("zip_postal_code", "text", False, "station postal code"),
            ),
        ),
    ),
)

BOULDER = SourceContract(
    source="boulder",
    timezone="America/Denver",
    families=(
        FamilyContract(
            family="transactions",
            file_pattern="Electric_Vehicle_Charging_Station_Data",
            columns=(
                ColumnSpec(
                    "Station_Name",
                    "text",
                    description="station display name; the only station identifier",
                ),
                ColumnSpec("Address", "text", False, "station street address (site key)"),
                ColumnSpec("City", "text", False, "station city"),
                ColumnSpec("State_Province", "text", False, "station state"),
                ColumnSpec("Zip_Postal_Code", "text", False, "station postal code"),
                # two shapes in one column (M/D/YYYY H:MM and ISO); declared text, parsed in silver
                ColumnSpec(
                    "Start_Date___Time",
                    "text",
                    description="session start, wall-clock local, two formats",
                ),
                ColumnSpec(
                    "Start_Time_Zone",
                    "text",
                    False,
                    "publisher's zone label; unreliable per row (docs/PROFILE.md)",
                ),
                ColumnSpec(
                    "End_Date___Time",
                    "text",
                    description="session end, wall-clock local, two formats",
                ),
                ColumnSpec("End_Time_Zone", "text", False, "publisher's zone label"),
                ColumnSpec(
                    "Total_Duration__hh_mm_ss_",
                    "duration_hms",
                    description="plug-in duration hh:mm:ss, hours unbounded",
                ),
                ColumnSpec(
                    "Charging_Time__hh_mm_ss_",
                    "duration_hms",
                    description="charging duration hh:mm:ss",
                ),
                ColumnSpec("Energy__kWh_", "decimal", description="energy delivered, kWh"),
                ColumnSpec(
                    "GHG_Savings__kg_", "decimal", False, "publisher's derived estimate; not used"
                ),
                ColumnSpec(
                    "Gasoline_Savings__gallons_",
                    "decimal",
                    False,
                    "publisher's derived estimate; not used",
                ),
                ColumnSpec("Port_Type", "text", False, "port class (Level 2 throughout)"),
                ColumnSpec(
                    "ObjectID",
                    "integer",
                    description="per-delivery row id; restarts at 0 at each delivery",
                ),
                ColumnSpec("ObjectId2", "integer", description="row id over the whole file"),
            ),
        ),
    ),
)

_DFT_COMMON = (
    ColumnSpec(
        "ChargingEvent",
        "text",
        False,
        "publisher's event id: an integer or a UUID; null or repeated in the fasts files",
    ),
    ColumnSpec("CPID", "text", description="charge-point id; null on some fasts rows"),
    ColumnSpec(
        "Connector", "text", False, "connector id 1..3, sometimes a text variant, often null"
    ),
    ColumnSpec("StartDate", "date", description="start date; ISO or day-first by family"),
    ColumnSpec("StartTime", "duration_hms", description="start time of day hh:mm:ss"),
    ColumnSpec("EndDate", "date", description="end date"),
    ColumnSpec("EndTime", "duration_hms", description="end time of day hh:mm:ss"),
    ColumnSpec(
        "Energy",
        "decimal",
        description="energy delivered, kWh (published as EnergySupplied in the rapids files)",
    ),
    ColumnSpec(
        "Name",
        "text",
        description="funding body (a council or public-sector organisation); the site key",
    ),
)
DFT_2017 = SourceContract(
    source="dft_2017",
    timezone="Europe/London",
    families=(
        FamilyContract(
            family="rapids",
            file_pattern="local_authority_rapids_raw",
            columns=(
                *_DFT_COMMON,
                ColumnSpec("Price", "text", False, "fee charged; NA tokens"),
                ColumnSpec("PluginDuration", "integer", description="plug-in duration, minutes"),
            ),
            aliases={"EnergySupplied": "Energy"},
            null_tokens=("NA",),
            duration_unit="minutes",
        ),
        FamilyContract(
            family="rapids_anomalies",
            file_pattern="local_authority_rapids_incomplete_anomalies",
            columns=(
                *_DFT_COMMON,
                ColumnSpec("Price", "text", False, "fee charged; NA tokens"),
                ColumnSpec(
                    "Area code", "text", False, "ONS area code of the funding body; NA tokens"
                ),
            ),
            aliases={"EnergySupplied": "Energy"},
            null_tokens=("NA",),
            duration_unit=None,
        ),
        FamilyContract(
            family="fasts",
            file_pattern="public_sector_fasts_raw",
            columns=(
                ColumnSpec("publisher_row_index", "integer", False, "unnamed leading index column"),
                *_DFT_COMMON,
                ColumnSpec("PluginDuration", "decimal", description="plug-in duration, hours"),
            ),
            null_tokens=("NA",),
            duration_unit="hours",
        ),
        FamilyContract(
            family="fasts_anomalies",
            file_pattern="public_sector_fasts_incomplete_anomalies",
            columns=(
                ColumnSpec("publisher_row_index", "integer", False, "unnamed leading index column"),
                *_DFT_COMMON,
                ColumnSpec("PluginDuration", "decimal", description="plug-in duration, hours"),
            ),
            null_tokens=("NA",),
            duration_unit="hours",
        ),
    ),
)

CONTRACTS: dict[str, SourceContract] = {c.source: c for c in (BOULDER, CARY, DFT_2017)}
