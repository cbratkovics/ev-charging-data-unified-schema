"""docs/CONTRACTS.md is exactly what the contracts render to (ADR-0009 item 1)."""

from __future__ import annotations

import importlib.util

from ev_charging_data_unified_schema.config import REPO_ROOT

spec = importlib.util.spec_from_file_location(
    "render_contracts", REPO_ROOT / "scripts" / "render_contracts.py"
)
rc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rc)


def test_committed_contract_docs_match_the_code() -> None:
    assert (REPO_ROOT / "docs" / "CONTRACTS.md").read_text(encoding="utf-8") == rc.render()


def test_diff_table_shows_units_and_aliases_for_dft() -> None:
    md = rc.render()
    assert "integer, minutes" in md and "decimal, hours" in md
    assert "published as `EnergySupplied`, aliased to `Energy`" in md
