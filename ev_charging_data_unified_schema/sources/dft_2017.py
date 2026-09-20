"""UK Department for Transport — Electric Chargepoint Analysis 2017 raw data (OGL v3.0):
local-authority rapids and public-sector fasts, each with the publisher's incomplete-or-anomalous
file. Four files, four slightly different headers; the contract's family map and alias map
reconcile them (ADR-0007). docs/DATA_SOURCES.md records endpoints, licence and retrieval."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ev_charging_data_unified_schema.sources._common import download_all, read_csv_strings

SOURCE = "dft_2017"
_BASE = "https://assets.publishing.service.gov.uk/media/"
FILES = {
    "dft_2017_local_authority_rapids_raw.csv": _BASE
    + "5c1147ece5274a0bcac5f8d5/electric-chargepoint-analysis-2017-raw-rapids-data.csv",
    "dft_2017_local_authority_rapids_incomplete_anomalies.csv": _BASE
    + "5c114827e5274a0bd964df2b/electric-chargepoint-analysis-2017-rapids-incomplete-anomalies.csv",
    "dft_2017_public_sector_fasts_raw.csv": _BASE
    + "5c128fa5e5274a0ba8c4ba79/electric-chargepoint-analysis-2017-raw-public-sector-fasts-data.csv",
    "dft_2017_public_sector_fasts_incomplete_anomalies.csv": _BASE
    + "5c128de8e5274a0ae06bd792/electric-chargepoint-analysis-2017-public-sector-fasts-incomplete-anomalies.csv",
}


class Dft2017Loader:
    SOURCE = SOURCE
    URLS = tuple(FILES.values())

    def download(self, raw_dir: Path, *, refresh: bool = False) -> list[Path]:
        return download_all(FILES, raw_dir, SOURCE, refresh=refresh)

    def read_raw(self, path: Path) -> pd.DataFrame:
        frame = read_csv_strings(path)
        # the fasts files carry an unnamed leading index column; pandas names it "Unnamed: 0".
        # Keep it, under a name that cannot collide with a published header.
        return frame.rename(columns={"Unnamed: 0": "publisher_row_index"})


LOADER = Dft2017Loader()
