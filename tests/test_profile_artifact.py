"""Assertions on the committed profile artifact. These are the evidence-first form of tests on
real data: they run offline against artifacts/profile/latest.json and fail if a regenerated
artifact no longer supports a claim the design relies on."""

from __future__ import annotations

import json

import pytest

from ev_charging_data_unified_schema.config import ARTIFACTS_DIR, PROJECT

PROFILE_DIR = ARTIFACTS_DIR / "profile"


@pytest.fixture(scope="module")
def artifact() -> dict:
    latest = PROFILE_DIR / "latest.json"
    if not latest.exists():
        pytest.skip("no profile artifact committed yet")
    return json.loads((PROFILE_DIR / json.loads(latest.read_text())["path"]).read_text())


def test_artifact_covers_exactly_the_configured_sources(artifact) -> None:
    assert set(artifact["sources"]) == set(PROJECT.source_names)
    assert all(s["available"] for s in artifact["sources"].values())
    assert artifact["code_commit"] and artifact["run_id"].startswith("profile-")


def test_every_file_carries_hash_size_rows_and_download_provenance(artifact) -> None:
    for src in artifact["sources"].values():
        for f in src["files"]:
            assert len(f["sha256"]) == 64 and f["bytes"] > 0 and f["rows"] > 0
            assert f["download"]["url"].startswith("https://") and f["download"]["retrieved_at"]


def test_boulder_delivery_block_0_is_a_subset_of_block_1(artifact) -> None:
    """Amendment (b): the dedup rule prefers the latest delivery; that is only sound if the
    earlier delivery adds nothing. Every block-0 row's natural key must exist in the last block."""
    blocks = artifact["sources"]["boulder"]["answers"]["overlap"]["delivery_blocks"]["blocks"]
    assert len(blocks) == 2
    first, last = blocks
    assert first["rows_with_key_in_last_block"] == first["rows"]
    assert last["rows_with_key_in_last_block"] is None


def test_cary_timestamps_are_true_utc(artifact) -> None:
    """Amendment (c): the raw-hour usage profile shifts by about one hour between summer and
    winter, as it must if the +00:00 timestamps are UTC and habits are local."""
    shift = artifact["sources"]["cary"]["answers"]["timezone"]["seasonal_shift"]
    assert -1.5 < shift["summer_minus_winter_mean_raw_hour"] < -0.5


def test_wall_clock_sources_show_dst_gaps_on_transition_dates(artifact) -> None:
    for name in ("boulder", "dft_2017"):
        gaps = artifact["sources"][name]["answers"]["timezone"]["dst_transition_gaps"]
        spring = [v for d, v in gaps.items() if d[5:7] == "03"]
        fall = [v for d, v in gaps.items() if d[5:7] in ("10", "11")]
        assert any("60" in v["gap_minutes_counts"] for v in spring), name
        assert any("-60" in v["gap_minutes_counts"] for v in fall), name


def test_duration_availability_is_declared_per_source(artifact) -> None:
    """Amendment (e): each source declares which durations exist; nothing is imputed."""
    avail = {n: s["answers"]["durations"]["availability"] for n, s in artifact["sources"].items()}
    assert avail == {"boulder": "both", "cary": "charging_only", "dft_2017": "plug_in_only"}
