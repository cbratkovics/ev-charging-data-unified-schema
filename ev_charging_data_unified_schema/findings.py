"""Findings computed from gold and the sensitivity artifact (ADR-0013 items 5 and 6).

Every number a finding cites is computed here into ``artifacts/findings/<run_id>.json``;
``docs/FINDINGS.md`` is rendered from that artifact. Findings are within-source only.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import duckdb
import numpy as np
import pandas as pd

N_VALUES = (1, 2, 3, 5, 10)


def run_id(now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now(dt.UTC)
    return "findings-" + now.strftime("%Y%m%dT%H%M%SZ")


# --- Boulder idle -------------------------------------------------------------------------------


def full_occupancy_idle(sessions: pd.DataFrame, ports: pd.Series) -> dict[str, Any]:
    """Idle minutes accrued while every inferred port at the station was occupied ("idle at full
    occupancy"): an upper bound on displaced demand, because ports are lower bounds, every idle
    minute at a single-port station counts by definition, and there is no queue data.

    ``sessions``: non-trivial Boulder sessions with start_utc, end_utc, charging_minutes,
    connected_minutes, start_local, station_key. ``ports``: station_key -> port count. Per
    station, the connected intervals are swept; the windows where the running count reaches the
    port count are the blocking windows; each session's idle window [start + charging, end) is
    intersected with them (vectorised through the cumulative blocking time before any instant).
    Returns totals and an hour-of-day profile of idle and blocking-idle minutes (local hour in
    which the minutes elapsed).
    """
    total_idle = total_full = total_connected = total_charging = 0.0
    by_hour_idle = np.zeros(24)
    by_hour_full = np.zeros(24)
    stations_with_full = 0
    for key, g in sessions.groupby("station_key"):
        n_ports = int(ports.get(key, 1))
        g = g.dropna(subset=["start_utc", "end_utc"])
        g = g[g["end_utc"] > g["start_utc"]]
        if g.empty:
            continue
        start = (
            g["start_utc"]
            .dt.tz_convert("UTC")
            .dt.tz_localize(None)
            .to_numpy()
            .astype("datetime64[s]")
            .astype("int64")
        )
        end = (
            g["end_utc"]
            .dt.tz_convert("UTC")
            .dt.tz_localize(None)
            .to_numpy()
            .astype("datetime64[s]")
            .astype("int64")
        )
        offset_s = int(
            (
                g["start_local"].iloc[0]
                - g["start_utc"].iloc[0].tz_convert("UTC").tz_localize(None)
            ).total_seconds()
        )
        # sweep
        t = np.concatenate([start, end])
        d = np.concatenate([np.ones(len(start), dtype=int), -np.ones(len(end), dtype=int)])
        order = np.lexsort((d, t))  # ends (-1) before starts (+1) at equal instants
        t, d = t[order], d[order]
        c = np.cumsum(d)
        nxt = np.append(t[1:], t[-1])
        blk = (c >= n_ports) & (nxt > t)
        bs, be = t[blk], nxt[blk]
        # cumulative blocking seconds before each window start
        lengths = be - bs
        cum = np.concatenate([[0], np.cumsum(lengths)])

        idle_s = start + np.round(g["charging_minutes"].to_numpy() * 60).astype("int64")
        idle_e = end
        has_idle = idle_e > idle_s
        idle_s, idle_e = idle_s[has_idle], idle_e[has_idle]
        idle_total = float((idle_e - idle_s).sum()) / 60
        blocked = (
            _blocked_before(idle_e, bs, be, cum) - _blocked_before(idle_s, bs, be, cum)
            if len(idle_s)
            else np.array([])
        )
        station_full = float(blocked.sum()) / 60 if len(blocked) else 0.0
        total_idle += idle_total
        total_full += station_full
        if station_full > 0:
            stations_with_full += 1
        total_connected += float(g["connected_minutes"].sum())
        total_charging += float(g["charging_minutes"].sum())
        # hour profiles: explode intervals at local hour boundaries
        by_hour_idle += _hour_profile(idle_s + offset_s, idle_e + offset_s)
        if len(bs):
            # intersect idle intervals with blocking windows: candidate pairs by searchsorted range
            lo = np.searchsorted(be, idle_s, side="right")  # first window ending after idle start
            hi = np.searchsorted(bs, idle_e, side="left")  # windows starting before idle end
            counts = np.clip(hi - lo, 0, None)
            if counts.sum():
                i_idx = np.repeat(np.arange(len(idle_s)), counts)
                w_idx = np.concatenate(
                    [np.arange(a, a + n) for a, n in zip(lo, counts, strict=True) if n > 0]
                )
                s2 = np.maximum(idle_s[i_idx], bs[w_idx])
                e2 = np.minimum(idle_e[i_idx], be[w_idx])
                keep = e2 > s2
                by_hour_full += _hour_profile(s2[keep] + offset_s, e2[keep] + offset_s)
    return {
        "idle_minutes": round(total_idle, 3),
        "full_occupancy_idle_minutes": round(total_full, 3),
        "connected_minutes": round(total_connected, 3),
        "charging_minutes": round(total_charging, 3),
        "idle_share_of_connected": (
            round(total_idle / total_connected, 6) if total_connected else None
        ),
        "full_occupancy_idle_share_of_connected": (
            round(total_full / total_connected, 6) if total_connected else None
        ),
        "full_occupancy_share_of_idle": round(total_full / total_idle, 6) if total_idle else None,
        # how many times the headline idle share overstates the full-occupancy figure
        "idle_to_full_occupancy_ratio": round(total_idle / total_full, 3) if total_full else None,
        "stations_with_full_occupancy_idle": stations_with_full,
        "stations": int(sessions["station_key"].nunique()),
        "by_local_hour": {
            str(h): {
                "idle_minutes": round(float(by_hour_idle[h]), 3),
                "full_occupancy_idle_minutes": round(float(by_hour_full[h]), 3),
            }
            for h in range(24)
        },
    }


def _blocked_before(x: np.ndarray, bs: np.ndarray, be: np.ndarray, cum: np.ndarray) -> np.ndarray:
    """Seconds of blocking windows [bs, be) (sorted, non-overlapping; cum = cumulative lengths with
    a leading 0) that lie before each instant in x."""
    if len(bs) == 0:
        return np.zeros(len(x))
    j = np.searchsorted(bs, x, side="right")  # windows starting before or at x
    full = cum[j]
    prev = j - 1
    valid = prev >= 0
    over = np.where(valid, np.clip(be[np.clip(prev, 0, None)] - x, 0, None), 0)
    return full - over


def _hour_profile(start_s: np.ndarray, end_s: np.ndarray) -> np.ndarray:
    """Minutes of each [start, end) (local seconds since epoch) per hour of day, 24 buckets."""
    out = np.zeros(24)
    if len(start_s) == 0:
        return out
    first_hour = start_s // 3600
    last_hour = (end_s - 1) // 3600
    n = (last_hour - first_hour + 1).astype("int64")
    idx = np.repeat(np.arange(len(start_s)), n)
    hour = first_hour[idx] + (np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n))
    seg_s = np.maximum(start_s[idx], hour * 3600)
    seg_e = np.minimum(end_s[idx], (hour + 1) * 3600)
    np.add.at(out, (hour % 24).astype(int), (seg_e - seg_s) / 60)
    return out


# --- DfT anomalies population ---------------------------------------------------------------


def anomalies_population(
    con: duckdb.DuckDBPyConnection, family: str = "rapids_anomalies"
) -> dict[str, Any]:
    """Every landed row of the family: accepted (by publisher rule) + quarantined by primary
    reason, with natural_key_duplicate split by the surviving twin's family and status. The
    survivor of a natural key is the row of that key not flagged as a duplicate; it may itself be
    quarantined for a value reason."""
    base = con.execute(f"""
        with a as (select * from silver.slv_sessions__dft_2017 where source_family = '{family}')
        select count(*) as total,
               count(*) filter (where primary_reason is null) as accepted,
               count(*) filter (where primary_reason is null and publisher_excluded_rule) as accepted_meets_rule,
               count(*) filter (where primary_reason is null and not publisher_excluded_rule) as accepted_not_meeting_rule,
               count(*) filter (where primary_reason is not null) as quarantined
        from a
        """).df().iloc[0]
    reasons = con.execute(
        f"select primary_reason, count(*) as n from silver.slv_sessions__dft_2017 where source_family = '{family}' and primary_reason is not null group by 1 order by 2 desc"
    ).df()
    twins = con.execute(f"""
        with d as (
            select natural_key_hash from silver.slv_sessions__dft_2017
            where source_family = '{family}' and primary_reason = 'natural_key_duplicate'
        ),
        surv as (
            select natural_key_hash, source_family as twin_family,
                   case when primary_reason is null then 'accepted' else 'quarantined' end as twin_status
            from silver.slv_sessions__dft_2017
            where not list_contains(quarantine_reasons, 'natural_key_duplicate')
              and not list_contains(quarantine_reasons, 'exact_duplicate')
        )
        select coalesce(s.twin_family, '<none>') as twin_family, coalesce(s.twin_status, '<none>') as twin_status, count(*) as n
        from d left join surv as s using (natural_key_hash) group by 1, 2 order by 3 desc
        """).df()
    dup_split = {
        f"{r['twin_family']}/{r['twin_status']}": int(r["n"]) for r in twins.to_dict("records")
    }
    moved = sum(v for k, v in dup_split.items() if k.startswith("fasts/"))
    return {
        "family": family,
        "total": int(base["total"]),
        "accepted": int(base["accepted"]),
        "accepted_meets_rule": int(base["accepted_meets_rule"]),
        "accepted_not_meeting_rule": int(base["accepted_not_meeting_rule"]),
        "quarantined": int(base["quarantined"]),
        "quarantined_by_primary_reason": {
            r["primary_reason"]: int(r["n"]) for r in reasons.to_dict("records")
        },
        "natural_key_duplicate_by_twin": dup_split,
        "moved_to_fasts_raw": moved,
    }


# --- assembly -----------------------------------------------------------------------------------


def _df(con: duckdb.DuckDBPyConnection, sql: str) -> pd.DataFrame:
    return con.execute(sql).df()


def compute(
    con: duckdb.DuckDBPyConnection,
    sensitivity: dict[str, Any],
    silver: dict[str, Any],
    *,
    rid: str,
    code_commit: str,
) -> dict[str, Any]:
    periods = {
        r["source"]: {
            "first_start_local": str(r["first"]),
            "last_start_local": str(r["last"]),
            "sessions": int(r["n"]),
        }
        for r in con.execute(
            "select source, min(start_local) as first, max(start_local) as last, count(*) as n from gold.fct_charging_session group by 1 order by 1"
        )
        .df()
        .to_dict("records")
    }
    # Boulder idle under the production port count and each robust-max N
    b = _df(
        con,
        "select station_key, start_utc, end_utc, start_local, charging_minutes, connected_minutes from gold.fct_charging_session where source = 'boulder' and is_non_trivial and not contains(station_key, '/unknown/')",
    )
    prod_ports = _df(
        con, "select station_key, ports_inferred from gold.dim_station where source = 'boulder'"
    ).set_index("station_key")["ports_inferred"]
    idle = {"production": full_occupancy_idle(b, prod_ports)}
    # by station group: single-port stations count every idle minute as full occupancy by
    # definition; the multi-port group is where the measure carries information
    single = set(prod_ports[prod_ports == 1].index)
    idle_by_group = {
        "single_port": full_occupancy_idle(b[b["station_key"].isin(single)], prod_ports),
        "multi_port": full_occupancy_idle(b[~b["station_key"].isin(single)], prod_ports),
    }
    # alternative port counts from the sensitivity artifact's per-definition distributions are
    # source-wide; recompute per station with the same concurrency sweep the artifact used
    from ev_charging_data_unified_schema.sensitivity import concurrency_levels, ports_by_definition

    stations = _df(
        con, "select station_key, connector_ids from gold.dim_station where source = 'boulder'"
    )
    levels, _ = concurrency_levels(b.assign(end_utc=b["end_utc"]))
    defs = ports_by_definition(levels, stations)
    for label in (f"robust_max_n{n}" for n in N_VALUES):
        idle[label] = full_occupancy_idle(b, defs[label])
    # by-hour headline profile: idle minutes and full-occupancy idle minutes by local hour
    hour_rows = []
    for h in range(24):
        r = idle["production"]["by_local_hour"][str(h)]
        hour_rows.append({"hour": h, **r})
    # sensitivity ranges from the artifact
    ranges: dict[str, dict[str, Any]] = {}
    for r in sensitivity["results"]:
        if r["session_rule"] != "non_trivial_only" or r["utilization"] is None:
            continue
        k = f"{r['source']}__{r['flavour']}"
        ranges.setdefault(
            k,
            {
                "min": r["utilization"],
                "max": r["utilization"],
                "min_definition": r["definition"],
                "max_definition": r["definition"],
                "production": None,
                "over_100": {},
            },
        )
        if r["utilization"] < ranges[k]["min"]:
            ranges[k].update(min=r["utilization"], min_definition=r["definition"])
        if r["utilization"] > ranges[k]["max"]:
            ranges[k].update(max=r["utilization"], max_definition=r["definition"])
        ranges[k]["over_100"][r["definition"]] = r["station_days_over_100pct"]
    # production utilization from gold directly (ports_inferred as built)
    prod = _df(
        con,
        "select source, sum(connected_minutes) / nullif(sum(available_port_minutes), 0) as connected, sum(charging_minutes) / nullif(sum(available_port_minutes), 0) as charging, count(*) filter (where not is_excluded_day) as station_days from gold.fct_station_day where not is_excluded_day group by 1 order by 1",
    )
    for r in prod.to_dict("records"):
        for flavour in ("connected", "charging"):
            k = f"{r['source']}__{flavour}"
            if k in ranges and r[flavour] is not None and not pd.isna(r[flavour]):
                ranges[k]["production"] = round(float(r[flavour]), 6)
    # width of the range as a share of the production value: the error bar a denominator choice adds
    for rg in ranges.values():
        rg["relative_range"] = (
            round((rg["max"] - rg["min"]) / rg["production"], 6) if rg["production"] else None
        )
    over100_prod = _df(
        con,
        "select source, count(*) as n from gold.fct_station_day where not is_excluded_day and coalesce(connected_minutes, charging_minutes) > available_port_minutes group by 1",
    )
    # DfT publisher rule (from the silver summary)
    pr = silver["publisher_rule"]
    return {
        "artifact": "findings",
        "run_id": rid,
        "generated_at_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "code_commit": code_commit,
        "inputs": {"sensitivity_run_id": sensitivity["run_id"], "silver_run_id": silver["run_id"]},
        "definitions": {
            "idle_share_of_connected": "1 - charging minutes / connected minutes over non-trivial Boulder sessions at known stations",
            "full_occupancy_idle_share_of_connected": "idle minutes that elapsed while every inferred port at the station was occupied, over connected minutes; computed from the connected-interval sweep per station with the port count of the named definition",
            "full_occupancy_share_of_idle": "full-occupancy idle minutes over all idle minutes",
            "idle_to_full_occupancy_ratio": "idle minutes over full-occupancy idle minutes: how many times the headline idle share overstates the full-occupancy figure",
            "by_local_hour": "idle and full-occupancy idle minutes attributed to the local hour in which they elapsed",
            "utilization_range": "min and max of the sensitivity artifact's non-trivial-rule utilization across denominator definitions; production is the value under dim_station.ports_inferred; relative_range is (max - min) / production",
            "period": "first and last local session start per source in the fact",
        },
        "periods": periods,
        "boulder_idle": idle,
        "boulder_idle_by_station_group": idle_by_group,
        "dft_anomalies_population": anomalies_population(con),
        "boulder_idle_by_hour_production": hour_rows,
        "utilization_ranges": ranges,
        "station_days_over_100pct_production": {
            r["source"]: int(r["n"]) for r in over100_prod.to_dict("records")
        },
        "dft_publisher_rule": {"by_family": pr["by_family"]},
        "unknown_station": silver["unknown_station"],
        "cannot_show": [
            "no queue, arrival or turned-away-driver data exists in any source, so idle time is a ceiling on recoverable capacity, not demand",
            "port counts are inferred lower bounds (ADR-0012); a station with more ports than inferred has lower true utilization and less idle at full occupancy than reported",
            "the DfT publication covers calendar 2017 only; Boulder 2018-2023 and Cary 2012-2023 are single operators; nothing here compares operators",
            "charging time is assumed to begin at session start; the sources publish no charging profile",
        ],
    }
