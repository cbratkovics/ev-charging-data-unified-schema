from __future__ import annotations

import numpy as np
import pandas as pd

from ev_charging_data_unified_schema.eval import drift


def _ref(rng, n=2000):
    return [float(v) for v in np.quantile(rng.normal(size=n), np.linspace(0, 1, 11))]


def test_no_shift_is_ok_and_broad_shift_holds() -> None:
    rng = np.random.default_rng(0)
    ref = {f: _ref(rng) for f in ("a", "b", "c")}
    same = pd.DataFrame({f: rng.normal(size=500) for f in ref})
    assert drift.drift_report(same, ref, list(ref))["status"] == "ok"
    shifted = pd.DataFrame({f: rng.normal(loc=2.5, size=500) for f in ref})
    rep = drift.drift_report(shifted, ref, list(ref))
    assert rep["status"] == "hold" and rep["thresholds"]["calibrated"] is drift.CALIBRATED


def test_single_feature_shift_only_warns() -> None:
    rng = np.random.default_rng(1)
    ref = {f: _ref(rng) for f in ("a", "b", "c")}
    cur = pd.DataFrame({f: rng.normal(size=500) for f in ref})
    cur["a"] = cur["a"] + 1.5
    assert drift.drift_report(cur, ref, list(ref))["status"] == "warn"


def test_period_bucket_covers_the_season_in_n_buckets() -> None:
    from ev_charging_data_unified_schema.config import PROJECT

    s = drift.BUCKET_PERIODS
    assert (
        drift.period_bucket(1) == 0
        and drift.period_bucket(s) == 0
        and drift.period_bucket(s + 1) == 1
    )
    assert 0 <= drift.period_bucket(PROJECT.periods_per_season) <= drift.N_BUCKETS - 1
    assert drift.period_bucket(10 * PROJECT.periods_per_season) == drift.N_BUCKETS - 1  # capped


def _seasonal_world(rng, seasons, n_rows=40):
    """A cohort whose feature level rises through the season, so late-season rows compared
    with an early-season reference look shifted and compared with late-season rows do not."""
    from ev_charging_data_unified_schema.config import PROJECT

    n = PROJECT.periods_per_season
    rows = []
    for season in seasons:
        for period in range(1, n + 1):
            level = 10.0 + 6.0 * (period - 1) / max(1, n - 1)
            for _ in range(n_rows):
                rows.append(
                    {
                        PROJECT.season_name: season,
                        PROJECT.period_name: period,
                        "f_a": rng.normal(level, 1.5),
                        "f_b": rng.normal(level * 2, 4.0),
                        "f_c": rng.normal(3.0, 1.0),
                    }
                )
    return pd.DataFrame(rows)


def _bucket_reference(train, feats):
    from ev_charging_data_unified_schema.config import PROJECT

    b = train[PROJECT.period_name].map(drift.period_bucket)
    return {
        "bucket_periods": drift.BUCKET_PERIODS,
        "global": drift.deciles(train, feats),
        "buckets": {str(int(k)): drift.deciles(train[b == k], feats) for k in sorted(b.unique())},
    }


def _boundary_window(current, last_season, n):
    from ev_charging_data_unified_schema.config import PROJECT

    s, p = PROJECT.season_name, PROJECT.period_name
    tail = max(1, n - (drift.WINDOW_PERIODS - 1))
    return current[
        ((current[s] == last_season) & (current[p] >= tail + 1))
        | ((current[s] == last_season + 1) & (current[p] == 1))
    ]


def test_boundary_window_holds_under_bucket_reference_and_clears_under_hybrid() -> None:
    from ev_charging_data_unified_schema.config import PROJECT

    rng = np.random.default_rng(3)
    feats = ["f_a", "f_b", "f_c"]
    train = _seasonal_world(rng, [2019, 2020, 2021, 2022])
    bucket_ref = _bucket_reference(train, feats)
    current = _seasonal_world(rng, [2025, 2026])
    window = _boundary_window(current, 2025, PROJECT.periods_per_season)
    pooled = drift.drift_report(window, bucket_ref["buckets"]["0"], feats)
    assert pooled["status"] == "hold", pooled["median_monitored"]
    ref, meta = drift.reference_for_window(window, bucket_ref, train, feats)
    hybrid = drift.drift_report(window, ref, feats, reference=meta)
    assert meta["mode"] == "matched" and meta["window_periods"][-1] == 1
    assert hybrid["status"] == "ok", hybrid["median_monitored"]


def test_mid_season_window_is_identical_under_both_references() -> None:
    from ev_charging_data_unified_schema.config import PROJECT

    rng = np.random.default_rng(4)
    feats = ["f_a", "f_b", "f_c"]
    train = _seasonal_world(rng, [2019, 2020, 2021, 2022])
    bucket_ref = _bucket_reference(train, feats)
    current = _seasonal_world(rng, [2026])
    lo = drift.BUCKET_PERIODS + 1
    window = current[current[PROJECT.period_name].between(lo, lo + drift.WINDOW_PERIODS - 1)]
    newest = int(window[PROJECT.period_name].max())  # the rule keys the bucket on the newest period
    bucket_only = drift.drift_report(
        window, bucket_ref["buckets"][str(drift.period_bucket(newest))], feats
    )

    ref, meta = drift.reference_for_window(window, bucket_ref, train, feats)
    hybrid = drift.drift_report(window, ref, feats, reference=meta)
    assert meta["mode"] == "bucket"
    assert hybrid["psi"] == bucket_only["psi"] and hybrid["status"] == bucket_only["status"]
