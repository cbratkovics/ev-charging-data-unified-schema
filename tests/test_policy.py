"""Every branch of the pure publish / hold / promote policy, plus the promotion rule."""

from __future__ import annotations

from ev_charging_data_unified_schema.models import registry
from ev_charging_data_unified_schema.pipeline import scheduled


def test_contract_failure_holds() -> None:
    action, reasons = scheduled.decide(
        contract_ok=False, drift_status="ok", promote_ok=False, contract_failures=["freshness"]
    )
    assert action == "HOLD" and "freshness" in reasons[0]


def test_drift_hold_holds_and_warn_publishes_with_reason() -> None:
    assert (
        scheduled.decide(
            contract_ok=True, drift_status="hold", promote_ok=False, drift_features=["A:x"]
        )[0]
        == "HOLD"
    )
    action, reasons = scheduled.decide(
        contract_ok=True, drift_status="warn", promote_ok=False, promote_reason="n/a"
    )
    assert action == "PUBLISH" and any("warning" in r for r in reasons)


def test_promotion() -> None:
    action, _ = scheduled.decide(
        contract_ok=True, drift_status="ok", promote_ok=True, promote_reason="won"
    )
    assert action == "PROMOTE"


def test_should_promote_needs_four_wins_and_frozen_test() -> None:
    assert registry.should_promote([1, 1, 1], [0.5] * 3, 1.0, 0.9)[0] is False
    assert registry.should_promote([1] * 4, [0.5, 0.5, 1.5, 0.5], 1.0, 0.9)[0] is False
    assert registry.should_promote([1] * 4, [0.5] * 4, 1.0, 1.1)[0] is False
    assert registry.should_promote([1] * 4, [0.5] * 4, 1.0, 0.9)[0] is True


def test_manifest_roundtrip(tmp_path) -> None:
    p = tmp_path / "manifest.json"
    registry.write_manifest({"champion": {"model_version": "v", "candidate": "rf"}}, p)
    m = registry.read_manifest(p)
    assert m["manifest_version"] == registry.MANIFEST_VERSION and registry.slot(m, "champion") == (
        "v",
        "rf",
    )
