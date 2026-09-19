from __future__ import annotations

import pandas as pd

from ev_charging_data_unified_schema.config import PROJECT
from ev_charging_data_unified_schema.data import loader


def test_rows_are_unique_at_the_grain_and_sorted(rows: pd.DataFrame) -> None:
    assert not rows.duplicated(list(PROJECT.grain)).any()
    assert rows.equals(rows.sort_values(list(PROJECT.grain)).reset_index(drop=True))
    assert set(loader.ID_COLUMNS + loader.STAT_COLUMNS) <= set(rows.columns)
    assert rows[PROJECT.cohort_name].isin(PROJECT.cohorts).all()


def test_synthesis_is_deterministic() -> None:
    a = loader.synthesize([2019, 2020])
    b = loader.synthesize([2019, 2020])
    pd.testing.assert_frame_equal(a, b)
    assert loader.LOADER.periods_in_season(2019) == PROJECT.periods_per_season


def test_cache_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(loader, "CACHE_DIR", tmp_path)
    first = loader.load_period_rows([2019])
    assert loader.cache_path_for(loader.CACHE_NAME, [2019]).exists()
    second = loader.load_period_rows([2019])
    pd.testing.assert_frame_equal(first, second)
