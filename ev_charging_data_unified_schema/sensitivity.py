"""The capacity-denominator sensitivity artifact (ADR-0006 h, ADR-0010 f, ADR-0011).

Computed from ``gold.fct_charging_session`` (so every definition uses the same sessions) and
``gold.dim_station`` (active windows and excluded days). For each source and each denominator
definition, connected-time and charging-time utilization as ratio of sums over the station's
available days, with and without the non-trivial rule, plus the count of station-days above
100% as a diagnostic of undercounted ports. Definitions:

* ``robust_max_n{1,2,3,5,10}``: highest concurrency level reached on at least N distinct local
  dates (N = 1 is the plain maximum);
* ``trailing_90d_max``: the Phase 1 proposal, the maximum concurrency over a trailing 90-day
  window ending on each station-day (a per-day denominator);
* ``connector_ids``: distinct published connector ids (DfT units that have them; others fall
  back to robust_max_n5 and are reported as such);
* ``registry``: registry port counts for matched stations (Phase 5; absent until then).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import duckdb
import pandas as pd

N_VALUES = (1, 2, 3, 5, 10)
LEVELS = (1, 2, 3, 4, 5, 6, 7, 8)


def run_id(now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now(dt.UTC)
    return "sensitivity-" + now.strftime("%Y%m%dT%H%M%SZ")


def _sessions(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute("""
        select station_key, source, start_utc, end_utc, start_local, end_local, energy_kwh,
               charging_minutes, connected_minutes, is_non_trivial, start_tz, port_id
        from gold.fct_charging_session
        """).df()


def _stations(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute(
        "select station_key, source, station_tz, ports_inferred, ports_source, active_from, active_to, excluded_days, window_days, connector_ids from gold.dim_station"
    ).df()


def _station_days(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute(
        "select station_key, source, local_date, is_excluded_day, day_minutes, charging_minutes, connected_minutes from gold.fct_station_day"
    ).df()


def concurrency_levels(sessions: pd.DataFrame) -> pd.DataFrame:
    """Per station: days at each concurrency level and a per-date max concurrency series.
    The charging window stands in for the connected window where end is null (Cary)."""
    s = sessions.copy()
    end = s["end_utc"].where(
        s["end_utc"].notna(),
        s["start_utc"] + pd.to_timedelta(s["charging_minutes"].fillna(0), unit="m"),
    )
    s["end_eff"] = end
    out_levels = []
    out_daily = []
    for key, g in s.groupby("station_key"):
        ev = pd.concat(
            [
                pd.DataFrame(
                    {"t": g["start_utc"], "d": 1, "date": g["start_local"].dt.normalize()}
                ),
                pd.DataFrame({"t": g["end_eff"], "d": -1, "date": pd.NaT}),
            ]
        ).sort_values(["t", "d"])
        ev["c"] = ev["d"].cumsum()
        starts = ev[ev["d"] == 1]
        for k in LEVELS:
            out_levels.append(
                {
                    "station_key": key,
                    "k": k,
                    "days": int(starts.loc[starts["c"] >= k, "date"].nunique()),
                }
            )
        daily = starts.groupby("date")["c"].max()
        out_daily.append(
            pd.DataFrame({"station_key": key, "date": daily.index, "max_c": daily.values})
        )
    levels = pd.DataFrame(out_levels)
    daily = (
        pd.concat(out_daily)
        if out_daily
        else pd.DataFrame(columns=["station_key", "date", "max_c"])
    )
    return levels, daily


def ports_by_definition(levels: pd.DataFrame, stations: pd.DataFrame) -> dict[str, pd.Series]:
    """Station-level port counts per definition (trailing_90d_max is per day and handled apart)."""
    out: dict[str, pd.Series] = {}
    for n in N_VALUES:
        rm = levels[levels["days"] >= n].groupby("station_key")["k"].max()
        out[f"robust_max_n{n}"] = (
            rm.reindex(stations["station_key"]).fillna(0).clip(lower=1).astype(int)
        )
    conn = stations.set_index("station_key")["connector_ids"]
    out["connector_ids"] = conn.where(conn > 0, out["robust_max_n5"]).astype(int)
    return out


def trailing_90d_ports(daily: pd.DataFrame, station_days: pd.DataFrame) -> pd.Series:
    """Per station-day: max concurrency over the trailing 90 days (including the day), floored
    at 1; indexed like station_days."""
    if daily.empty:
        return pd.Series(1, index=station_days.index)
    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"])
    frames = []
    for key, g in d.groupby("station_key"):
        series = g.set_index("date")["max_c"].sort_index()
        full = series.reindex(
            pd.date_range(series.index.min(), series.index.max(), freq="D")
        ).fillna(0)
        rolled = full.rolling("90D", min_periods=1).max()
        frames.append(
            pd.DataFrame({"station_key": key, "local_date": rolled.index, "ports": rolled.values})
        )
    roll = pd.concat(frames)
    sd = station_days[["station_key", "local_date"]].copy()
    sd["local_date"] = pd.to_datetime(sd["local_date"])
    merged = sd.merge(roll, on=["station_key", "local_date"], how="left")
    return merged["ports"].fillna(1).clip(lower=1).astype(int).set_axis(station_days.index)


def utilization_table(
    station_days: pd.DataFrame, ports: pd.Series, *, label: str
) -> list[dict[str, Any]]:
    sd = station_days[~station_days["is_excluded_day"]].copy()
    sd["ports"] = ports.loc[sd.index].values
    sd["available"] = sd["ports"] * sd["day_minutes"]
    rows = []
    for src, g in sd.groupby("source"):
        for flavour, col in (("connected", "connected_minutes"), ("charging", "charging_minutes")):
            num = g[col]
            if num.notna().sum() == 0:
                rows.append(
                    {
                        "source": src,
                        "definition": label,
                        "flavour": flavour,
                        "utilization": None,
                        "station_days": int(len(g)),
                        "station_days_with_measure": 0,
                        "station_days_over_100pct": None,
                    }
                )
                continue
            ratio = float(num.sum() / g["available"].sum()) if g["available"].sum() else None
            over = int(((num / g["available"]) > 1).sum())
            rows.append(
                {
                    "source": src,
                    "definition": label,
                    "flavour": flavour,
                    "utilization": None if ratio is None else round(ratio, 6),
                    "station_days": int(len(g)),
                    "station_days_with_measure": int(num.notna().sum()),
                    "station_days_over_100pct": over,
                }
            )
    return rows


def sensitivity(con: duckdb.DuckDBPyConnection, *, rid: str, code_commit: str) -> dict[str, Any]:
    sessions = _sessions(con)
    stations = _stations(con)
    station_days = _station_days(con).reset_index(drop=True)
    non_trivial = sessions[sessions["is_non_trivial"]]
    results: list[dict[str, Any]] = []
    port_tables: dict[str, dict[str, Any]] = {}
    for rule_label, sess in (("non_trivial_only", non_trivial), ("all_sessions", sessions)):
        levels, daily = concurrency_levels(sess)
        defs = ports_by_definition(levels, stations)
        for label, ports in defs.items():
            per_day = ports.reindex(station_days["station_key"]).set_axis(station_days.index)
            for r in utilization_table(station_days, per_day, label=label):
                results.append({"session_rule": rule_label, **r})
            if rule_label == "non_trivial_only":
                port_tables[label] = {
                    "distribution": {
                        str(k): int(v) for k, v in ports.value_counts().sort_index().items()
                    },
                    "stations": int(len(ports)),
                }
        t90 = trailing_90d_ports(daily, station_days)
        for r in utilization_table(station_days, t90, label="trailing_90d_max"):
            results.append({"session_rule": rule_label, **r})
    # note: the station-day measures themselves are over non-trivial sessions (fct_station_day);
    # the session rule only changes the concurrency evidence for the denominator
    dim_check = {
        "stations": int(len(stations)),
        "ports_source": {
            str(k): int(v) for k, v in stations["ports_source"].value_counts().items()
        },
        "ports_inferred_distribution": {
            str(k): int(v)
            for k, v in stations["ports_inferred"].value_counts().sort_index().items()
        },
        "excluded_days_total": int(stations["excluded_days"].sum()),
        "window_days_total": int(stations["window_days"].sum()),
    }
    return {
        "artifact": "sensitivity",
        "run_id": rid,
        "generated_at_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "code_commit": code_commit,
        "definitions": {
            "utilization": "sum of the measure minutes over sum of (ports x day minutes) across the source's available station-days (ratio of sums; never an average of daily ratios); the measure minutes are those of fct_station_day, which uses non-trivial sessions",
            "session_rule": "which sessions supply the concurrency evidence for the denominator: non_trivial_only (the production rule) or all_sessions",
            "robust_max_nN": "ports = highest concurrency level reached on at least N distinct local dates over the station's life, floored at 1",
            "trailing_90d_max": "ports on each station-day = maximum concurrency over the trailing 90 days ending that day, floored at 1 (the retired Phase 1 proposal)",
            "connector_ids": "ports = distinct published connector ids where the unit has any, else robust_max_n5",
            "station_days_over_100pct": "available station-days whose daily measure minutes exceed the day's available port minutes: undercounted ports or overlapping data errors",
            "production_definition": "dim_station.ports_inferred = connector_ids where present else robust_max_n5 (ADR-0007 item 4)",
        },
        "dim_station": dim_check,
        "ports_by_definition": port_tables,
        "results": results,
    }
