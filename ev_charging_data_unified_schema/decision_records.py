"""Build and validate the bounded Boulder post-charge-idle decision record.

The record is deliberately not a generic decision platform.  It pins the aggregate findings
snapshot and its two declared inputs, then exposes only the observations needed by this case.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ev_charging_data_unified_schema.config import ARTIFACTS_DIR, REPO_ROOT

SCHEMA_VERSION = "1.0.0"
POLICY_VERSION = "boulder_idle_investigation_v1"
METRIC_VERSION = "full_occupancy_idle_v1"
DECISION_ID = "boulder_post_charge_idle_review"
SUPPORTED_CAPACITY_DEFINITIONS = (
    "production",
    "robust_max_n1",
    "robust_max_n2",
    "robust_max_n3",
    "robust_max_n5",
    "robust_max_n10",
)


class ActionState(BaseModel):
    """Observed operational action for this retrospective case."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["not_observed"]
    observed_action: None
    reason: str


class OutcomeState(BaseModel):
    """Measured operational outcome for this retrospective case."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["not_measured"]
    measured_effect: None
    reason: str


class DecisionRecord(BaseModel):
    """Strict outer contract plus case-specific semantic checks."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    decision_id: str
    record_version: str
    record_type: str
    created_at_utc: dt.datetime
    question: str
    population: dict[str, Any]
    evidence: dict[str, Any]
    observations: list[dict[str, Any]] = Field(min_length=1)
    sensitivity_interpretation: dict[str, Any]
    recommendation: dict[str, Any]
    alternatives_reviewed: list[dict[str, Any]]
    action: ActionState
    outcome: OutcomeState
    analytical_conclusion: str
    extension: dict[str, Any]

    @model_validator(mode="after")
    def case_invariants(self) -> DecisionRecord:
        if self.schema_version != SCHEMA_VERSION or self.decision_id != DECISION_ID:
            raise ValueError("unsupported decision contract or decision id")
        if self.record_type != "retrospective_analysis":
            raise ValueError("the historical case must be retrospective_analysis")
        labels = tuple(row.get("capacity_definition_id") for row in self.observations)
        if labels != SUPPORTED_CAPACITY_DEFINITIONS:
            raise ValueError(f"unsupported or reordered capacity definitions: {labels}")
        for row in self.observations:
            m = row["measures"]
            connected, idle, full = (
                m["connected_minutes"]["value"],
                m["idle_minutes"]["value"],
                m["full_occupancy_idle_minutes"]["value"],
            )
            if not 0 <= full <= idle <= connected:
                raise ValueError("minutes must nest: full-occupancy idle <= idle <= connected")
            ratios = row["ratios"]
            expected_idle = None if connected == 0 else round(idle / connected, 6)
            expected_full = None if connected == 0 else round(full / connected, 6)
            expected_of_idle = None if idle == 0 else round(full / idle, 6)
            if ratios["idle_share_of_connected"]["value"] != expected_idle:
                raise ValueError("idle share is not the ratio of summed components")
            if ratios["full_occupancy_idle_share_of_connected"]["value"] != expected_full:
                raise ValueError("full-occupancy idle share is not the ratio of summed components")
            if ratios["full_occupancy_share_of_idle"]["value"] != expected_of_idle:
                raise ValueError(
                    "full-occupancy share of idle is not the ratio of summed components"
                )
        return self


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def analytical_identity(record: dict[str, Any]) -> dict[str, Any]:
    """Return the content covered by ``record_version``.

    The identity includes every substantive field, including evidence, observations, policy,
    recommendation, action, and outcome.  It excludes only the self-referential version, the
    wall-clock creation time, and the builder execution's repository base commit.  Builder
    contract, policy, and metric versions remain substantive.
    """
    identity = deepcopy(record)
    identity.pop("record_version", None)
    identity.pop("created_at_utc", None)
    identity["evidence"]["builder"].pop("repository_base_commit", None)
    return identity


def record_version(record: dict[str, Any]) -> str:
    digest = hashlib.sha256(_canonical(analytical_identity(record))).hexdigest()[:16]
    return f"{DECISION_ID}-{digest}"


def _resolve_latest(kind: str, artifacts_dir: Path) -> tuple[Path, dict[str, Any]]:
    pointer = artifacts_dir / kind / "latest.json"
    target = pointer.parent / json.loads(pointer.read_text(encoding="utf-8"))["path"]
    if target.name == "latest.json" or not target.is_file():
        raise ValueError(f"{pointer} does not resolve to an immutable artifact")
    return target, json.loads(target.read_text(encoding="utf-8"))


def _artifact_ref(path: Path, artifact: dict[str, Any], root: Path, keys: list[str]) -> dict:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": sha256(path),
        "run_id": artifact["run_id"],
        "code_commit": artifact["code_commit"],
        "keys": keys,
    }


def _ratio(value: float | None, numerator: str, denominator: str) -> dict[str, Any]:
    return {
        "value": value,
        "unit": "ratio",
        "numerator_metric_id": numerator,
        "denominator_metric_id": denominator,
        "zero_denominator": "null",
        "aggregation": "ratio_of_summed_components_not_average_of_ratios",
    }


