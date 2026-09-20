"""Paths and the one project configuration shared by every layer.

Nothing here depends on a secret. ``PROJECT`` is the single source of the project-wide
constants; dbt cannot import Python, so ``dbt/dbt_project.yml`` carries a mirror of
:func:`dbt_vars` and ``tests/test_project_config.py`` fails when it drifts.

Environment variables (all optional, prefix ``EV_CHARGING_DATA_UNIFIED_SCHEMA_``):

* ``RAW_DIR`` / ``LANDED_DIR`` / ``ARTIFACTS_DIR`` — override the data directories.
* ``DUCKDB_PATH`` / ``DUCKDB_THREADS`` — read by ``dbt/profiles.yml``.

No secret is read anywhere; ``.env.example`` documents that.
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ENV_PREFIX = "EV_CHARGING_DATA_UNIFIED_SCHEMA_"
REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = Path(os.environ.get(ENV_PREFIX + "RAW_DIR", DATA_DIR / "raw"))
LANDED_DIR = Path(os.environ.get(ENV_PREFIX + "LANDED_DIR", DATA_DIR / "landed"))
ARTIFACTS_DIR = Path(os.environ.get(ENV_PREFIX + "ARTIFACTS_DIR", REPO_ROOT / "artifacts"))
EXPORTS_DIR = REPO_ROOT / "exports"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"
LANDED_MANIFEST_NAME = "manifest.json"

# Landing metadata every landed row carries (docs/ARCHITECTURE.md § ingestion).
META_COLUMNS: tuple[str, ...] = ("_source", "_file_name", "_retrieved_at", "_row_hash")


@dataclass(frozen=True)
class SourceSpec:
    """One session source. The download endpoints, licence and schema are recorded in
    docs/DATA_SOURCES.md; this is only the list of names."""

    name: str
    display_name: str
    country: str
    timezone: str
    """IANA zone of the stations (station-local time)."""
    licence: str
    """Short licence label; the verbatim text and its URL live in docs/DATA_SOURCES.md. Only
    sources with an explicit open licence are admitted (docs/adr/0004-source-policy.md)."""


@dataclass(frozen=True)
class ProjectConfig:
    """Project-wide constants. Frozen: change the values here, then regenerate the mirrors."""

    slug: str
    display_name: str
    package_name: str
    domain_summary: str
    sources: tuple[SourceSpec, ...]
    dbt_project_name: str
    github_owner: str
    repo_url: str
    pages_url: str
    python_version: str
    sessions_lookback_days: int
    """Restatement lookback of the incremental session fact, in days. Not calibrated."""

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @property
    def source_names(self) -> tuple[str, ...]:
        return tuple(s.name for s in self.sources)

    def source(self, name: str) -> SourceSpec:
        for s in self.sources:
            if s.name == name:
                return s
        raise KeyError(f"unknown source {name!r}; known: {self.source_names}")


PROJECT = ProjectConfig(
    slug="ev-charging-data-unified-schema",
    display_name="EV charging data, unified schema",
    package_name="ev_charging_data_unified_schema",
    domain_summary=(
        "Consolidates public EV-charging session data from four operators into one tested "
        "dbt schema on DuckDB."
    ),
    sources=(
        SourceSpec("boulder", "Boulder, CO", "US", "America/Denver", "CC0-1.0"),
        SourceSpec("cary", "Cary, NC", "US", "America/New_York", "CC0-1.0"),
        SourceSpec(
            "dft_2017", "UK DfT chargepoint analysis 2017", "GB", "Europe/London", "OGL-3.0"
        ),
    ),
    dbt_project_name="ev_charging_data_unified_schema_dbt",
    github_owner="cbratkovics",
    repo_url="https://github.com/cbratkovics/ev-charging-data-unified-schema",
    pages_url="https://cbratkovics.github.io/ev-charging-data-unified-schema/",
    python_version="3.12",
    sessions_lookback_days=45,
)


def env(name: str, default: str = "") -> str:
    """Read ``<PREFIX>_<name>`` from the environment."""
    return os.environ.get(ENV_PREFIX + name, default)


def dbt_vars() -> dict[str, Any]:
    """The project vars ``dbt/dbt_project.yml`` must declare with exactly these defaults."""
    return {
        "landed_dir": (
            LANDED_DIR.relative_to(REPO_ROOT).as_posix()
            if LANDED_DIR.is_relative_to(REPO_ROOT)
            else LANDED_DIR.as_posix()
        ),
        "sources": list(PROJECT.source_names),
        "sessions_lookback_days": PROJECT.sessions_lookback_days,
    }


def _main(argv: list[str]) -> int:  # pragma: no cover - thin CLI
    """python -m ev_charging_data_unified_schema.config --dbt-vars | --json | <field>"""
    if not argv or argv[0] in {"-h", "--help"}:
        print(_main.__doc__)
        return 0
    if argv[0] == "--dbt-vars":
        print(json.dumps(dbt_vars()))
    elif argv[0] == "--json":
        print(json.dumps(PROJECT.as_dict(), indent=2, default=list))
    else:
        value = getattr(PROJECT, argv[0])
        print(",".join(map(str, value)) if isinstance(value, tuple) else value)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main(sys.argv[1:]))
