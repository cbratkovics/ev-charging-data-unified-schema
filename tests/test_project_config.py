"""PROJECT is the one source of the vocabulary; every mirror must agree, and the tree holds
no secret and no paid target."""

from __future__ import annotations

import subprocess

import yaml

from ev_charging_data_unified_schema.config import PROJECT, REPO_ROOT, dbt_vars


def test_dbt_project_vars_mirror_the_config() -> None:
    project = yaml.safe_load((REPO_ROOT / "dbt" / "dbt_project.yml").read_text(encoding="utf-8"))
    assert {k: project["vars"][k] for k in dbt_vars()} == dbt_vars()
    assert project["name"] == PROJECT.dbt_project_name


def test_profiles_have_one_local_duckdb_target_and_no_token() -> None:
    text = (REPO_ROOT / "dbt" / "profiles.yml").read_text(encoding="utf-8")
    profile = yaml.safe_load(text)[PROJECT.dbt_project_name]
    assert set(profile["outputs"]) == {"dev"}
    assert profile["outputs"]["dev"]["type"] == "duckdb"
    assert "md:" not in text and "MOTHERDUCK_TOKEN" not in text


def test_only_the_env_example_is_tracked() -> None:
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    env_files = [p for p in tracked if p.split("/")[-1].startswith(".env")]
    assert env_files == [".env.example"]
    assert "no secret" in (REPO_ROOT / ".env.example").read_text(encoding="utf-8").lower()


def test_source_names_are_unique_and_snake_case() -> None:
    names = PROJECT.source_names
    assert len(set(names)) == len(names)
    assert all(n == n.lower() and n.replace("_", "").isalnum() for n in names)
