"""CI must materialize a complete shared fixture before tests and catalog validation."""

from __future__ import annotations

import importlib.util

import yaml

from ev_charging_data_unified_schema.config import REPO_ROOT

spec = importlib.util.spec_from_file_location(
    "check_dbt_descriptions", REPO_ROOT / "scripts" / "check_dbt_descriptions.py"
)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def _steps() -> list[dict]:
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text())
    return workflow["jobs"]["checks"]["steps"]


def test_ci_builds_complete_fixture_before_pytest_and_docs() -> None:
    steps = _steps()
    names = [step.get("name") for step in steps]
    build_index = names.index("Build complete fixture warehouse")
    test_index = next(i for i, name in enumerate(names) if name and name.startswith("Tests "))
    docs_index = names.index("dbt docs generate + every model, column and source described")
    assert build_index < test_index < docs_index

    build = steps[build_index]
    assert build["env"] == {
        "EV_CHARGING_DATA_UNIFIED_SCHEMA_DUCKDB_PATH": ".duckdb/fixture.duckdb",
        "EV_CHARGING_DATA_UNIFIED_SCHEMA_DUCKDB_THREADS": "1",
    }
    assert "make fixture-landed PY=python" in build["run"]
    assert "dbt build" in build["run"] and "--full-refresh" in build["run"]
    assert "--select" not in build["run"] and "--state" not in build["run"]
    assert not any("Slim CI state" == name for name in names)

    assert "python -m pytest tests -ra" in steps[test_index]["run"]
    docs = steps[docs_index]
    assert (
        docs["env"]["EV_CHARGING_DATA_UNIFIED_SCHEMA_DUCKDB_PATH"]
        == build["env"]["EV_CHARGING_DATA_UNIFIED_SCHEMA_DUCKDB_PATH"]
    )
    assert "dbt docs generate" in docs["run"]
    assert "python scripts/check_dbt_descriptions.py" in docs["run"]


def test_description_checker_rejects_documented_model_absent_from_catalog() -> None:
    manifest = {
        "nodes": {
            "model.project.documented": {
                "resource_type": "model",
                "name": "documented",
                "description": "A documented model.",
                "columns": {"id": {"description": "Primary key."}},
            }
        },
        "sources": {},
        "exposures": {},
    }
    gaps = checker.find_gaps(manifest, {"nodes": {}})
    assert gaps == ["model documented: not in catalog.json (was it built before docs generate?)"]
