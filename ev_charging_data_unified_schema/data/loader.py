"""Shared landing machinery every source loader uses: string-typed frames, row hashes, and the
landing manifest. Source-specific download and parsing live in ``sources/<name>.py`` (Phase 2).
This module has no network access and is fully unit-tested on the fixture.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from ev_charging_data_unified_schema.config import (
    LANDED_MANIFEST_NAME,
    META_COLUMNS,
    REPO_ROOT,
)
from ev_charging_data_unified_schema.interfaces import ManifestEntry


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def as_strings(frame: pd.DataFrame) -> pd.DataFrame:
    """Every column as a nullable string; nulls stay null, whitespace is not trimmed."""
    out = pd.DataFrame(index=frame.index)
    for col in frame.columns:
        s = frame[col]
        out[str(col)] = s.where(s.notna(), None).astype("string")
    return out


def row_hashes(frame: pd.DataFrame) -> pd.Series:
    """sha256 over the source columns of each row, in column order, nulls as the empty token.
    Stable across runs and machines; used for exact-duplicate detection downstream."""
    cols = [c for c in frame.columns if c not in META_COLUMNS]
    joined = frame[cols].fillna("\x00").astype(str).agg("\x1f".join, axis=1)
    return joined.map(lambda s: hashlib.sha256(s.encode("utf-8")).hexdigest()).astype("string")


def land_frame(
    raw: pd.DataFrame, *, source: str, file_name: str, retrieved_at: str
) -> pd.DataFrame:
    """The landed shape: source columns as strings plus the four metadata columns."""
    out = as_strings(raw)
    out["_source"] = pd.Series(source, index=out.index, dtype="string")
    out["_file_name"] = pd.Series(file_name, index=out.index, dtype="string")
    out["_retrieved_at"] = pd.Series(retrieved_at, index=out.index, dtype="string")
    out["_row_hash"] = row_hashes(out)
    return out.reset_index(drop=True)


def write_landed(frame: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False, compression="zstd")
    return path


def repo_relative(path: Path) -> str:
    p = path.resolve()
    return p.relative_to(REPO_ROOT).as_posix() if p.is_relative_to(REPO_ROOT) else p.as_posix()


def read_manifest(landed_dir: Path) -> dict[str, ManifestEntry]:
    """Manifest keyed by ``<source>/<file_name>``; empty when none exists yet."""
    path = landed_dir / LANDED_MANIFEST_NAME
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: ManifestEntry(**v) for k, v in data.get("files", {}).items()}


def write_manifest(landed_dir: Path, entries: dict[str, ManifestEntry]) -> Path:
    landed_dir.mkdir(parents=True, exist_ok=True)
    path = landed_dir / LANDED_MANIFEST_NAME
    payload = {"files": {k: asdict(v) for k, v in sorted(entries.items())}}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def manifest_key(source: str, file_name: str) -> str:
    return f"{source}/{file_name}"


def is_unchanged(entry: ManifestEntry | None, raw_path: Path) -> bool:
    """True when the manifest already records this file with the same sha256 and its landed
    parquet exists: re-landing would be a no-op."""
    if entry is None:
        return False
    landed = REPO_ROOT / entry.landed_path
    return landed.exists() and entry.sha256 == sha256_of(raw_path)
