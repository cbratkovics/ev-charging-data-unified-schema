"""Cary, NC — Town of Cary, "Electric Vehicle Charging Stations" (CC0 1.0).
docs/DATA_SOURCES.md records the endpoint, licence and retrieval."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ev_charging_data_unified_schema.sources._common import download_all, read_csv_strings

SOURCE = "cary"
FILES = {
    "electric-vehicle-charging-stations.csv": (
        "https://data.townofcary.org/api/explore/v2.1/catalog/datasets/"
        "electric-vehicle-charging-stations/exports/csv?delimiter=,&use_labels=false"
    ),
}


class CaryLoader:
    SOURCE = SOURCE
    URLS = tuple(FILES.values())

    def download(self, raw_dir: Path, *, refresh: bool = False) -> list[Path]:
        return download_all(FILES, raw_dir, SOURCE, refresh=refresh)

    def read_raw(self, path: Path) -> pd.DataFrame:
        # the export starts with a UTF-8 BOM
        return read_csv_strings(path, encoding="utf-8-sig")


LOADER = CaryLoader()
