"""As-of feature builder — THE feature module (training, evaluation and serving all call it).

Every feature for target row ``(entity, season, period)`` is computed from that entity's rows
with ``(season, period)`` strictly earlier than the target. Nothing from the target row or any
later row is used: every statistic is computed on a series already shifted by one row within the
entity's group, and ``tests/test_features_no_leakage.py`` recomputes random rows from scratch.

Feature scheme, per raw stat (the loader's stat columns minus the published target):
``{stat}_L1`` (previous row), ``{stat}_L3_avg`` / ``{stat}_L5_avg`` (mean of the previous ≤3 / ≤5
rows, crossing season boundaries), ``{stat}_season_avg`` (mean of previous rows in the same
season; 0 at the first period), plus the target's own lags, ``period_of_season`` and
``rows_prior_this_season``. ``features_for_cohort`` returns every feature for every cohort; add
per-cohort exclusions there when a stat is meaningless for a cohort.

Bump ``FEATURE_VERSION`` whenever the scheme changes; it travels in every artifact.
"""

from __future__ import annotations

import pandas as pd

from ev_charging_data_unified_schema.config import PROJECT
from ev_charging_data_unified_schema.data import loader

FEATURE_VERSION = "asof_v1"

KEY_COLUMNS: tuple[str, ...] = PROJECT.grain
CONTEXT_COLUMNS: tuple[str, ...] = (PROJECT.cohort_name, "team", PROJECT.entity_display_column)
BASE_STATS: tuple[str, ...] = tuple(
    c for c in loader.STAT_COLUMNS if c != PROJECT.target_column
) + (PROJECT.target_column,)
LAGS: tuple[str, ...] = ("L1", "L3_avg", "L5_avg", "season_avg")
TEMPORAL_FEATURES: tuple[str, ...] = ("period_of_season", "rows_prior_this_season")
HISTORY_FLAG = "has_history"
TARGET_FLAG = "is_target"
_ENTITY, _SEASON, _PERIOD = PROJECT.entity_key, PROJECT.season_name, PROJECT.period_name


def all_feature_names() -> list[str]:
    names = [f"{stat}_{lag}" for stat in BASE_STATS for lag in LAGS]
    names.extend(TEMPORAL_FEATURES)
    return names


def features_for_cohort(cohort: str) -> list[str]:
    if cohort not in PROJECT.cohorts:
        raise ValueError(f"unknown cohort {cohort!r}; expected one of {PROJECT.cohorts}")
    return all_feature_names()


FEATURES_BY_COHORT: dict[str, list[str]] = {c: features_for_cohort(c) for c in PROJECT.cohorts}


def _shifted(df: pd.DataFrame, stat: str, by: list[str]) -> pd.Series:
    return df.groupby(by, sort=False)[stat].shift(1)


def _rolling_mean(df: pd.DataFrame, shifted: pd.Series, window: int) -> pd.Series:
    tmp = df[[_ENTITY]].assign(_v=shifted)
    out = (
        tmp.groupby(_ENTITY, sort=False)["_v"]
        .rolling(window, min_periods=1)
        .mean()
        .reset_index(level=0, drop=True)
    )
    return out.reindex(df.index)


def _expanding_mean(df: pd.DataFrame, shifted: pd.Series) -> pd.Series:
    tmp = df[[_ENTITY, _SEASON]].assign(_v=shifted)
    out = (
        tmp.groupby([_ENTITY, _SEASON], sort=False)["_v"]
        .expanding(min_periods=1)
        .mean()
        .reset_index(level=[0, 1], drop=True)
    )
    return out.reindex(df.index)


def build_features(rows: pd.DataFrame, targets: pd.DataFrame | None = None) -> pd.DataFrame:
    """Features at the grain. ``targets`` are future rows to score (keys + optional context);
    their features come from prior rows only, their target is NaN and ``is_target`` is True."""
    required = list(KEY_COLUMNS) + [PROJECT.cohort_name] + list(BASE_STATS)
    missing = [c for c in required if c not in rows.columns]
    if missing:
        raise KeyError(f"build_features requires columns {missing}")

    df = rows.copy()
    df[TARGET_FLAG] = False
    if targets is not None and len(targets):
        t = targets.copy()
        for c in KEY_COLUMNS:
            if c not in t.columns:
                raise KeyError(f"targets requires column {c!r}")
        collide = t.merge(df[list(KEY_COLUMNS)], on=list(KEY_COLUMNS), how="inner")
        if len(collide):
            raise ValueError(f"{len(collide)} target rows already exist in rows")
        latest_ctx = (
            df.sort_values(list(KEY_COLUMNS))
            .groupby(_ENTITY, sort=False)[list(CONTEXT_COLUMNS)]
            .last()
        )
        for c in CONTEXT_COLUMNS:
            if c not in t.columns:
                t[c] = t[_ENTITY].map(latest_ctx[c])
        t[TARGET_FLAG] = True
        for stat in BASE_STATS:
            t[stat] = float("nan")
        df = pd.concat([df, t[df.columns.intersection(t.columns)]], ignore_index=True)

    if df.duplicated(list(KEY_COLUMNS)).any():
        raise ValueError("rows has duplicate grain keys")

    df = df.sort_values(list(KEY_COLUMNS), kind="mergesort").reset_index(drop=True)
    for stat in BASE_STATS:
        df[stat] = pd.to_numeric(df[stat], errors="coerce").astype("float64")

    feats: dict[str, pd.Series] = {}
    for stat in BASE_STATS:
        s_prev = _shifted(df, stat, [_ENTITY])
        feats[f"{stat}_L1"] = s_prev
        feats[f"{stat}_L3_avg"] = _rolling_mean(df, s_prev, 3)
        feats[f"{stat}_L5_avg"] = _rolling_mean(df, s_prev, 5)
        feats[f"{stat}_season_avg"] = _expanding_mean(df, _shifted(df, stat, [_ENTITY, _SEASON]))
    feats["period_of_season"] = df[_PERIOD].astype("float64")
    feats["rows_prior_this_season"] = (
        df.groupby([_ENTITY, _SEASON], sort=False).cumcount().astype("float64")
    )

    features = pd.DataFrame(feats, index=df.index)[all_feature_names()]
    history_col = f"{PROJECT.target_column}_L1"
    has_history = features[history_col].notna()
    features = features.fillna(0.0)
    features.loc[~has_history, history_col] = float("nan")

    out = df[list(KEY_COLUMNS) + list(CONTEXT_COLUMNS)].copy()
    out["target"] = df[PROJECT.target_column].where(~df[TARGET_FLAG])
    out[HISTORY_FLAG] = has_history.to_numpy()
    out[TARGET_FLAG] = df[TARGET_FLAG].to_numpy()
    return pd.concat([out, features], axis=1)


def training_frame(features: pd.DataFrame) -> pd.DataFrame:
    """Rows usable for supervised training: realised target and at least one prior row."""
    return features[(~features[TARGET_FLAG]) & features[HISTORY_FLAG]].copy()
