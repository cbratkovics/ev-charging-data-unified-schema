"""The SourceLoader seam is a runtime-checkable protocol; a minimal implementation satisfies
it and the registry of sources in config agrees with what dbt declares."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

from ev_charging_data_unified_schema import interfaces
from ev_charging_data_unified_schema.config import PROJECT, REPO_ROOT


class _Minimal:
    SOURCE = "boulder"
    URLS = ("https://example.invalid/sessions.csv",)

    def download(self, raw_dir: Path, *, refresh: bool = False) -> list[Path]:
        return []

    def read_raw(self, path: Path) -> pd.DataFrame:
        return pd.DataFrame()


def test_minimal_loader_satisfies_the_protocol() -> None:
    assert isinstance(_Minimal(), interfaces.SourceLoader)
    assert _Minimal.SOURCE in PROJECT.source_names


def test_every_configured_source_is_a_declared_dbt_source_table() -> None:
    src = yaml.safe_load(
        (REPO_ROOT / "dbt" / "models" / "bronze" / "_sources.yml").read_text(encoding="utf-8")
    )
    landed = next(s for s in src["sources"] if s["name"] == "landed")
    assert {t["name"] for t in landed["tables"]} == set(PROJECT.source_names)


def test_registry_coverage_flags_are_by_country() -> None:
    for s in PROJECT.sources:
        assert s.registry_coverage == (s.country in {"US", "CA"}), s.name
