"""Blocking idle on a hand-made case with a known answer (ADR-0013 item 6)."""

from __future__ import annotations

import pandas as pd

from ev_charging_data_unified_schema.findings import full_occupancy_idle


def _sessions(rows):
    df = pd.DataFrame(
        rows, columns=["station_key", "start_utc", "end_utc", "charging_minutes", "start_local"]
    )
    df["start_utc"] = pd.to_datetime(df["start_utc"], utc=True)
    df["end_utc"] = pd.to_datetime(df["end_utc"], utc=True)
    df["start_local"] = pd.to_datetime(df["start_local"])
    df["connected_minutes"] = (df["end_utc"] - df["start_utc"]).dt.total_seconds() / 60
    return df


def test_blocking_idle_counts_only_minutes_while_all_ports_are_busy() -> None:
    # station S has 2 ports (local = UTC - 7h). Session A 08:00-12:00 UTC charges 60 min, idle 09:00-12:00.
    # Session B 10:00-11:00 UTC charges 60 min (no idle). Both ports busy 10:00-11:00 -> A's idle is
    # blocking for exactly 60 of its 180 idle minutes. Session C at another time, alone: idle, never blocking.
    df = _sessions(
        [
            ("S", "2023-06-01 08:00:00", "2023-06-01 12:00:00", 60.0, "2023-06-01 01:00:00"),
            ("S", "2023-06-01 10:00:00", "2023-06-01 11:00:00", 60.0, "2023-06-01 03:00:00"),
            ("S", "2023-06-02 08:00:00", "2023-06-02 09:30:00", 30.0, "2023-06-02 01:00:00"),
        ]
    )
    out = full_occupancy_idle(df, pd.Series({"S": 2}))
    assert out["idle_minutes"] == 180.0 + 60.0
    assert out["full_occupancy_idle_minutes"] == 60.0
    assert out["connected_minutes"] == 240.0 + 60.0 + 90.0
    assert out["stations_with_full_occupancy_idle"] == 1 and out["stations"] == 1
    # hour profile: A's idle 09:00-12:00 UTC is local 02:00-05:00 (60 min in each of hours 2, 3, 4);
    # C's idle 08:30-09:30 UTC is local 01:30-02:30 (30 in hour 1, 30 in hour 2);
    # blocking 10:00-11:00 UTC is local hour 3
    assert out["by_local_hour"]["3"]["full_occupancy_idle_minutes"] == 60.0
    assert out["by_local_hour"]["1"]["idle_minutes"] == 30.0
    assert (
        out["by_local_hour"]["2"]["idle_minutes"] == 90.0
        and out["by_local_hour"]["4"]["idle_minutes"] == 60.0
    )
    assert sum(v["idle_minutes"] for v in out["by_local_hour"].values()) == 240.0
    # with one port, every idle minute of A while B is connected... B starts after A's charging ended,
    # and A alone occupies the single port: all of A's idle and C's idle are blocking
    one = full_occupancy_idle(df, pd.Series({"S": 1}))
    assert one["full_occupancy_idle_minutes"] == 240.0
