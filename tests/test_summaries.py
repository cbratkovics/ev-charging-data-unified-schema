"""The silver summary artifact is pure over the built warehouse. Runs against the fixture
warehouse (`make dbt-fixture` builds .duckdb/fixture.duckdb; CI builds it before pytest) and is
skipped when that file is absent."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from ev_charging_data_unified_schema.config import REPO_ROOT
from ev_charging_data_unified_schema.data.loader import read_manifest
from ev_charging_data_unified_schema.summaries import silver_summary

FIXTURE_DB = REPO_ROOT / ".duckdb" / "fixture.duckdb"
FIXTURE_LANDED = REPO_ROOT / "tests" / "fixtures" / "landed"


@pytest.fixture(scope="module")
def payload() -> dict:
    if not FIXTURE_DB.exists() or not (FIXTURE_LANDED / "manifest.json").exists():
        pytest.skip("fixture warehouse not built (make dbt-fixture)")
    con = duckdb.connect(str(FIXTURE_DB), read_only=True)
    try:
        return silver_summary(
            con, read_manifest(FIXTURE_LANDED), rid="silver-test", code_commit="abc"
        )
    finally:
        con.close()


def test_counts_conserve_and_primary_reasons_sum(payload) -> None:
    for name, s in payload["by_source"].items():
        assert s["bronze"] == s["accepted"] + s["quarantined"], name
        assert sum(s["by_primary_reason"].values()) == s["quarantined"], name
        assert s["non_trivial"] <= s["accepted"]
    for f in payload["by_file"]:
        assert f["bronze"] == f["accepted"] + f["quarantined"], f["source_file"]
        assert sum(f["by_primary_reason"].values()) == f["quarantined"]


def test_inputs_carry_hashes_and_the_fixture_exercises_the_rules(payload) -> None:
    assert payload["inputs"] and all(len(v["sha256"]) == 64 for v in payload["inputs"].values())
    b = payload["by_source"]["boulder"]
    assert b["by_primary_reason"].get("natural_key_duplicate", 0) >= 1
    assert b["by_primary_reason"].get("nonexistent_local_time", 0) == 0
    d = payload["by_source"]["dft_2017"]
    assert d["by_primary_reason"].get("end_sentinel_1970", 0) == 1
    assert "publisher_excluded_rule" in d["flags"] and "unknown_station" in d["flags"]
    assert payload["unknown_station"]["dft_2017"]["unknown_station_sessions"] >= 1
    assert "rapids_anomalies" in payload["publisher_rule"]["anomalies_not_meeting_rule"]
    assert Path(".").exists()


def test_station_attribute_ambiguity_and_collapsed_names_are_reported(payload) -> None:
    attrs = payload["station_attributes"]
    assert attrs["boulder"]["multi_site_key"] == 1 and attrs["boulder"]["multi_operator"] == 0
    assert attrs["dft_2017"]["multi_operator"] == 1
    assert attrs["cary"]["multi_site_key"] == 0
    names = payload["dft_operator_names"]
    assert names["distinct_raw"] - names["distinct_normalised"] == names["collapsed"] == 2
    assert names["groups"] == {
        "Fixture Council": ["Fixture  Council", "Fixture Council", "Fixture Council "]
    }
