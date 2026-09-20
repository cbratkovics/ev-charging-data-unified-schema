from __future__ import annotations

import pandas as pd

from ev_charging_data_unified_schema.config import META_COLUMNS
from ev_charging_data_unified_schema.data import loader
from ev_charging_data_unified_schema.interfaces import ManifestEntry


def test_land_frame_keeps_every_column_as_string_and_adds_metadata(raw_frame) -> None:
    landed = loader.land_frame(
        raw_frame, source="fixture", file_name="f.csv", retrieved_at="2026-01-01T00:00:00+00:00"
    )
    assert list(landed.columns) == [*raw_frame.columns, *META_COLUMNS]
    for col in raw_frame.columns:
        assert landed[col].dtype == "string", col
    assert landed["Energy (kWh)"].tolist()[:2] == ["1.5", "1.5"]
    assert pd.isna(landed["Energy (kWh)"][2]) and pd.isna(landed["Station Name"][3])
    assert landed["_source"].eq("fixture").all() and landed["_file_name"].eq("f.csv").all()


def test_row_hash_is_deterministic_and_ignores_metadata(raw_frame) -> None:
    a = loader.land_frame(raw_frame, source="s", file_name="f1", retrieved_at="t1")
    b = loader.land_frame(raw_frame, source="s", file_name="f2", retrieved_at="t2")
    assert a["_row_hash"].tolist() == b["_row_hash"].tolist()
    # the two identical source rows hash the same; the others differ
    assert a["_row_hash"][0] == a["_row_hash"][1]
    assert a["_row_hash"].nunique() == 3


def test_row_hash_distinguishes_null_from_empty_string() -> None:
    frame = pd.DataFrame({"x": [None, ""]})
    hashes = loader.row_hashes(loader.as_strings(frame))
    assert hashes[0] != hashes[1]


def test_landed_roundtrip_and_manifest(tmp_path, raw_frame) -> None:
    landed = loader.land_frame(raw_frame, source="s", file_name="f.csv", retrieved_at="t")
    path = loader.write_landed(landed, tmp_path / "landed" / "s" / "f.parquet")
    back = pd.read_parquet(path)
    pd.testing.assert_frame_equal(back, landed, check_dtype=False)

    raw = tmp_path / "f.csv"
    raw.write_text("a,b\n1,2\n")
    entry = ManifestEntry(
        source="s",
        file_name="f.csv",
        url="https://example.invalid/f.csv",
        retrieved_at="t",
        bytes=raw.stat().st_size,
        sha256=loader.sha256_of(raw),
        row_count=len(landed),
        landed_path=loader.repo_relative(path),
    )
    key = loader.manifest_key("s", "f.csv")
    loader.write_manifest(tmp_path / "landed", {key: entry})
    assert loader.read_manifest(tmp_path / "landed") == {key: entry}
    assert loader.read_manifest(tmp_path / "nowhere") == {}


def test_unchanged_file_is_a_noop_and_changed_file_is_not(tmp_path, raw_frame) -> None:
    raw = tmp_path / "f.csv"
    raw.write_text("a,b\n1,2\n")
    landed = loader.write_landed(
        loader.land_frame(raw_frame, source="s", file_name="f.csv", retrieved_at="t"),
        tmp_path / "f.parquet",
    )
    entry = ManifestEntry("s", "f.csv", "u", "t", 8, loader.sha256_of(raw), 4, str(landed))
    assert loader.is_unchanged(entry, raw)
    assert not loader.is_unchanged(None, raw)
    raw.write_text("a,b\n1,3\n")
    assert not loader.is_unchanged(entry, raw)
    landed.unlink()
    raw.write_text("a,b\n1,2\n")
    assert not loader.is_unchanged(entry, raw), "missing landed parquet must re-land"


def test_row_hashes_of_an_empty_frame_is_an_empty_series_and_it_lands(tmp_path) -> None:
    """The full-build failure of 2026-09-20: a header-only file reached land_frame and the
    row-wise hash returned a DataFrame (ADR-0015 amendment)."""
    empty = pd.DataFrame({"x": pd.Series([], dtype="string"), "y": pd.Series([], dtype="string")})
    hashes = loader.row_hashes(empty)
    assert isinstance(hashes, pd.Series) and len(hashes) == 0 and hashes.dtype == "string"
    landed = loader.land_frame(empty, source="s", file_name="f.csv", retrieved_at="t")
    assert list(landed.columns) == ["x", "y", *META_COLUMNS] and len(landed) == 0
    back = pd.read_parquet(loader.write_landed(landed, tmp_path / "f.parquet"))
    assert list(back.columns) == list(landed.columns) and len(back) == 0
