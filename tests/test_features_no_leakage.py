"""Leakage discipline: every feature of a row is recomputed from scratch using only earlier rows
of the same entity, and perturbing the target row changes nothing upstream."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ev_charging_data_unified_schema.config import PROJECT
from ev_charging_data_unified_schema.features import asof

_E, _S, _P = PROJECT.entity_key, PROJECT.season_name, PROJECT.period_name


def _recompute(history: pd.DataFrame, stat: str, season: int) -> dict[str, float]:
    h = history.sort_values([_S, _P])
    prev = h[stat].to_numpy()
    same = h[h[_S] == season][stat].to_numpy()
    return {
        f"{stat}_L1": prev[-1] if len(prev) else 0.0,
        f"{stat}_L3_avg": prev[-3:].mean() if len(prev) else 0.0,
        f"{stat}_L5_avg": prev[-5:].mean() if len(prev) else 0.0,
        f"{stat}_season_avg": same.mean() if len(same) else 0.0,
    }


def test_random_rows_recompute_from_earlier_rows_only(rows: pd.DataFrame) -> None:
    feats = asof.training_frame(asof.build_features(rows))
    sample = feats.sample(150, random_state=1)
    for r in sample.itertuples(index=False):
        rd = r._asdict()
        hist = rows[
            (rows[_E] == rd[_E])
            & ((rows[_S] < rd[_S]) | ((rows[_S] == rd[_S]) & (rows[_P] < rd[_P])))
        ]
        assert len(hist) >= 1
        for stat in asof.BASE_STATS:
            for k, v in _recompute(hist, stat, rd[_S]).items():
                assert np.isclose(rd[k], v), (rd[_E], rd[_S], rd[_P], k)
        assert rd["rows_prior_this_season"] == len(hist[hist[_S] == rd[_S]])
        assert rd["period_of_season"] == rd[_P]


def test_perturbing_the_target_row_changes_no_feature(rows: pd.DataFrame) -> None:
    # Perturb the *last* row of 30 entities: a perturbed row's own features must not move (they
    # come from earlier rows only), and choosing the last row per entity means no other
    # perturbed row precedes it.
    base = asof.build_features(rows)
    perturbed = rows.copy()
    last_per_entity = perturbed.sort_values(list(asof.KEY_COLUMNS)).groupby(_E).tail(1)
    idx = last_per_entity.sample(30, random_state=2).index
    for c in asof.BASE_STATS:
        perturbed.loc[idx, c] = perturbed.loc[idx, c] * 10 + 100
    after = asof.build_features(perturbed)
    keys = list(asof.KEY_COLUMNS)
    changed_keys = rows.loc[idx, keys]
    same = base.merge(changed_keys, on=keys)[asof.all_feature_names()].reset_index(drop=True)
    same_after = after.merge(changed_keys, on=keys)[asof.all_feature_names()].reset_index(drop=True)
    pd.testing.assert_frame_equal(same, same_after)


def test_first_row_of_an_entity_has_no_history_and_no_cross_contamination(
    rows: pd.DataFrame,
) -> None:
    feats = asof.build_features(rows)
    first = feats.sort_values(list(asof.KEY_COLUMNS)).groupby(_E).head(1)
    assert not first[asof.HISTORY_FLAG].any()
    assert (first[[f"{s}_L3_avg" for s in asof.BASE_STATS]] == 0).all().all()


def test_target_rows_are_scored_from_prior_rows(rows: pd.DataFrame) -> None:
    last = rows[_S].max()
    targets = pd.DataFrame({_E: rows[_E].unique()[:5], _S: last + 1, _P: 1})
    feats = asof.build_features(rows, targets=targets)
    stubs = feats[feats[asof.TARGET_FLAG]]
    assert len(stubs) == 5 and stubs["target"].isna().all() and stubs[asof.HISTORY_FLAG].all()
