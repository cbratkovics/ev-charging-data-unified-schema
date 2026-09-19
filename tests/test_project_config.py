"""PROJECT is the one source of the vocabulary; every mirror must agree."""

from __future__ import annotations

import json

import yaml

from ev_charging_data_unified_schema.config import PROJECT, REPO_ROOT, dbt_vars, frontend_config


def test_dbt_project_vars_mirror_the_config() -> None:
    project = yaml.safe_load((REPO_ROOT / "dbt" / "dbt_project.yml").read_text(encoding="utf-8"))
    assert {k: project["vars"][k] for k in dbt_vars()} == dbt_vars()
    assert project["name"] == PROJECT.dbt_project_name


def test_frontend_config_json_is_regenerated() -> None:
    p = REPO_ROOT / "frontend" / "src" / "lib" / "project.config.json"
    if not p.exists():
        return  # frontend not generated
    assert (
        json.loads(p.read_text(encoding="utf-8")) == frontend_config()
    ), "run: python -m ev_charging_data_unified_schema.config --frontend > frontend/src/lib/project.config.json"


def test_scheduled_workflow_mirrors_the_config() -> None:
    wf = (REPO_ROOT / ".github" / "workflows" / "scheduled.yml").read_text(encoding="utf-8")
    assert f'cron: "{PROJECT.schedule_cron}"' in wf
    assert 'hf upload "$(python -m ev_charging_data_unified_schema.config hf_space)"' in wf


def test_profiles_name_the_configured_database() -> None:
    assert f"'{PROJECT.motherduck_database}'" in (REPO_ROOT / "dbt" / "profiles.yml").read_text(
        encoding="utf-8"
    )
