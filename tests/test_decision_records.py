"""Decision Lab checks: synthetic interval math and committed real-artifact consistency."""

from __future__ import annotations

import copy
import datetime as dt
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from ev_charging_data_unified_schema.config import REPO_ROOT
from ev_charging_data_unified_schema.decision_records import (
    POLICY_VERSION,
    SUPPORTED_CAPACITY_DEFINITIONS,
    DecisionRecord,
    build_record,
    record_version,
    select_observation,
    validate_record,
    write_record,
)
from ev_charging_data_unified_schema.findings import full_occupancy_idle
from scripts.build_decision_records import check_record


def _committed_record() -> dict:
    latest = json.loads((REPO_ROOT / "artifacts/decisions/latest.json").read_text())
    return json.loads((REPO_ROOT / "artifacts/decisions" / latest["path"]).read_text())


def _isolated_record_repo(tmp_path: Path) -> tuple[Path, dict]:
    """Copy only the immutable record and evidence needed by offline decision tests."""
    record = _committed_record()
    for kind, ref in record["evidence"]["artifacts"].items():
        destination = tmp_path / ref["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / ref["path"], destination)
        shutil.copy2(
            REPO_ROOT / "artifacts" / kind / "latest.json", destination.parent / "latest.json"
        )
    name = f"{record['record_version']}.json"
    canonical = tmp_path / "artifacts" / "decisions" / name
    public = tmp_path / "exports" / "decision_lab" / name
    canonical.parent.mkdir(parents=True, exist_ok=True)
    public.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / "artifacts" / "decisions" / name, canonical)
    shutil.copy2(REPO_ROOT / "exports" / "decision_lab" / name, public)
    return tmp_path, record


def _synthetic_sessions() -> pd.DataFrame:
    frame = pd.DataFrame(
        [
            ("fixture/S", "2026-01-01T09:00:00Z", "2026-01-01T10:00:00Z", 30.0),
            ("fixture/S", "2026-01-01T09:15:00Z", "2026-01-01T09:45:00Z", 30.0),
        ],
        columns=["station_key", "start_utc", "end_utc", "charging_minutes"],
    )
    frame["start_utc"] = pd.to_datetime(frame["start_utc"], utc=True)
    frame["end_utc"] = pd.to_datetime(frame["end_utc"], utc=True)
    frame["start_local"] = frame["start_utc"].dt.tz_localize(None)
    frame["connected_minutes"] = (frame["end_utc"] - frame["start_utc"]).dt.total_seconds() / 60
    return frame


def test_fixture_interval_example_and_capacity_monotonicity() -> None:
    """Independent hand-built UTC fixture; it is not the public historical record."""
    sessions = _synthetic_sessions()
    two = full_occupancy_idle(sessions, pd.Series({"fixture/S": 2}))
    three = full_occupancy_idle(sessions, pd.Series({"fixture/S": 3}))
    assert two["connected_minutes"] == 90
    assert two["idle_minutes"] == 30
    assert two["full_occupancy_idle_minutes"] == 15
    assert two["idle_share_of_connected"] == pytest.approx(30 / 90)
    assert two["full_occupancy_idle_share_of_connected"] == pytest.approx(15 / 90, abs=1e-6)
    assert three["full_occupancy_idle_minutes"] == 0
    assert three["full_occupancy_idle_minutes"] <= two["full_occupancy_idle_minutes"]


def test_committed_real_record_resolves_every_measure_and_keeps_chronology_distinct() -> None:
    record = _committed_record()
    validate_record(record)
    findings_ref = record["evidence"]["artifacts"]["findings"]
    findings = json.loads((REPO_ROOT / findings_ref["path"]).read_text())
    assert (
        tuple(o["capacity_definition_id"] for o in record["observations"])
        == SUPPORTED_CAPACITY_DEFINITIONS
    )
    for observation in record["observations"]:
        evidence = findings["boulder_idle"][observation["capacity_definition_id"]]
        for metric, measure in observation["measures"].items():
            assert measure["value"] == evidence[metric]
    created = dt.datetime.fromisoformat(record["created_at_utc"])
    assert created.tzinfo is not None
    assert str(created.year) not in {
        record["evidence"]["observed_source_period"]["first_session_start_local"][:4],
        record["evidence"]["observed_source_period"]["last_session_start_local"][:4],
    }
    assert record["action"]["observed_action"] is None
    assert record["outcome"]["measured_effect"] is None
    assert select_observation(record, "robust_max_n3")["capacity_definition_id"] == "robust_max_n3"
    with pytest.raises(KeyError, match="unsupported"):
        select_observation(record, "production_multi_port")


