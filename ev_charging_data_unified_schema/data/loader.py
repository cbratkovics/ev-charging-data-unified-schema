"""STUB SourceLoader: a deterministic synthetic source so the generated project builds end to
end before any real data exists. Replace this module (docs/TEMPLATE_GUIDE.md § replacing the
loader) and keep the contract:

* ``load_period_rows(seasons)`` returns one row per ``(entity_key, season, period)`` with
  ``ID_COLUMNS + STAT_COLUMNS``, sorted by grain, stat columns float64, cached as dated parquet
  under ``CACHE_DIR/<name>_<first>-<last>_<YYYY-MM-DD>.parquet``;
* ``current_period()`` comes from the source's own calendar;
* ``LIBRARY`` names the client and version for provenance.

The synthetic world: ``N_ENTITIES`` entities split evenly over the cohorts, each with a latent
skill; every period each entity produces three stats around its skill (with season-level drift
and a few missing periods), and the published target is the rules of ``target.py`` applied to
those stats. Deterministic (fixed seed), so tests and dbt builds are reproducible.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from pathlib import Path

import numpy as np
import pandas as pd

from ev_charging_data_unified_schema.config import CACHE_DIR, PROJECT

LIBRARY = "synthetic-stub==0.1"
N_ENTITIES = 60
SEED = 7
CACHE_NAME = "period_rows"

ID_COLUMNS: tuple[str, ...] = (
    PROJECT.entity_key,
    PROJECT.entity_display_column,
    PROJECT.cohort_name,
    PROJECT.season_name,
    PROJECT.period_name,
    "team",
)
STAT_COLUMNS: tuple[str, ...] = ("stat_a", "stat_b", "stat_c", PROJECT.target_column)


def _seasons_list(seasons: int | Iterable[int]) -> list[int]:
    if isinstance(seasons, int):
        return [seasons]
    out = sorted({int(s) for s in seasons})
    if not out:
        raise ValueError("seasons must not be empty")
    return out


def _cache_path(name: str, seasons: list[int], load_date: dt.date | None = None) -> Path:
    load_date = load_date or dt.date.today()
    return CACHE_DIR / f"{name}_{seasons[0]}-{seasons[-1]}_{load_date.isoformat()}.parquet"


def cache_path_for(name: str, seasons: int | Iterable[int]) -> Path:
    return _cache_path(name, _seasons_list(seasons))


def synthesize(
    seasons: Iterable[int], *, n_entities: int = N_ENTITIES, seed: int = SEED
) -> pd.DataFrame:
    """The synthetic source, generated fresh (no cache). Deterministic for a given seed."""
    from ev_charging_data_unified_schema.target import derive

    rng = np.random.default_rng(seed)
    cohorts = list(PROJECT.cohorts)
    ids = [f"E{i:04d}" for i in range(n_entities)]
    skill = rng.normal(10.0, 3.0, size=n_entities).clip(2.0, None)
    teams = [f"T{i % 8:02d}" for i in range(n_entities)]
    rows = []
    for season in _seasons_list(seasons):
        season_shift = rng.normal(0.0, 0.5)
        for i, eid in enumerate(ids):
            active = rng.random(PROJECT.periods_per_season) > 0.08  # a few missing periods
            for period in range(1, PROJECT.periods_per_season + 1):
                if not active[period - 1]:
                    continue
                base = skill[i] + season_shift + 0.15 * period
                stat_a = max(0.0, rng.normal(4 * base, 6.0))
                stat_b = max(0.0, rng.normal(base, 2.5))
                stat_c = float(rng.poisson(max(base / 8, 0.1)))
                rows.append(
                    {
                        PROJECT.entity_key: eid,
                        PROJECT.entity_display_column: f"Entity {i:04d}",
                        PROJECT.cohort_name: cohorts[i % len(cohorts)],
                        PROJECT.season_name: season,
                        PROJECT.period_name: period,
                        "team": teams[i],
                        "stat_a": round(stat_a, 1),
                        "stat_b": round(stat_b, 1),
                        "stat_c": stat_c,
                    }
                )
    df = pd.DataFrame(rows)
    df[PROJECT.target_column] = derive(df).round(2)
    for c in STAT_COLUMNS:
        df[c] = df[c].astype("float64")
    return df.sort_values(list(PROJECT.grain)).reset_index(drop=True)


def load_period_rows(seasons: int | Iterable[int], *, refresh: bool = False) -> pd.DataFrame:
    seasons_l = _seasons_list(seasons)
    path = _cache_path(CACHE_NAME, seasons_l)
    if path.exists() and not refresh:
        raw = pd.read_parquet(path)
    else:
        raw = synthesize(seasons_l)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        raw.to_parquet(path, index=False)
    missing = [c for c in ID_COLUMNS + STAT_COLUMNS if c not in raw.columns]
    if missing:
        raise KeyError(f"source missing expected columns: {missing}")
    df = raw[list(ID_COLUMNS + STAT_COLUMNS)].copy()
    for c in STAT_COLUMNS:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")
    return df.sort_values(list(PROJECT.grain)).reset_index(drop=True)


class SyntheticLoader:
    """``interfaces.SourceLoader`` over the synthetic world."""

    LIBRARY = LIBRARY
    ID_COLUMNS = ID_COLUMNS
    STAT_COLUMNS = STAT_COLUMNS
    LAST_SEASON = PROJECT.test_season + 1  # the world has one complete season past the test

    def load_period_rows(
        self, seasons: int | Iterable[int], *, refresh: bool = False
    ) -> pd.DataFrame:
        return load_period_rows(seasons, refresh=refresh)

    def cache_path_for(self, name: str, seasons: int | Iterable[int]) -> Path:
        return cache_path_for(name, seasons)

    def current_period(self, today: dt.date | None = None) -> tuple[int, int]:
        # A real loader reads the schedule; the stub's world ends after LAST_SEASON, so the
        # next period to play is period 1 of the following season.
        return self.LAST_SEASON + 1, 1

    def periods_in_season(self, season: int) -> int:
        return PROJECT.periods_per_season


LOADER = SyntheticLoader()


def _main() -> None:  # pragma: no cover - CLI: python -m <pkg>.data.loader [--csv PATH]
    import argparse

    p = argparse.ArgumentParser(description="materialise the synthetic source cache")
    p.add_argument("--csv", type=Path, help="also write the rows as CSV (for dbt fixtures)")
    a = p.parse_args()
    df = load_period_rows(range(PROJECT.min_season, LOADER.LAST_SEASON + 1), refresh=True)
    print(
        f"{len(df)} rows -> {cache_path_for(CACHE_NAME, range(PROJECT.min_season, LOADER.LAST_SEASON + 1))}"
    )
    if a.csv:
        a.csv.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(a.csv, index=False)
        print(f"csv -> {a.csv}")


if __name__ == "__main__":  # pragma: no cover
    _main()
