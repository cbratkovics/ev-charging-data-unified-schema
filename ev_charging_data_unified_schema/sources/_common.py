"""Shared pieces of the loaders."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ev_charging_data_unified_schema import acquire


def read_csv_strings(path: Path, *, encoding: str = "utf-8") -> pd.DataFrame:
    """Every column a nullable string, exactly the publisher's header names. Only the empty
    string is null; literal tokens such as ``NA`` stay as published (the contract declares
    them, silver nulls them) so bronze is a faithful copy."""
    return pd.read_csv(
        path, dtype="string", keep_default_na=False, na_values=[""], encoding=encoding
    )


def download_all(
    files: dict[str, str], raw_dir: Path, source: str, *, refresh: bool = False
) -> list[Path]:
    """Fetch ``{file_name: url}`` into ``raw_dir/<source>/`` one at a time (acquire.fetch
    pauses between requests and skips files already on disk)."""
    out = []
    for name, url in files.items():
        dest = raw_dir / source / name
        acquire.fetch(url, dest, refresh=refresh)
        out.append(dest)
    return out
