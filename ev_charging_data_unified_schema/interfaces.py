"""The seams a domain plugs into. Each is implemented once in this project.

* :class:`SourceLoader` — ``<package>.data.loader.LOADER``. One row per
  ``(entity_key, season, period)`` with the raw columns every feature and the target derive
  from, cached as dated parquet, and the current period from the source's own calendar.
* :class:`TargetSpec` — ``<package>.target.TARGET_SPEC``. Names the target and its units,
  derives it from raw columns by explicit rules, and reconciles those rules against the value
  the source publishes (a non-empty disagreement frame is a stop, never a fudge).
* :class:`FeatureModule` — ``<package>.features.asof``. The one feature builder training,
  evaluation and serving all call. Every feature of a row uses only rows strictly earlier
  within the entity.

The artifact shapes that flow between layers are JSON Schemas under ``artifacts/schemas/``.
``tests/test_interfaces.py`` asserts the implementations satisfy these protocols and that every
committed artifact validates against its schema.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import pandas as pd


@runtime_checkable
class SourceLoader(Protocol):
    LIBRARY: str
    """``<client>==<version>`` recorded in training metadata for provenance."""
    ID_COLUMNS: tuple[str, ...]
    """Identifier / context columns: entity key, display name, cohort, season, period, ..."""
    STAT_COLUMNS: tuple[str, ...]
    """Raw numeric columns. Every feature and the target derive from these."""

    def load_period_rows(
        self, seasons: int | Iterable[int], *, refresh: bool = False
    ) -> pd.DataFrame:
        """One row per grain, ``ID_COLUMNS + STAT_COLUMNS``, sorted by grain, numeric columns
        float64. Raises ``KeyError`` when the source lacks an expected column."""

    def cache_path_for(self, name: str, seasons: int | Iterable[int]) -> Path:
        """The dated cache file a same-day load reads or writes (dbt's source)."""

    def current_period(self, today: Any = None) -> tuple[int, int]:
        """``(season, next_period_to_play)`` from the source's calendar, not the clock."""

    def periods_in_season(self, season: int) -> int:
        """Number of periods in ``season`` (the freshness contract's ceiling)."""


@dataclass(frozen=True)
class TargetSpec:
    column: str
    units: str
    required_columns: tuple[str, ...]
    derive: Callable[[pd.DataFrame], pd.Series]
    """``derive(df) -> Series`` of the target from raw columns, by explicit rules."""
    reconcile: Callable[[pd.DataFrame], pd.DataFrame]
    """Rows where the rules disagree with the source's own published value; empty = ok."""


@runtime_checkable
class FeatureModule(Protocol):
    FEATURE_VERSION: str
    KEY_COLUMNS: tuple[str, ...]
    CONTEXT_COLUMNS: tuple[str, ...]
    HISTORY_FLAG: str
    TARGET_FLAG: str

    def all_feature_names(self) -> list[str]: ...

    def features_for_cohort(self, cohort: str) -> list[str]: ...

    def build_features(
        self, rows: pd.DataFrame, targets: pd.DataFrame | None = None
    ) -> pd.DataFrame: ...

    def training_frame(self, features: pd.DataFrame) -> pd.DataFrame: ...
