from __future__ import annotations

from ev_charging_data_unified_schema.reconciliation import KWH_REL_TOL, classify


def test_rows_and_sessions_must_reconcile_exactly() -> None:
    assert classify(0, 100, kind="rows")["status"] == "ok"
    assert classify(1, 100, kind="sessions")["status"] == "blocking"
    assert classify(-3, 100, kind="rows")["status"] == "blocking"
    assert "unaccounted" in classify(2, 100, kind="rows")["interpretation"]


def test_kwh_residual_branches() -> None:
    assert classify(0.0, 1000.0, kind="kwh")["status"] == "ok"
    small = classify(1000.0 * KWH_REL_TOL * 0.5, 1000.0, kind="kwh")
    assert small["status"] == "non_blocking" and small["relative"] <= KWH_REL_TOL
    big = classify(1.0, 1000.0, kind="kwh")
    assert big["status"] == "blocking" and "exceeds tolerance" in big["interpretation"]
    # tiny references do not blow up the relative measure
    assert classify(0.5, 0.0, kind="kwh")["status"] == "blocking"