def analytical_payload(
    *, artifacts_dir: Path = ARTIFACTS_DIR, repo_root: Path = REPO_ROOT, builder_commit: str
) -> dict[str, Any]:
    findings_path, findings = _resolve_latest("findings", artifacts_dir)
    sensitivity_path, sensitivity = _resolve_latest("sensitivity", artifacts_dir)
    silver_path, silver = _resolve_latest("silver", artifacts_dir)
    if findings["inputs"] != {
        "sensitivity_run_id": sensitivity["run_id"],
        "silver_run_id": silver["run_id"],
    }:
        raise ValueError("findings inputs do not resolve to the pinned sensitivity and silver runs")
    if len({findings["code_commit"], sensitivity["code_commit"], silver["code_commit"]}) != 1:
        raise ValueError("pinned evidence artifacts do not share an upstream code commit")

    period = findings["periods"]["boulder"]
    source_input = silver["inputs"]["boulder/Electric_Vehicle_Charging_Station_Data.csv"]
    observations = []
    for capacity_id in SUPPORTED_CAPACITY_DEFINITIONS:
        if capacity_id not in findings["boulder_idle"]:
            raise ValueError(f"unsupported findings scenario: boulder_idle.{capacity_id}")
        row = findings["boulder_idle"][capacity_id]
        population_scope = "boulder_non_trivial_sessions_at_known_stations"
        component = f"boulder_idle.{capacity_id}"
        measures = {
            metric: {
                "value": row[metric],
                "unit": "minutes",
                "population_scope": population_scope,
                "evidence_key": f"{component}.{metric}",
            }
            for metric in (
                "connected_minutes",
                "idle_minutes",
                "full_occupancy_idle_minutes",
            )
        }
        observations.append(
            {
                "capacity_definition_id": capacity_id,
                "capacity_assumption": (
                    sensitivity["definitions"]["production"]
                    if capacity_id == "production"
                    else sensitivity["definitions"]["robust_max_nN"].replace(
                        "N distinct", f"{capacity_id.removeprefix('robust_max_n')} distinct"
                    )
                ),
                "population_scope": population_scope,
                "single_port_limitation": "At an inferred single-port station, every idle minute counts as full-occupancy idle by definition.",
                "measures": measures,
                "ratios": {
                    "idle_share_of_connected": _ratio(
                        row["idle_share_of_connected"], "idle_minutes", "connected_minutes"
                    ),
                    "full_occupancy_idle_share_of_connected": _ratio(
                        row["full_occupancy_idle_share_of_connected"],
                        "full_occupancy_idle_minutes",
                        "connected_minutes",
                    ),
                    "full_occupancy_share_of_idle": _ratio(
                        row["full_occupancy_share_of_idle"],
                        "full_occupancy_idle_minutes",
                        "idle_minutes",
                    ),
                },
                "evidence_object": "findings",
                "evidence_key": component,
            }
        )

    payload = {
        "schema_version": SCHEMA_VERSION,
        "decision_id": DECISION_ID,
        "record_type": "retrospective_analysis",
        "question": "For the historical Boulder observations, does recorded post-charge idle time support an operational intervention, or only a narrower investigation?",
        "population": {
            "source": "boulder",
            "scope": "non-trivial sessions at known stations",
            "session_count_in_source_fact": period["sessions"],
        },
        "evidence": {
            "observed_source_period": {
                "first_session_start_local": period["first_start_local"],
                "last_session_start_local": period["last_start_local"],
                "semantics": "Bounds are the first and last local session starts in the fact, not record creation or evidence availability dates.",
            },
            "source_retrieval": {
                "retrieved_at_utc": source_input["retrieved_at"],
                "source_file_sha256": source_input["sha256"],
                "semantics": "Retrieval records when this source snapshot was obtained; it does not prove availability to a historical decision-maker during the observed period.",
            },
            "artifacts": {
                "findings": _artifact_ref(
                    findings_path,
                    findings,
                    repo_root,
                    ["periods.boulder", "boulder_idle.production", "boulder_idle.robust_max_n*"],
                ),
                "sensitivity": _artifact_ref(
                    sensitivity_path,
                    sensitivity,
                    repo_root,
                    ["definitions.production", "definitions.robust_max_nN"],
                ),
                "silver": _artifact_ref(
                    silver_path,
                    silver,
                    repo_root,
                    ["inputs.boulder/Electric_Vehicle_Charging_Station_Data.csv"],
                ),
            },
            "builder": {
                "path": "ev_charging_data_unified_schema/decision_records.py",
                "repository_base_commit": builder_commit,
                "repository_base_commit_semantics": "HEAD when the record builder ran; contract_version identifies the builder contract and this field does not claim the uncommitted builder code existed in that commit.",
                "contract_version": SCHEMA_VERSION,
                "policy_version": POLICY_VERSION,
                "metric_definition_version": METRIC_VERSION,
            },
            "transformations": [
                {
                    "kind": "dbt_node",
                    "id": "model.ev_charging_data_unified_schema_dbt.fct_charging_session",
                },
                {"kind": "dbt_node", "id": "model.ev_charging_data_unified_schema_dbt.dim_station"},
                {
                    "kind": "external_python_function",
                    "id": "ev_charging_data_unified_schema.findings.full_occupancy_idle",
                    "executed_by_dbt": False,
                },
            ],
        },
        "observations": observations,
        "sensitivity_interpretation": {
            "type": "model_choice_sensitivity",
            "is_confidence_interval": False,
            "is_calibrated_probability": False,
            "statement": "The alternatives change inferred capacity for the same sessions; they do not quantify statistical uncertainty or observe queues.",
        },
        "recommendation": {
            "policy_version": POLICY_VERSION,
            "status": "targeted_investigation",
            "text": "Investigate the potential constraint and verify physical inventory and queue evidence before selecting an intervention.",
            "stable_across_supported_capacity_definitions": True,
        },
        "alternatives_reviewed": [
            {
                "interpretation": "system_wide_idle_fee_is_justified",
                "supported": False,
                "reason": "Idle overlap is not queue or displaced-demand evidence.",
            },
            {
                "interpretation": "a_queue_existed",
                "supported": False,
                "reason": "The source contains no queue, arrival, or turned-away-driver observations.",
            },
            {
                "interpretation": "targeted_investigation_before_intervention",
                "supported": True,
                "reason": "The conditional full-occupancy subset identifies a narrower question while retaining the evidence gaps.",
            },
        ],
        "action": {
            "status": "not_observed",
            "observed_action": None,
            "reason": "The historical artifacts contain no operator-action observation.",
        },
        "outcome": {
            "status": "not_measured",
            "measured_effect": None,
            "reason": "No intervention and no real-world operational effect were measured; zero would be an invented value.",
        },
        "analytical_conclusion": "The evidence narrows all post-charge idle time to the subset coinciding with inferred full occupancy and supports investigation, not a claimed queue or intervention effect.",
        "extension": {
            "rule": "A future version may append observed action or outcome evidence; it must create a new immutable record and must not overwrite this evidence and recommendation."
        },
    }
    return payload


