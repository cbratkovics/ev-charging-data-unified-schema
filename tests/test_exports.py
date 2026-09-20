"""The exports/ contract (ADR-0015): only station-day grain and above, every file under the size
ceiling, manifest hashes match the files, JSON only for small relations, and two exports of the
same warehouse are byte-identical. Runs against the fixture warehouse when it exists; the
committed exports/ directory is checked whenever it exists."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import duckdb
import pytest

from ev_charging_data_unified_schema.config import EXPORTS_DIR, REPO_ROOT
from ev_charging_data_unified_schema.exports import (
    GRAIN_KEYS,
    SESSION_GRAIN,
    SIZE_CEILING_BYTES,
    sha256_of,
    write_exports,
)

FIXTURE_DB = REPO_ROOT / ".duckdb" / "fixture.duckdb"
DBT_MANIFEST = REPO_ROOT / "dbt" / "target" / "manifest.json"


def _check_dir(out: Path) -> dict:
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["files"], "no files exported"
    for name, f in manifest["files"].items():
        path = out / name
        assert path.exists(), name
        assert f["relation"] not in SESSION_GRAIN and f["relation"] in GRAIN_KEYS, name
        assert f["bytes"] == path.stat().st_size <= SIZE_CEILING_BYTES, (name, f["bytes"])
        assert f["sha256"] == sha256_of(path), name
        if f["format"] == "json":
            assert f["relation"] != "fct_station_day", "JSON is for small relations only"
    assert (out / "SCHEMA.md").exists() and "Open Government Licence" in (
        out / "SCHEMA.md"
    ).read_text()
    return manifest


def test_committed_exports_satisfy_the_contract() -> None:
    if not (EXPORTS_DIR / "manifest.json").exists():
        pytest.skip("no exports committed yet")
    _check_dir(EXPORTS_DIR)


def test_two_exports_of_the_same_warehouse_are_byte_identical(tmp_path) -> None:
    if not FIXTURE_DB.exists() or not DBT_MANIFEST.exists():
        pytest.skip("fixture warehouse or dbt manifest not built")
    dbt_manifest = json.loads(DBT_MANIFEST.read_text())
    outs = []
    for name in ("a", "b"):
        con = duckdb.connect(str(FIXTURE_DB), read_only=True)
        try:
            write_exports(con, dbt_manifest, tmp_path / name, rid="export-test", code_commit="abc")
        finally:
            con.close()
        _check_dir(tmp_path / name)
        outs.append(
            {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (tmp_path / name).iterdir()
                if p.suffix in (".parquet", ".json") and p.name != "manifest.json"
            }
        )
    assert outs[0] == outs[1]
