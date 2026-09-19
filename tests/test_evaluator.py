from __future__ import annotations

import pytest

from ev_charging_data_unified_schema.config import PROJECT
from ev_charging_data_unified_schema.eval import evaluator

_E, _S, _P, _C = PROJECT.entity_key, PROJECT.season_name, PROJECT.period_name, PROJECT.cohort_name


def _row(e, s, p, c, pred, act):
    return {_E: e, _S: s, _P: p, _C: c, "prediction": pred, "actual": act}


def test_causal_baseline_never_sees_the_current_period() -> None:
    rows = [
        _row("a", 2023, 1, "A", 10, 12),
        _row("a", 2023, 2, "A", 10, 8),
        _row("b", 2023, 2, "A", 5, 6),
    ]
    out = {(r[_E], r[_P]): r["trailing_mean_baseline"] for r in evaluator.add_causal_baseline(rows)}
    assert out[("a", 1)] == 10  # nothing earlier: the prediction itself
    assert out[("a", 2)] == 12  # only period 1
    assert out[("b", 2)] == 12  # cohort fallback from a's period 1


def test_history_seeds_the_baseline_before_the_window() -> None:
    hist = [_row("a", 2022, 12, "A", 0, 20)]
    rows = [_row("a", 2023, 1, "A", 10, 12)]
    assert evaluator.add_causal_baseline(rows, hist)[0]["trailing_mean_baseline"] == 20


def test_metrics_share_rows_and_bands_follow_config() -> None:
    b1, b2 = PROJECT.within_k
    rows = [_row("a", 2023, 1, "A", 10, 10 + b1), _row("b", 2023, 1, "A", 10, 10 + b2 + 1)]
    rep = evaluator.evaluate_rows(rows, (2023, 1))
    assert rep["metrics"]["n"] == 2
    assert rep["metrics"]["within_band1_rate"] == 0.5 and rep["metrics"]["within_band2_rate"] == 0.5
    assert set(rep["cohorts"]) == {"A"} and rep["baseline"]["name"] == evaluator.BASELINE_NAME


def test_rejects_missing_columns_and_empty_window() -> None:
    with pytest.raises(ValueError):
        evaluator.evaluate_rows([{"x": 1}], (2023, 1))
    with pytest.raises(ValueError):
        evaluator.evaluate_rows([_row("a", 2022, 1, "A", 1, 1)], (2023, 1))


def test_build_artifact_records_provenance(tmp_path) -> None:
    p = tmp_path / "preds.csv"
    p.write_text("x\n1\n")
    rep = evaluator.evaluate_rows([_row("a", 2023, 1, "A", 1, 1)], (2023, 1))
    art = evaluator.build_artifact(
        rep,
        input_path=p,
        input_rows=1,
        model={"version": "v", "candidate": "rf"},
        kind="frozen_test",
    )
    assert art["artifact_version"] == evaluator.ARTIFACT_VERSION and art["input"]["sha256"]
    assert not art["input"]["path"].startswith("/") and art["eval_id"].startswith("eval-")
    assert "within_band1_rate" in art["metric_definitions"]
