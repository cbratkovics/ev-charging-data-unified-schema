"""Coherence of the committed findings and sensitivity artifacts: parts sum to wholes, shares
lie in [0, 1], production values lie inside their ranges (the number checker verifies keys,
not coherence; these tests do). Skipped when no artifact is committed."""

from __future__ import annotations

import json

import pytest

from ev_charging_data_unified_schema.config import ARTIFACTS_DIR


def _latest(kind: str) -> dict:
    d = ARTIFACTS_DIR / kind
    if not (d / "latest.json").exists():
        pytest.skip(f"no {kind} artifact committed")
    return json.loads((d / json.loads((d / "latest.json").read_text())["path"]).read_text())


@pytest.fixture(scope="module")
def findings() -> dict:
    return _latest("findings")


@pytest.fixture(scope="module")
def sensitivity() -> dict:
    return _latest("sensitivity")


def test_production_utilization_lies_inside_every_range(findings) -> None:
    for key, r in findings["utilization_ranges"].items():
        assert r["production"] is not None, key
        assert r["min"] - 1e-9 <= r["production"] <= r["max"] + 1e-9, (key, r)
        assert 0 <= r["min"] <= r["max"] <= 5, key  # utilization above 100% is possible but bounded


def test_idle_measures_are_shares_and_nest(findings) -> None:
    for label, v in {
        **findings["boulder_idle"],
        **findings["boulder_idle_by_station_group"],
    }.items():
        assert (
            0 <= v["full_occupancy_idle_minutes"] <= v["idle_minutes"] <= v["connected_minutes"]
        ), label
        for k in (
            "idle_share_of_connected",
            "full_occupancy_idle_share_of_connected",
            "full_occupancy_share_of_idle",
        ):
            assert 0 <= v[k] <= 1, (label, k)
        hours = v["by_local_hour"].values()
        assert abs(sum(h["idle_minutes"] for h in hours) - v["idle_minutes"]) < 1.0, label
        assert (
            abs(
                sum(h["full_occupancy_idle_minutes"] for h in hours)
                - v["full_occupancy_idle_minutes"]
            )
            < 1.0
        ), label
    g = findings["boulder_idle_by_station_group"]
    p = findings["boulder_idle"]["production"]
    assert g["single_port"]["stations"] + g["multi_port"]["stations"] == p["stations"]
    assert (
        abs(g["single_port"]["idle_minutes"] + g["multi_port"]["idle_minutes"] - p["idle_minutes"])
        < 1.0
    )
    assert (
        abs(
            g["single_port"]["full_occupancy_idle_minutes"]
            + g["multi_port"]["full_occupancy_idle_minutes"]
            - p["full_occupancy_idle_minutes"]
        )
        < 1.0
    )
    # single-port stations: every idle minute is at full occupancy by definition
    if g["single_port"]["idle_minutes"] > 0:
        assert g["single_port"]["full_occupancy_share_of_idle"] == pytest.approx(1.0, abs=1e-6)


def test_dft_anomalies_population_sums(findings) -> None:
    pop = findings["dft_anomalies_population"]
    assert pop["accepted"] == pop["accepted_meets_rule"] + pop["accepted_not_meeting_rule"]
    assert pop["quarantined"] == sum(pop["quarantined_by_primary_reason"].values())
    assert pop["total"] == pop["accepted"] + pop["quarantined"]
    dup = pop["quarantined_by_primary_reason"].get("natural_key_duplicate", 0)
    assert dup == sum(pop["natural_key_duplicate_by_twin"].values())
    assert pop["moved_to_fasts_raw"] == sum(
        v for k, v in pop["natural_key_duplicate_by_twin"].items() if k.startswith("fasts/")
    )
    assert pop["family"] == "rapids_anomalies"


def test_sensitivity_includes_the_production_definition_and_ranges_contain_it(sensitivity) -> None:
    defs = {r["definition"] for r in sensitivity["results"]}
    assert "production" in defs
    rows = [
        r
        for r in sensitivity["results"]
        if r["session_rule"] == "non_trivial_only" and r["utilization"] is not None
    ]
    by = {}
    for r in rows:
        by.setdefault((r["source"], r["flavour"]), {})[r["definition"]] = r["utilization"]
    for key, d in by.items():
        assert (
            d["production"] >= min(d.values()) - 1e-12
            and d["production"] <= max(d.values()) + 1e-12
        ), key
        for v in d.values():
            assert v >= 0
    for r in sensitivity["results"]:
        if r["station_days_over_100pct"] is not None:
            assert 0 <= r["station_days_over_100pct"] <= r["station_days"]
