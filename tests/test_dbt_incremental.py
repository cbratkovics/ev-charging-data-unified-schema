"""Incremental equivalence for slv_period_rows: a full refresh and an incremental run over the
same input produce identical rows; a restated period inside the lookback is picked up; one
outside it is not until --full-refresh. Runs dbt against a scratch DuckDB file."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from ev_charging_data_unified_schema.config import ENV_PREFIX, PROJECT, REPO_ROOT

pytest.importorskip("dbt.cli.main")

MODEL = "slv_period_rows"
KEYS = list(PROJECT.grain)
LOOKBACK = 2
_S, _P = PROJECT.season_name, PROJECT.period_name
DBT_DIR = REPO_ROOT / "dbt"
PACKAGES_DIR = DBT_DIR / "dbt_packages"


def _dbt_bin() -> list[str]:
    """The dbt console script next to the current interpreter, else ``python -m dbt``."""
    script = Path(sys.executable).parent / "dbt"
    if script.exists():
        return [str(script)]
    return [sys.executable, "-m", "dbt"]


def _required_packages() -> list[str]:
    """Package directory names dbt expects: every entry of package-lock.yml (transitive
    dependencies included), else packages.yml."""
    import yaml

    for name in ("package-lock.yml", "packages.yml"):
        path = DBT_DIR / name
        if path.exists():
            entries = yaml.safe_load(path.read_text(encoding="utf-8")).get("packages", [])
            names = [e["package"].split("/")[-1] for e in entries if "package" in e]
            if names:
                return names
    return []


def _packages_installed() -> bool:
    required = _required_packages()
    return bool(required) and all(
        (PACKAGES_DIR / name).is_dir() and any((PACKAGES_DIR / name).iterdir()) for name in required
    )


@pytest.fixture(scope="session", autouse=True)
def dbt_packages() -> None:
    """Install the dbt packages once per session, exactly like ``make dbt-deps``.

    A test that shells out to dbt owns its dependency install: CI job boundaries are not a
    test's dependency manager. Never skipped: a missing package directory must fail loudly.
    """
    if _packages_installed():
        return
    cmd = [*_dbt_bin(), "deps", "--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR)]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    # macOS occasionally leaves empty "<pkg> 2" copies next to the installed packages, which makes
    # dbt refuse to run; empty directories are safe to drop.
    for d in PACKAGES_DIR.iterdir() if PACKAGES_DIR.exists() else []:
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    if proc.returncode != 0 or not _packages_installed():
        pytest.fail(
            "dbt deps failed or left packages missing\n"
            f"required: {_required_packages()}\nstdout:\n{proc.stdout[-3000:]}\nstderr:\n{proc.stderr[-3000:]}",
            pytrace=False,
        )


def _dbt_run(db_path: Path, rows_path: Path, *, full_refresh: bool) -> None:
    cmd = [
        *_dbt_bin(),
        "run",
        "--select",
        f"+{MODEL}",
        "--project-dir",
        "dbt",
        "--profiles-dir",
        "dbt",
        "--target",
        "dev",
        "--target-path",
        str(db_path.parent / "target"),
        "--log-path",
        str(db_path.parent / "logs"),
        "--vars",
        json.dumps({"rows_path": str(rows_path), "rows_lookback_periods": LOOKBACK}),
    ]
    if full_refresh:
        cmd.append("--full-refresh")
    env = {**os.environ, ENV_PREFIX + "DUCKDB_PATH": str(db_path)}
    proc = subprocess.run(cmd, cwd=REPO_ROOT, env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-3000:]


def _table(db_path: Path) -> pd.DataFrame:
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        return (
            con.execute(f"select * from silver.{MODEL}")
            .df()
            .sort_values(KEYS)
            .reset_index(drop=True)
        )
    finally:
        con.close()


def _checksum(df: pd.DataFrame) -> str:
    d = df[sorted(df.columns)].sort_values(KEYS).reset_index(drop=True)
    return hashlib.sha256(
        pd.util.hash_pandas_object(d, index=False).to_numpy().tobytes()
    ).hexdigest()


@pytest.fixture(scope="module")
def periods(rows: pd.DataFrame) -> list[int]:
    return sorted({PROJECT.period_key(s, p) for s, p in zip(rows[_S], rows[_P], strict=True)})


def _write(frame: pd.DataFrame, path: Path) -> Path:
    frame.to_csv(path, index=False)
    return path


def _restate(frame: pd.DataFrame, period_key: int) -> tuple[pd.DataFrame, pd.Series]:
    out = frame.copy()
    idx = out[(out[_S] * PROJECT.period_key_base + out[_P]) == period_key].index[0]
    out.loc[idx, "stat_b"] = float(out.loc[idx, "stat_b"]) + 10.0
    out.loc[idx, PROJECT.target_column] = float(out.loc[idx, PROJECT.target_column]) + 5.0
    return out, out.loc[idx, KEYS]


def test_incremental_run_equals_full_refresh_after_append(tmp_path, rows, periods) -> None:
    full = _write(rows, tmp_path / "full.csv")
    trunc = _write(
        rows[rows[_S] * PROJECT.period_key_base + rows[_P] < periods[-2]],
        tmp_path / "truncated.csv",
    )
    ref_db = tmp_path / "ref" / "w.duckdb"
    ref_db.parent.mkdir()
    _dbt_run(ref_db, full, full_refresh=True)
    reference = _table(ref_db)
    inc_db = tmp_path / "inc" / "w.duckdb"
    inc_db.parent.mkdir()
    _dbt_run(inc_db, trunc, full_refresh=True)
    assert len(_table(inc_db)) < len(reference)
    _dbt_run(inc_db, full, full_refresh=False)
    after = _table(inc_db)
    assert len(after) == len(reference) and _checksum(after) == _checksum(reference)


def test_restated_period_inside_lookback_is_picked_up(tmp_path, rows, periods) -> None:
    full = _write(rows, tmp_path / "full.csv")
    restated_frame, key = _restate(rows, periods[-LOOKBACK])
    restated = _write(restated_frame, tmp_path / "restated.csv")
    db = tmp_path / "w.duckdb"
    _dbt_run(db, full, full_refresh=True)
    _dbt_run(db, restated, full_refresh=False)
    ref_db = tmp_path / "ref.duckdb"
    _dbt_run(ref_db, restated, full_refresh=True)
    assert _checksum(_table(db)) == _checksum(_table(ref_db))


def test_restated_period_outside_lookback_needs_full_refresh(tmp_path, rows, periods) -> None:
    full = _write(rows, tmp_path / "full.csv")
    restated_frame, key = _restate(rows, periods[-(LOOKBACK + 3)])
    restated = _write(restated_frame, tmp_path / "restated.csv")
    db = tmp_path / "w.duckdb"
    _dbt_run(db, full, full_refresh=True)
    original = _table(db)
    _dbt_run(db, restated, full_refresh=False)
    assert _checksum(_table(db)) == _checksum(original)
    _dbt_run(db, restated, full_refresh=True)
    assert _checksum(_table(db)) != _checksum(original)
