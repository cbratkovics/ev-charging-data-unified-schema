"""Paths and the one project configuration shared by every layer.

Nothing here depends on the environment; there are no secrets. ``PROJECT`` is the single source
of the project-wide constants. dbt and the site cannot import Python, so they carry mirrors and
``tests/test_project_config.py`` fails when a mirror drifts:

* ``dbt/dbt_project.yml`` ``vars`` must equal :func:`dbt_vars`
* ``frontend/src/lib/project.config.json`` must equal :func:`frontend_config`
  (regenerate with ``python -m ev_charging_data_unified_schema.config --frontend``)
* the workflows read deployment names with ``python -m ev_charging_data_unified_schema.config <field>``
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ENV_PREFIX = "EV_CHARGING_DATA_UNIFIED_SCHEMA_"
REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS_DIR = Path(os.environ.get(ENV_PREFIX + "ARTIFACTS_DIR", REPO_ROOT / "artifacts"))
CACHE_DIR = Path(os.environ.get(ENV_PREFIX + "CACHE_DIR", REPO_ROOT / "data" / "cache"))
MANIFEST_PATH = ARTIFACTS_DIR / "manifest.json"
SCHEMAS_DIR = ARTIFACTS_DIR / "schemas"


@dataclass(frozen=True)
class ProjectConfig:
    """Project-wide constants. Frozen: change the values here, then regenerate the mirrors."""

    slug: str
    display_name: str
    package_name: str
    domain_summary: str
    entity_name: str
    entity_key: str
    entity_display_column: str
    period_name: str
    season_name: str
    cohort_name: str
    cohorts: tuple[str, ...]
    target_column: str
    target_units: str
    within_k: tuple[float, ...]
    candidates: tuple[str, ...]
    source_name: str
    min_season: int
    train_seasons: tuple[int, ...]
    val_season: int
    test_season: int
    periods_per_season: int
    dbt_project_name: str
    motherduck_database: str
    github_owner: str
    repo_url: str
    hf_space: str
    api_url: str
    site_url: str
    site_origins: tuple[str, ...]
    pages_url: str
    schedule_cron: str
    python_version: str
    node_version: str
    include_tiers: bool

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @property
    def period_columns(self) -> tuple[str, str]:
        return (self.season_name, self.period_name)

    @property
    def grain(self) -> tuple[str, ...]:
        return (self.entity_key, *self.period_columns)

    @property
    def period_width(self) -> int:
        """Digits needed for a period ordinal (file-name padding)."""
        return len(str(self.periods_per_season))

    @property
    def period_key_base(self) -> int:
        """period_key = season * period_key_base + period; the next power of ten above N."""
        return 10**self.period_width

    def period_key(self, season: int, period: int) -> int:
        return int(season) * self.period_key_base + int(period)


PROJECT = ProjectConfig(
    slug="ev-charging-data-unified-schema",
    display_name="Ev Charging Data Unified Schema",
    package_name="ev_charging_data_unified_schema",
    domain_summary="Consolidates five messy partner feeds into one tested dbt schema on DuckDB.",
    entity_name="station",
    entity_key="station_id",
    entity_display_column="station_name",
    period_name="day",
    season_name="day",
    cohort_name="channel",
    cohorts=(
        "A",
        "B",
    ),
    target_column="utilization",
    target_units="",
    within_k=(2, 4),
    candidates=("rf", "gbm"),
    source_name="synthetic stub (replace: docs/TEMPLATE_GUIDE.md)",
    # Synthetic fixture design; keep whole seasons forward in time when you plug in real data.
    min_season=2019,
    train_seasons=(2019, 2020, 2021),
    val_season=2022,
    test_season=2023,
    periods_per_season=12,
    dbt_project_name="ev_charging_data_unified_schema_dbt",
    motherduck_database="ev_charging_data_unified_schema",
    github_owner="cbratkovics",
    repo_url="https://github.com/cbratkovics/ev-charging-data-unified-schema",
    hf_space="/ev-charging-data-unified-schema",
    api_url="https://-ev-charging-data-unified-schema.hf.space",
    site_url="https://ev-charging-data-unified-schema.vercel.app",
    site_origins=("https://ev-charging-data-unified-schema.vercel.app",),
    pages_url="https://cbratkovics.github.io/ev-charging-data-unified-schema/",
    schedule_cron="0 10 * * 2",
    python_version="3.12",
    node_version="20",
    include_tiers=False,
)

RANDOM_STATE = 42
LOCAL_ORIGINS: tuple[str, ...] = ("http://localhost:3000", "http://127.0.0.1:3000")


def cors_origins() -> list[str]:
    return [*LOCAL_ORIGINS, *PROJECT.site_origins]


def env(name: str, default: str = "") -> str:
    """Read ``<PREFIX>_<name>`` from the environment."""
    return os.environ.get(ENV_PREFIX + name, default)


def dbt_vars() -> dict[str, Any]:
    """The project vars ``dbt/dbt_project.yml`` must declare with exactly these defaults."""
    return {
        "entity_key": PROJECT.entity_key,
        "season_column": PROJECT.season_name,
        "period_column": PROJECT.period_name,
        "cohort_column": PROJECT.cohort_name,
        "cohorts": list(PROJECT.cohorts),
        "candidates": list(PROJECT.candidates),
        "target_column": PROJECT.target_column,
        "within_k": list(PROJECT.within_k),
        "min_season": PROJECT.min_season,
        "periods_per_season": PROJECT.periods_per_season,
        "period_key_base": PROJECT.period_key_base,
    }


def frontend_config() -> dict[str, Any]:
    """Labels and names the site reads instead of string literals."""
    return {
        "slug": PROJECT.slug,
        "displayName": PROJECT.display_name,
        "domainSummary": PROJECT.domain_summary,
        "repoUrl": PROJECT.repo_url,
        "apiUrl": PROJECT.api_url,
        "pagesUrl": PROJECT.pages_url,
        "entity": {"name": PROJECT.entity_name, "key": PROJECT.entity_key},
        "period": {"name": PROJECT.period_name, "season": PROJECT.season_name},
        "cohort": {"name": PROJECT.cohort_name, "values": list(PROJECT.cohorts)},
        "target": {"column": PROJECT.target_column, "units": PROJECT.target_units},
        "withinK": list(PROJECT.within_k),
        "candidates": list(PROJECT.candidates),
    }


def _main(argv: list[str]) -> int:  # pragma: no cover - thin CLI
    """python -m ev_charging_data_unified_schema.config --frontend | --dbt-vars | --json | <field>"""
    if not argv or argv[0] in {"-h", "--help"}:
        print(_main.__doc__)
        return 0
    if argv[0] == "--frontend":
        print(json.dumps(frontend_config(), indent=2, ensure_ascii=False))
    elif argv[0] == "--dbt-vars":
        print(json.dumps(dbt_vars()))
    elif argv[0] == "--json":
        print(json.dumps(PROJECT.as_dict(), indent=2, default=list))
    else:
        value = getattr(PROJECT, argv[0])
        print(",".join(map(str, value)) if isinstance(value, tuple) else value)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main(sys.argv[1:]))
