from __future__ import annotations

from ev_charging_data_unified_schema.compare import classify_run, issue_body

SILVER = {
    "run_id": "s1",
    "status": "non_blocking",
    "inputs": {"boulder/x.csv": {"sha256": "a", "rows": 10}},
    "by_source": {
        "boulder": {
            "bronze": 10,
            "accepted": 8,
            "non_trivial": 7,
            "quarantined": 2,
            "accepted_kwh": 100.0,
        }
    },
}
SENS = {
    "run_id": "z1",
    "results": [
        {
            "session_rule": "non_trivial_only",
            "source": "boulder",
            "definition": "production",
            "flavour": "connected",
            "utilization": 0.1,
            "station_days_over_100pct": 0,
        }
    ],
}


def _copy(d):
    import copy

    return copy.deepcopy(d)


def test_identical_runs_are_ok() -> None:
    r = classify_run(SILVER, _copy(SILVER), SENS, _copy(SENS))
    assert r["status"] == "ok" and not r["input_changes"] and not r["output_differences"]


def test_changed_inputs_are_informational_even_when_outputs_move() -> None:
    fresh = _copy(SILVER)
    fresh["inputs"]["boulder/x.csv"] = {"sha256": "b", "rows": 12}
    fresh["by_source"]["boulder"]["bronze"] = 12
    r = classify_run(SILVER, fresh, SENS, _copy(SENS))
    assert r["status"] == "upstream_changed"
    assert r["input_changes"][0]["row_delta"] == 2
    title, body = issue_body(r)
    assert title == "New source data available" and "boulder/x.csv" in body


def test_identical_inputs_with_moved_outputs_is_a_regression() -> None:
    fresh_s = _copy(SENS)
    fresh_s["results"][0]["utilization"] = 0.11
    r = classify_run(SILVER, _copy(SILVER), SENS, fresh_s)
    assert r["status"] == "regression" and r["output_differences"]
    title, _ = issue_body(r)
    assert title == "Full build regression"


def test_float_noise_within_tolerance_is_not_a_regression() -> None:
    fresh = _copy(SILVER)
    fresh["by_source"]["boulder"]["accepted_kwh"] = 100.0 * (1 + 1e-9)
    assert classify_run(SILVER, fresh, SENS, _copy(SENS))["status"] == "ok"


def test_blocking_reconciliation_is_a_regression_even_with_new_inputs() -> None:
    fresh = _copy(SILVER)
    fresh["status"] = "blocking"
    fresh["inputs"]["boulder/x.csv"]["sha256"] = "b"
    assert classify_run(SILVER, fresh, SENS, _copy(SENS))["status"] == "regression"