def test_deterministic_identity_changes_for_policy_and_preserves_creation_metadata(
    monkeypatch,
) -> None:
    one = build_record(
        builder_commit="builder-a", created_at=dt.datetime(2026, 9, 26, tzinfo=dt.UTC)
    )
    two = build_record(
        builder_commit="builder-b", created_at=dt.datetime(2027, 1, 1, tzinfo=dt.UTC)
    )
    assert one["record_version"] == two["record_version"]
    assert one["created_at_utc"] != two["created_at_utc"]
    monkeypatch.setattr(
        "ev_charging_data_unified_schema.decision_records.POLICY_VERSION",
        POLICY_VERSION + "_changed",
    )
    changed = build_record(builder_commit="builder-a")
    assert changed["record_version"] != one["record_version"]


def test_valid_new_version_matches_shared_identity_calculation(monkeypatch) -> None:
    monkeypatch.setattr(
        "ev_charging_data_unified_schema.decision_records.POLICY_VERSION",
        POLICY_VERSION + "_changed",
    )
    changed = build_record(builder_commit="builder-a")
    assert changed["record_version"] == record_version(changed)
    validate_record(changed)


@pytest.mark.parametrize(
    ("ratio", "message"),
    [
        ("idle_share_of_connected", "idle share"),
        ("full_occupancy_idle_share_of_connected", "full-occupancy idle share"),
        ("full_occupancy_share_of_idle", "full-occupancy share of idle"),
    ],
)
def test_incorrect_ratios_are_rejected_by_semantic_validation(ratio: str, message: str) -> None:
    record = _committed_record()
    record["observations"][0]["ratios"][ratio]["value"] = 0.0
    with pytest.raises(ValueError, match=message):
        DecisionRecord.model_validate(record)


def test_invalid_nesting_and_zero_denominator_semantics() -> None:
    record = _committed_record()
    observation = record["observations"][0]
    observation["measures"]["idle_minutes"]["value"] = 1.0
    observation["measures"]["full_occupancy_idle_minutes"]["value"] = 2.0
    with pytest.raises(ValueError, match="minutes must nest"):
        DecisionRecord.model_validate(record)

    record = _committed_record()
    observation = record["observations"][0]
    for measure in observation["measures"].values():
        measure["value"] = 0.0
    for ratio in observation["ratios"].values():
        ratio["value"] = None
    DecisionRecord.model_validate(record)
    observation["ratios"]["idle_share_of_connected"]["value"] = 0.0
    with pytest.raises(ValueError, match="idle share"):
        DecisionRecord.model_validate(record)


@pytest.mark.parametrize("value", ["", 0, False, [], {}, "observed action"])
@pytest.mark.parametrize(
    ("section", "field"),
    [("action", "observed_action"), ("outcome", "measured_effect")],
)
def test_action_and_outcome_values_require_explicit_null(
    section: str, field: str, value: object
) -> None:
    record = _committed_record()
    record[section][field] = value
    with pytest.raises(ValueError, match=field):
        DecisionRecord.model_validate(record)


@pytest.mark.parametrize(
    ("section", "field"),
    [("action", "observed_action"), ("outcome", "measured_effect")],
)
def test_action_and_outcome_value_fields_are_required(section: str, field: str) -> None:
    record = _committed_record()
    del record[section][field]
    with pytest.raises(ValueError, match=field):
        DecisionRecord.model_validate(record)


@pytest.mark.parametrize(("section", "status"), [("action", "observed"), ("outcome", "measured")])
def test_action_and_outcome_statuses_are_exact(section: str, status: str) -> None:
    record = _committed_record()
    record[section]["status"] = status
    with pytest.raises(ValueError, match="status"):
        DecisionRecord.model_validate(record)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r["recommendation"].update(text="Different recommendation"),
        lambda r: r["evidence"]["builder"].update(policy_version="changed_policy"),
        lambda r: r["evidence"]["artifacts"]["findings"].update(run_id="changed_evidence"),
    ],
)
def test_changed_analytical_content_with_stale_version_is_rejected(tmp_path, mutate) -> None:
    root, record = _isolated_record_repo(tmp_path)
    mutate(record)
    with pytest.raises(ValueError, match="record_version does not match analytical content"):
        validate_record(record, repo_root=root)


def test_arbitrary_unused_record_version_is_rejected(tmp_path) -> None:
    root, record = _isolated_record_repo(tmp_path)
    record["record_version"] = "boulder_post_charge_idle_review-invented"
    with pytest.raises(ValueError, match="record_version does not match analytical content"):
        validate_record(record, repo_root=root)


