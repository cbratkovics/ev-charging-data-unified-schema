"""Hosts the session fixture that installs the dbt packages for every test that shells out to
dbt (tests/test_dbt_gold.py imports it). A test that shells out to a tool owns that tool's
dependency install: the fixture runs ``dbt deps`` itself when a package is missing (console
script next to the interpreter), removes the empty ``<pkg> N`` directories macOS sometimes
leaves, and fails, never skips, when packages are still missing.

The Phase 0 scaffold test that lived here is superseded by tests/test_dbt_gold.py (two builds
content-identical, landing order, late re-delivery equals a full refresh)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from ev_charging_data_unified_schema.config import REPO_ROOT

pytest.importorskip("dbt.cli.main")

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


@pytest.fixture(scope="session")
def dbt_packages() -> None:
    """Install the dbt packages once per session, exactly like ``make dbt-deps``."""
    if _packages_installed():
        return
    cmd = [*_dbt_bin(), "deps", "--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR)]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    for d in PACKAGES_DIR.iterdir() if PACKAGES_DIR.exists() else []:
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    if proc.returncode != 0 or not _packages_installed():
        pytest.fail(
            "dbt deps failed or left packages missing\n"
            f"required: {_required_packages()}\nstdout:\n{proc.stdout[-3000:]}\nstderr:\n{proc.stderr[-3000:]}",
            pytrace=False,
        )


def test_dbt_packages_are_installed(dbt_packages) -> None:
    assert _packages_installed()