def build_record(
    *,
    artifacts_dir: Path = ARTIFACTS_DIR,
    repo_root: Path = REPO_ROOT,
    builder_commit: str,
    created_at: dt.datetime | None = None,
) -> dict[str, Any]:
    payload = analytical_payload(
        artifacts_dir=artifacts_dir, repo_root=repo_root, builder_commit=builder_commit
    )
    payload["record_version"] = record_version(payload)
    payload["created_at_utc"] = (created_at or dt.datetime.now(dt.UTC)).isoformat()
    return DecisionRecord.model_validate(payload).model_dump(mode="json")


def validate_record(record: dict[str, Any], *, repo_root: Path = REPO_ROOT) -> DecisionRecord:
    validated = DecisionRecord.model_validate(record)
    expected_version = record_version(validated.model_dump(mode="json"))
    if validated.record_version != expected_version:
        raise ValueError(
            f"record_version does not match analytical content: expected {expected_version}"
        )
    for ref in validated.evidence["artifacts"].values():
        path = repo_root / ref["path"]
        if not path.is_file() or sha256(path) != ref["sha256"]:
            raise ValueError(f"missing or changed pinned evidence artifact: {ref['path']}")
        artifact = json.loads(path.read_text(encoding="utf-8"))
        if (
            artifact.get("run_id") != ref["run_id"]
            or artifact.get("code_commit") != ref["code_commit"]
        ):
            raise ValueError(f"pinned artifact identity mismatch: {ref['path']}")
    return validated


def select_observation(record: dict[str, Any], capacity_definition_id: str) -> dict[str, Any]:
    """Select one supported child exactly; never fall back to an unrelated scenario."""
    validated = DecisionRecord.model_validate(record)
    for observation in validated.observations:
        if observation["capacity_definition_id"] == capacity_definition_id:
            return observation
    raise KeyError(f"unsupported capacity definition: {capacity_definition_id}")


def write_record(record: dict[str, Any], *, repo_root: Path = REPO_ROOT) -> tuple[Path, Path]:
    validated = validate_record(record, repo_root=repo_root)
    data = _canonical(validated.model_dump(mode="json"))
    artifact_path = repo_root / "artifacts" / "decisions" / f"{validated.record_version}.json"
    public_path = repo_root / "exports" / "decision_lab" / f"{validated.record_version}.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.parent.mkdir(parents=True, exist_ok=True)
    if artifact_path.exists() and artifact_path.read_bytes() != data:
        # Creation time and builder provenance are intentionally retained for an existing version.
        existing = json.loads(artifact_path.read_text(encoding="utf-8"))
        validate_record(existing, repo_root=repo_root)
        data = artifact_path.read_bytes()
    else:
        artifact_path.write_bytes(data)
    public_path.write_bytes(data)
    pointer = {
        "decision_id": DECISION_ID,
        "record_version": validated.record_version,
        "path": artifact_path.name,
    }
    (artifact_path.parent / "latest.json").write_bytes(_canonical(pointer))
    (public_path.parent / "latest.json").write_bytes(
        _canonical({**pointer, "path": public_path.name})
    )
    return artifact_path, public_path
