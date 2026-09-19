from __future__ import annotations

from ev_charging_data_unified_schema.data import contracts


def test_summarise_run_results_maps_statuses() -> None:
    rr = {
        "results": [
            {
                "unique_id": "test.x.assert_rows_fresh_through_expected_period.abc",
                "status": "fail",
                "failures": 1,
            },
            {"unique_id": "test.x.not_null_slv_period_rows_id.abc", "status": "pass"},
            {"unique_id": "model.x.slv_predictions", "status": "error", "message": "boom"},
            {"unique_id": "model.x.slv_period_rows", "status": "success"},
        ],
        "elapsed_time": 1.0,
        "metadata": {"invocation_id": "i"},
    }
    rep = contracts.summarise_run_results(rr)
    names = {c["name"]: c for c in rep["checks"]}
    assert rep["ok"] is False
    assert names["freshness"]["ok"] is False and names["not_null_slv_period_rows_id"]["ok"] is True
    assert names["model:slv_predictions"]["detail"]["status"] == "error"
    assert rep["summary"]["dbt"]["n_checks"] == 3


def test_dbt_command_and_vars() -> None:
    v = contracts.dbt_vars(
        rows_path="data/cache/x.parquet",
        target_season=2024,
        target_period=3,
        expected_through=(2024, 2),
        prior_row_count=10,
    )
    assert v == {
        "rows_path": "data/cache/x.parquet",
        "target_season": 2024,
        "target_period": 3,
        "expected_season": 2024,
        "expected_period": 2,
        "prior_row_count": 10,
    }
    cmd = contracts.dbt_command(v, target="dev", full_refresh=True)
    assert "--full-refresh" in cmd and "+tag:silver" in cmd
