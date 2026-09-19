"""Scaffold for the Phase 4 idempotency and incremental-equivalence tests on
fct_charging_session: build twice and assert identical key-sorted content; land fixture files
out of order and with a re-delivered overlapping file and assert the same result. The dbt
helpers below (console script next to the interpreter, `dbt deps` owned by the session fixture,
scratch DuckDB via the profile's env var) are kept from the template because the tests reuse
them unchanged; the tests themselves are skipped until the model exists."""

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

from ev_charging_data_unified_schema.config import ENV_PREFIX, REPO_ROOT

pytest.importorskip("dbt.cli.main")

MODEL = "fct_charging_session"
KEYS = ["session_sk"]
DBT_DIR = REPO_ROOT / "dbt"
PACKAGES_DIR = DBT_DIR / "dbt_packages"
MODEL_EXISTS = any(DBT_DIR.glob(f"models/**/{MODEL}.sql"))


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


@pytest.fixture(scope="session")
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


def _dbt_run(db_path: Path, landed_dir: Path, *, full_refresh: bool) -> None:
    cmd = [
        *_dbt_bin(),
        "build",
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
        json.dumps({"landed_dir": str(landed_dir)}),
    ]
    if full_refresh:
        cmd.append("--full-refresh")
    env = {
        **os.environ,
        ENV_PREFIX + "DUCKDB_PATH": str(db_path),
        ENV_PREFIX + "DUCKDB_THREADS": "1",
    }
    proc = subprocess.run(cmd, cwd=REPO_ROOT, env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-3000:]


def _table(db_path: Path) -> pd.DataFrame:
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        return (
            con.execute(f"select * from gold.{MODEL}").df().sort_values(KEYS).reset_index(drop=True)
        )
    finally:
        con.close()


def _checksum(df: pd.DataFrame) -> str:
    d = df[sorted(df.columns)].sort_values(KEYS).reset_index(drop=True)
    return hashlib.sha256(
        pd.util.hash_pandas_object(d, index=False).to_numpy().tobytes()
    ).hexdigest()


@pytest.mark.skipif(not MODEL_EXISTS, reason=f"Phase 4: {MODEL} does not exist yet")
def test_two_full_builds_are_content_identical(tmp_path, dbt_packages, fixtures_dir) -> None:
    landed = fixtures_dir / "landed"
    a, b = tmp_path / "a" / "w.duckdb", tmp_path / "b" / "w.duckdb"
    a.parent.mkdir()
    b.parent.mkdir()
    _dbt_run(a, landed, full_refresh=True)
    _dbt_run(b, landed, full_refresh=True)
    assert _checksum(_table(a)) == _checksum(_table(b))
