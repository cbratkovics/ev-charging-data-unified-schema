"""The profile renderer is pure over the artifact: a tiny artifact renders, the inventory block
is spliced between its markers, and --check detects a stale document."""

from __future__ import annotations

import importlib.util
import json

import pytest

from ev_charging_data_unified_schema.config import REPO_ROOT

spec = importlib.util.spec_from_file_location(
    "render_profile", REPO_ROOT / "scripts" / "render_profile.py"
)
rp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)

ART = {
    "run_id": "profile-20260101T000000Z",
    "code_commit": "abcdef1234567890",
    "generated_at_utc": "2026-01-01T00:00:00+00:00",
    "definitions": {"null_rate": "share of nulls"},
    "sources": {
        "cary": {
            "available": True,
            "files": [
                {
                    "path": "data/raw/cary/x.csv",
                    "sha256": "0" * 64,
                    "bytes": 10,
                    "rows": 3,
                    "columns": ["a"],
                    "exact_duplicate_rows": 0,
                    "download": {
                        "url": "u",
                        "retrieved_at": "2026-01-01T00:00:00+00:00",
                        "last_modified_header": None,
                    },
                    "column_profiles": [
                        {
                            "name": "a",
                            "inferred_type": "text",
                            "pattern": None,
                            "rows": 3,
                            "null_or_blank": 1,
                            "null_rate": 0.333,
                            "distinct": 2,
                            "sample_values": ["x"],
                        }
                    ],
                }
            ],
            "answers": {
                "fully_blank_rows": 0,
                "coverage": {
                    "start_min": "2020-01-01",
                    "start_max": "2020-01-02",
                    "sessions_by_year": {"2020": 3},
                    "files_by_start_range": {},
                },
                "session_id": {"column": None},
                "overlap": {
                    "natural_key": ["a"],
                    "exact_duplicate_rows": 0,
                    "natural_key_duplicate_rows": 0,
                    "keys_shared_between_files": {},
                },
                "stations": {
                    "station_id_column": None,
                    "station_name_column": "a",
                    "distinct_names": 2,
                    "null_names": 0,
                    "sessions_per_station": {
                        "count": 2,
                        "min": 1,
                        "median": 1.5,
                        "max": 2,
                        "stations_under_30_sessions": 2,
                    },
                },
                "port": {
                    "port_id_column": None,
                    "port_type_column": None,
                    "port_type_values": None,
                },
                "durations": {
                    "charging_duration_column": "d",
                    "connected_duration_column": None,
                    "start_column": "s",
                    "end_column": None,
                    "connected_duration_derivable_from_start_end": False,
                },
                "implausible": {
                    "rows": 3,
                    "energy_zero": 1,
                    "energy_null": 0,
                    "energy_negative": 0,
                    "charging_minutes_zero": 1,
                    "charging_minutes_null": 0,
                    "charging_over_24h": 0,
                    "energy_zero_with_charging_minutes_over_0": 0,
                    "energy_over_0_with_charging_minutes_zero": 0,
                    "connected_over_24h": None,
                    "charging_exceeds_connected": None,
                },
                "timezone": {
                    "assumed_zone": "America/New_York",
                    "start_format": "ISO_UTC",
                    "start_hour_histogram_as_published": {"0": 1, "12": 2},
                },
                "personal_data": {"user_level_columns": [], "columns_present": ["a"]},
            },
        },
        "palo_alto": {"available": False, "files": [], "reason": "portal down"},
    },
}


def test_render_profile_contains_run_id_and_numbers() -> None:
    md = rp.render_profile(ART)
    assert "profile-20260101T000000Z" in md and "abcdef123456" in md
    assert "| Energy zero | 1 | 33.33% |" in md
    assert "**Not profiled.** portal down" in md
    assert "No session identifier is published" in md


def test_inventory_is_spliced_between_markers_and_check_detects_staleness(
    tmp_path, monkeypatch
) -> None:
    doc = "# Sources\n\nintro\n\n<!-- generated:inventory start -->\nold\n<!-- generated:inventory end -->\n\ntail\n"
    block = rp.render_inventory(ART)
    out = rp.splice_inventory(doc, block)
    assert out.startswith(
        "# Sources\n\nintro\n\n<!-- generated:inventory start -->"
    ) and out.endswith("<!-- generated:inventory end -->\n\ntail\n")
    assert "`x.csv`" in out and "| 10 | 3 |" in out and "old" not in out
    with pytest.raises(SystemExit):
        rp.splice_inventory("no markers here", block)


def test_fmt_and_pct() -> None:
    assert rp.fmt(1234567) == "1,234,567" and rp.fmt(1.5) == "1.5" and rp.fmt(None) == "n/a"
    assert rp.pct(1, 3) == "33.33%" and rp.pct(None, 3) == "n/a" and rp.pct(1, 0) == "n/a"


def test_committed_docs_match_the_latest_artifact() -> None:
    """Claim discipline: docs/PROFILE.md and the inventory block are exactly what the newest
    artifact renders."""
    latest = REPO_ROOT / "artifacts" / "profile" / "latest.json"
    if not latest.exists():
        pytest.skip("no profile artifact committed yet")
    art = json.loads(rp.latest_artifact(REPO_ROOT / "artifacts" / "profile").read_text())
    assert (REPO_ROOT / "docs" / "PROFILE.md").read_text(encoding="utf-8") == rp.render_profile(art)
    ds = (REPO_ROOT / "docs" / "DATA_SOURCES.md").read_text(encoding="utf-8")
    assert rp.splice_inventory(ds, rp.render_inventory(art)) == ds
