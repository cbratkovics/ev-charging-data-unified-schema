"""The one seam a source plugs into: :class:`SourceLoader`, implemented once per session
source under ``ev_charging_data_unified_schema.sources`` (Phase 2).

A loader owns download and landing for one source and nothing else: no cleaning, no typing.
Everything downstream is dbt. The landed shape is the contract:

* one parquet file per downloaded source file under ``LANDED_DIR/<source>/``;
* every source column kept as a string (dbt silver does the typing, so a retyped column is a
  drift event, not a crash);
* the landing metadata columns ``_source``, ``_file_name``, ``_retrieved_at``, ``_row_hash``;
* a manifest entry per file: URL, retrieved_at, bytes, sha256, row count;
* re-running with unchanged files is a no-op (the sha256 in the manifest decides).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

import pandas as pd


@dataclass(frozen=True)
class ManifestEntry:
    """What the landing manifest records for one downloaded file."""

    source: str
    file_name: str
    url: str
    retrieved_at: str
    """ISO-8601 UTC timestamp of the download."""
    bytes: int
    sha256: str
    row_count: int
    landed_path: str
    """Repo-relative path of the landed parquet."""


@runtime_checkable
class SourceLoader(Protocol):
    SOURCE: str
    """Short name; matches ``config.PROJECT.source_names``."""
    URLS: tuple[str, ...]
    """The file or API endpoints downloaded, exactly as recorded in docs/DATA_SOURCES.md."""

    def download(self, raw_dir: Path, *, refresh: bool = False) -> list[Path]:
        """Fetch every file into ``raw_dir/<SOURCE>/`` and return the local paths. A file
        already present is re-used unless ``refresh``."""

    def read_raw(self, path: Path) -> pd.DataFrame:
        """Parse one raw file into a frame with every column as a string, exactly the source's
        column names. No cleaning."""
