"""Boulder, CO — City of Boulder, "Electric Vehicle Charging Station Data" (CC0).
docs/DATA_SOURCES.md records the endpoint, licence and retrieval. The one CSV holds two
concatenated deliveries; silver handles that (ADR-0005 b), the loader lands it as is."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ev_charging_data_unified_schema.sources._common import download_all, read_csv_strings

SOURCE = "boulder"
FILES = {
    "Electric_Vehicle_Charging_Station_Data.csv": (
        "https://open-data.bouldercolorado.gov/api/download/v1/items/"
        "95992b3938be4622b07f0b05eba95d4c/csv?layers=0"
    ),
}


class BoulderLoader:
    SOURCE = SOURCE
    URLS = tuple(FILES.values())

    def download(self, raw_dir: Path, *, refresh: bool = False) -> list[Path]:
        return download_all(FILES, raw_dir, SOURCE, refresh=refresh)

    def read_raw(self, path: Path) -> pd.DataFrame:
        return read_csv_strings(path, encoding="utf-8-sig")


LOADER = BoulderLoader()
