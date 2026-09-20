"""Pins the DuckDB / ICU timezone behaviour silver relies on (ADR-0009). If a DuckDB bump changes
any of these, the silver DST rules must be re-verified before the pin moves."""

from __future__ import annotations

import datetime as dt

import duckdb
import pytest

CASES = [
    # zone, ambiguous local, its UTC under second-occurrence resolution, nonexistent local, its round trip
    (
        "America/Denver",
        "2023-11-05 01:30:00",
        "2023-11-05 08:30:00",
        "2023-03-12 02:30:00",
        "2023-03-12 03:30:00",
    ),
    (
        "Europe/London",
        "2023-10-29 01:30:00",
        "2023-10-29 01:30:00",
        "2023-03-26 01:30:00",
        "2023-03-26 02:30:00",
    ),
]


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect()
    c.execute("SET autoinstall_known_extensions=false; SET autoload_known_extensions=false;")
    c.execute("LOAD icu")
    c.execute("SET TimeZone='UTC'")
    return c


def test_icu_is_statically_linked_and_loads_offline(con) -> None:
    row = con.execute(
        "select loaded, installed, install_mode from duckdb_extensions() where extension_name = 'icu'"
    ).fetchone()
    assert row == (True, True, "STATICALLY_LINKED")


@pytest.mark.parametrize("zone, amb, amb_utc, gap, gap_back", CASES)
def test_ambiguous_resolves_to_second_occurrence_and_nonexistent_shifts_forward(
    con, zone, amb, amb_utc, gap, gap_back
) -> None:
    utc = con.execute(f"select timezone('{zone}', TIMESTAMP '{amb}')").fetchone()[0]
    assert utc.astimezone(dt.UTC).replace(tzinfo=None) == dt.datetime.fromisoformat(amb_utc)
    back = con.execute(
        f"select timezone('{zone}', timezone('{zone}', TIMESTAMP '{amb}'))"
    ).fetchone()[0]
    assert back == dt.datetime.fromisoformat(amb)
    back_gap = con.execute(
        f"select timezone('{zone}', timezone('{zone}', TIMESTAMP '{gap}'))"
    ).fetchone()[0]
    assert back_gap == dt.datetime.fromisoformat(gap_back)


@pytest.mark.parametrize("zone, amb, _u, gap, _g", CASES)
def test_detection_rules_flag_exactly_the_edge_hours(con, zone, amb, _u, gap, _g) -> None:
    def rules(ts: str) -> tuple[bool, bool]:
        nonexistent, ambiguous = con.execute(f"""
            select
                timezone('{zone}', timezone('{zone}', TIMESTAMP '{ts}')) <> TIMESTAMP '{ts}',
                timezone('{zone}', timezone('{zone}', TIMESTAMP '{ts}')) = TIMESTAMP '{ts}'
                and timezone('{zone}', TIMESTAMP '{ts}') - timezone('{zone}', TIMESTAMP '{ts}' - INTERVAL 1 HOUR) = INTERVAL 2 HOUR
            """).fetchone()
        return bool(nonexistent), bool(ambiguous)

    assert rules(amb) == (False, True)
    assert rules(gap) == (True, False)
    hour_before_amb = (dt.datetime.fromisoformat(amb) - dt.timedelta(hours=1)).isoformat(sep=" ")
    hour_after_amb = (dt.datetime.fromisoformat(amb) + dt.timedelta(hours=1)).isoformat(sep=" ")
    assert rules(hour_before_amb) == (False, False)
    assert rules(hour_after_amb) == (False, False)
    assert rules("2023-06-15 12:00:00") == (False, False)
