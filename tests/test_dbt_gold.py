"""Idempotency and incremental correctness of gold on the fixture (docs/BRIEF.md § 6,
ADR-0011). Every test builds scratch DuckDB warehouses with one DuckDB thread and compares
key-sorted content, never bytes (docs/REPRODUCIBILITY.md). The dbt packages are installed by
the session fixture in tests/test_dbt_incremental.py (imported here).

Cases:
* two full builds of the same landed files are content-identical in every gold table and in
  the snapshot, validity columns included;
* landing the fixture sources in a different order gives the same gold;
* a late re-delivery that changes an energy value, removes a session and re-delivers old
  sessions, applied incrementally, equals a full refresh on the new landed files, with the
  vanished session gone and the changed energy present.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from ev_charging_data_unified_schema import ingest
from ev_charging_data_unified_schema.config import ENV_PREFIX, PROJECT, REPO_ROOT

from .test_dbt_incremental import dbt_packages  # noqa: F401  (registers the session fixture)

pytest.importorskip("dbt.cli.main")

RAW = REPO_ROOT / "tests" / "fixtures" / "raw"
GOLD_TABLES = {
    "gold.fct_charging_session": ["session_sk"],
    "gold.dim_station": ["station_key"],
    "gold.dim_operator": ["operator_key"],
    "gold.dim_date": ["date_key"],
    "gold.fct_station_day": ["station_key", "local_date"],
    "gold.int_station_gaps": ["station_key", "gap_after_date"],
    "snapshots.snp_station": ["station_key", "dbt_valid_from"],
}


def _dbt_bin() -> list[str]:
    script = Path(sys.executable).parent / "dbt"
    return [str(script)] if script.exists() else [sys.executable, "-m", "dbt"]


def _land(raw: Path, landed: Path, sources: list[str]) -> None:
    drift = landed.parent / "drift"
    args = [
        "--no-download",
        "--raw-dir",
        str(raw),
        "--landed-dir",
        str(landed),
        "--drift-dir",
        str(drift),
        "--sources",
        *sources,
        "--retrieved-at",
        "2026-01-01T00:00:00+00:00",
    ]
    assert ingest.main(args) == 0


def _build(
    db: Path,
    landed: Path,
    *,
    full_refresh: bool,
    select: str = "tag:bronze tag:silver tag:gold snapshot:*",
) -> None:
    cmd = [
        *_dbt_bin(),
        "build",
        "--project-dir",
        "dbt",
        "--profiles-dir",
        "dbt",
        "--target",
        "dev",
        "--target-path",
        str(db.parent / "target"),
        "--log-path",
        str(db.parent / "logs"),
        "--vars",
        json.dumps({"landed_dir": str(landed)}),
        "--exclude",
        "test_type:unit",
    ]
    if full_refresh:
        cmd.append("--full-refresh")
    env = {**os.environ, ENV_PREFIX + "DUCKDB_PATH": str(db), ENV_PREFIX + "DUCKDB_THREADS": "1"}
    proc = subprocess.run(cmd, cwd=REPO_ROOT, env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-2000:]


def _table(db: Path, name: str, keys: list[str]) -> pd.DataFrame:
    con = duckdb.connect(str(db), read_only=True)
    try:
        df = con.execute(f"select * from {name}").df()
    finally:
        con.close()
    return df.sort_values(keys).reset_index(drop=True)[sorted(df.columns)]


def _checksum(df: pd.DataFrame) -> str:
    return hashlib.sha256(
        pd.util.hash_pandas_object(df, index=False).to_numpy().tobytes()
    ).hexdigest()


def _all_checksums(db: Path) -> dict[str, str]:
    return {name: _checksum(_table(db, name, keys)) for name, keys in GOLD_TABLES.items()}


def _fresh(tmp_path: Path, name: str) -> tuple[Path, Path]:
    d = tmp_path / name
    d.mkdir()
    return d / "w.duckdb", d / "landed"


@pytest.mark.usefixtures("dbt_packages")
def test_two_full_builds_are_content_identical_including_the_snapshot(tmp_path) -> None:
    a_db, a_landed = _fresh(tmp_path, "a")
    b_db, b_landed = _fresh(tmp_path, "b")
    _land(RAW, a_landed, list(PROJECT.source_names))
    _land(RAW, b_landed, list(PROJECT.source_names))
    _build(a_db, a_landed, full_refresh=True)
    _build(b_db, b_landed, full_refresh=True)
    assert _all_checksums(a_db) == _all_checksums(b_db)
    snap = _table(a_db, "snapshots.snp_station", ["station_key", "dbt_valid_from"])
    assert snap["dbt_valid_to"].isna().all() and len(snap) == len(
        _table(a_db, "gold.dim_station", ["station_key"])
    )


@pytest.mark.usefixtures("dbt_packages")
def test_landing_order_does_not_change_gold(tmp_path) -> None:
    a_db, a_landed = _fresh(tmp_path, "a")
    b_db, b_landed = _fresh(tmp_path, "b")
    order = list(PROJECT.source_names)
    _land(RAW, a_landed, order)
    for s in reversed(order):
        _land(RAW, b_landed, [s])
    _build(a_db, a_landed, full_refresh=True)
    _build(b_db, b_landed, full_refresh=True)
    assert _all_checksums(a_db) == _all_checksums(b_db)


@pytest.mark.usefixtures("dbt_packages")
def test_late_redelivery_incremental_equals_full_refresh(tmp_path) -> None:
    raw = tmp_path / "raw"
    shutil.copytree(RAW, raw)
    inc_db, landed = _fresh(tmp_path, "inc")
    _land(raw, landed, list(PROJECT.source_names))
    _build(inc_db, landed, full_refresh=True)
    before = _table(inc_db, "gold.fct_charging_session", ["session_sk"])
    # the re-delivery: Boulder's file arrives again with one session's energy changed, one
    # session removed, and its old block re-delivered (a second copy of the whole first block)
    boulder = raw / "boulder" / "Electric_Vehicle_Charging_Station_Data.csv"
    text = boulder.read_text(encoding="utf-8-sig").splitlines()
    header, rows = text[0], text[1:]
    changed = rows[9].replace(",22.0,", ",23.5,")  # last session: energy 22.0 -> 23.5
    removed = rows[8]  # the 11/5/2023 session vanishes
    kept = [r for r in rows if r != removed and r != rows[9]] + [changed]
    redelivered = [
        r.rsplit(",", 1)[0] + f",{100 + i}" for i, r in enumerate(rows[:4])
    ]  # old block again, new file row ids
    boulder.write_text("﻿" + "\n".join([header, *kept, *redelivered]) + "\n", encoding="utf-8")
    _land(raw, landed, list(PROJECT.source_names))
    _build(inc_db, landed, full_refresh=False)
    after = _table(inc_db, "gold.fct_charging_session", ["session_sk"])
    full_db, _ = _fresh(tmp_path, "full")
    _build(full_db, landed, full_refresh=True)
    reference = _table(full_db, "gold.fct_charging_session", ["session_sk"])
    assert _checksum(after) == _checksum(
        reference
    ), "incremental result differs from a full refresh"
    # the vanished session is gone, the changed energy is present, other sources untouched
    b_before = before[before["source"] == "boulder"]
    b_after = after[after["source"] == "boulder"]
    assert len(b_after) == len(b_before) - 1
    assert (b_after["energy_kwh"] == 23.5).sum() == 1 and (
        b_before["energy_kwh"] == 23.5
    ).sum() == 0
    for src in ("cary", "dft_2017"):
        assert _checksum(before[before["source"] == src].reset_index(drop=True)) == _checksum(
            after[after["source"] == src].reset_index(drop=True)
        )
    assert set(b_after["source_file_sha256"]) != set(b_before["source_file_sha256"])