def test_write_record_preserves_existing_version_bytes_for_excluded_metadata(tmp_path) -> None:
    root, record = _isolated_record_repo(tmp_path)
    path = root / "artifacts" / "decisions" / f"{record['record_version']}.json"
    original = path.read_bytes()
    candidate = copy.deepcopy(record)
    candidate["created_at_utc"] = "2027-01-01T00:00:00Z"
    candidate["evidence"]["builder"]["repository_base_commit"] = "different-builder-context"
    canonical, public = write_record(candidate, repo_root=root)
    assert canonical.read_bytes() == original
    assert public.read_bytes() == original


def test_write_record_rejects_invalid_candidate_before_preserving_existing_bytes(tmp_path) -> None:
    root, record = _isolated_record_repo(tmp_path)
    path = root / "artifacts" / "decisions" / f"{record['record_version']}.json"
    original = path.read_bytes()
    record["observations"][0]["ratios"]["idle_share_of_connected"]["value"] = 0.0
    with pytest.raises(ValueError, match="idle share"):
        write_record(record, repo_root=root)
    assert path.read_bytes() == original


def test_historical_validation_and_current_freshness_after_latest_advances(tmp_path) -> None:
    root, old_record = _isolated_record_repo(tmp_path)
    old_path = root / "artifacts" / "decisions" / f"{old_record['record_version']}.json"
    old_bytes = old_path.read_bytes()

    findings_ref = old_record["evidence"]["artifacts"]["findings"]
    newer = json.loads((root / findings_ref["path"]).read_text())
    newer["run_id"] = "findings-coherent-newer"
    newer_path = root / "artifacts" / "findings" / "findings-coherent-newer.json"
    newer_path.write_text(json.dumps(newer, indent=2, sort_keys=True) + "\n")
    (newer_path.parent / "latest.json").write_text(
        json.dumps({"run_id": newer["run_id"], "path": newer_path.name})
    )

    validate_record(old_record, repo_root=root)
    with pytest.raises(FileNotFoundError, match="missing generated decision record"):
        check_record(repo_root=root, artifacts_dir=root / "artifacts", builder_commit="new-builder")

    candidate = build_record(
        artifacts_dir=root / "artifacts", repo_root=root, builder_commit="new-builder"
    )
    assert candidate["record_version"] != old_record["record_version"]
    write_record(candidate, repo_root=root)
    assert (
        check_record(
            repo_root=root, artifacts_dir=root / "artifacts", builder_commit="other-builder"
        )
        == candidate["record_version"]
    )
    assert old_path.read_bytes() == old_bytes


def test_tampered_pinned_artifact_fails_validation(tmp_path: Path) -> None:
    record_path = (
        REPO_ROOT
        / "artifacts/decisions"
        / json.loads((REPO_ROOT / "artifacts/decisions/latest.json").read_text())["path"]
    )
    record = json.loads(record_path.read_text())
    for ref in record["evidence"]["artifacts"].values():
        target = tmp_path / ref["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((REPO_ROOT / ref["path"]).read_bytes())
    first = next(iter(record["evidence"]["artifacts"].values()))
    (tmp_path / first["path"]).write_text("{}")
    with pytest.raises(ValueError, match="missing or changed"):
        validate_record(record, repo_root=tmp_path)


def test_public_payload_is_aggregate_only_and_cannot_assert_success_from_schema() -> None:
    latest = json.loads((REPO_ROOT / "exports/decision_lab/latest.json").read_text())
    text = (REPO_ROOT / "exports/decision_lab" / latest["path"]).read_text()
    record = json.loads(text)
    forbidden = ("session_id", "session_sk", "user_id", "email", "recovered_demand", "test_passed")
    assert not any(token in text.lower() for token in forbidden)
    assert record["recommendation"]["status"] == "targeted_investigation"
    assert record["action"]["status"] == "not_observed"
    assert record["outcome"]["status"] == "not_measured"


def test_pruning_protects_artifacts_pinned_by_a_decision(tmp_path: Path, monkeypatch) -> None:
    from scripts import prune_artifacts

    decisions = tmp_path / "decisions"
    decisions.mkdir()
    (decisions / "record.json").write_text(
        json.dumps(
            {
                "evidence": {
                    "artifacts": {"findings": {"path": "artifacts/findings/findings-pinned.json"}}
                }
            }
        )
    )
    monkeypatch.setattr(prune_artifacts, "ARTIFACTS_DIR", tmp_path)
    assert prune_artifacts.cited_by_decisions() == {("findings", "findings-pinned.json")}
