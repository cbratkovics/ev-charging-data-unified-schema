#!/usr/bin/env python
"""Profile the raw source files into artifacts/profile/<run_id>.json.

Generic column profiles come from ``ev_charging_data_unified_schema.profiling``; the
source-specific questions (stable session id, overlapping files or deliveries, station ids vs
names, port identifiers, which durations exist, implausible-session shares, timezone evidence,
observed concurrency per station) are answered here from declared column roles. docs/PROFILE.md
and the inventory block of docs/DATA_SOURCES.md are rendered from the artifact by
scripts/render_profile.py; no number is typed by hand.

    python scripts/profile_sources.py [--raw-dir data/raw] [--out artifacts/profile]
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ev_charging_data_unified_schema import __version__, acquire  # noqa: E402
from ev_charging_data_unified_schema import profiling as pr
from ev_charging_data_unified_schema.config import ARTIFACTS_DIR, RAW_DIR  # noqa: E402
from ev_charging_data_unified_schema.profiling import (  # noqa: E402
    dst_transition_gaps,
    hms_to_minutes,
    max_concurrency,
    parse_mixed_us,
)

# DST transition dates (local) covered by the data, per zone.
DST_DENVER = [
    "2018-03-11",
    "2018-11-04",
    "2019-03-10",
    "2019-11-03",
    "2020-03-08",
    "2020-11-01",
    "2021-03-14",
    "2021-11-07",
    "2022-03-13",
    "2022-11-06",
    "2023-03-12",
    "2023-11-05",
]

# Column roles per source. Names are the raw headers exactly as published.
ROLES: dict[str, dict[str, Any]] = {
    "cary": {
        "files": ["electric-vehicle-charging-stations.csv"],
        "read": {"encoding": "utf-8-sig"},
        "timezone": "America/New_York",
        "session_id": None,
        "station_id": None,
        "station_name": "station_name",
        "port_id": None,
        "start": "start_date",
        "end": None,
        "start_format": "ISO_UTC",
        "charging_duration": "charging_time_hh_mm_ss",
        "connected_duration": None,
        "energy_kwh": "energy_kwh",
        "tz_label": None,
        "user_level_columns": [],
        "natural_key": ["station_name", "start_date"],
        "rated_kw_ceiling": 20.0,
        "seasonal_shift_check": True,
    },
    "boulder": {
        "files": ["Electric_Vehicle_Charging_Station_Data.csv"],
        "read": {"encoding": "utf-8-sig"},
        "timezone": "America/Denver",
        "session_id": None,
        "row_id": "ObjectId2",
        "delivery_row_id": "ObjectID",
        "station_id": None,
        "station_name": "Station_Name",
        "site_key": "Address",
        "port_id": None,
        "port_type": "Port_Type",
        "start": "Start_Date___Time",
        "end": "End_Date___Time",
        "start_format": "MIXED_US",
        "charging_duration": "Charging_Time__hh_mm_ss_",
        "connected_duration": "Total_Duration__hh_mm_ss_",
        "energy_kwh": "Energy__kWh_",
        "tz_label": "Start_Time_Zone",
        "user_level_columns": [],
        "natural_key": ["Station_Name", "_start_min", "_end_min", "_energy"],
        "dst_transitions": DST_DENVER,
        "rated_kw_ceiling": 20.0,
    },
    "dft_2017": {
        "files": [
            "dft_2017_local_authority_rapids_raw.csv",
            "dft_2017_local_authority_rapids_incomplete_anomalies.csv",
            "dft_2017_public_sector_fasts_raw.csv",
            "dft_2017_public_sector_fasts_incomplete_anomalies.csv",
        ],
        "read": {},
        "na_tokens": ["NA"],
        "timezone": "Europe/London",
        "session_id": "ChargingEvent",
        "station_id": "CPID",
        "station_name": None,
        "site_key": "Name",
        "port_id": "Connector",
        "port_type": None,
        "start": "StartDate",
        "start_time": "StartTime",
        "end": "EndDate",
        "end_time": "EndTime",
        "start_format": "DATE_PLUS_TIME",
        "charging_duration": None,
        "connected_duration": "PluginDuration",
        "connected_duration_kind": "numeric",
        "connected_duration_unit_by_file": {
            "dft_2017_local_authority_rapids_raw.csv": "minutes",
            "dft_2017_public_sector_fasts_raw.csv": "hours",
            "dft_2017_public_sector_fasts_incomplete_anomalies.csv": "hours",
        },
        "energy_kwh": "Energy",
        "tz_label": None,
        "user_level_columns": [],
        "natural_key": ["CPID", "Connector", "_start_min", "_end_min", "_energy"],
        "aliases": {"EnergySupplied": "Energy", "Unnamed: 0": "_publisher_row_index"},
        "dst_transitions": ["2017-03-26", "2017-10-29"],
        "file_family": {
            "dft_2017_local_authority_rapids_raw.csv": "rapids",
            "dft_2017_local_authority_rapids_incomplete_anomalies.csv": "rapids_anomalies",
            "dft_2017_public_sector_fasts_raw.csv": "fasts",
            "dft_2017_public_sector_fasts_incomplete_anomalies.csv": "fasts_anomalies",
        },
        "rated_kw_ceiling": 60.0,
    },
}


def parse_times(
    frame: pd.DataFrame, roles: dict[str, Any]
) -> tuple[pd.Series, pd.Series | None, dict]:
    notes: dict[str, Any] = {}
    fmt = roles["start_format"]
    end: pd.Series | None = None
    if fmt == "MIXED_US":
        start, notes["start_formats"] = parse_mixed_us(frame[roles["start"]])
        end, notes["end_formats"] = parse_mixed_us(frame[roles["end"]])
    elif fmt == "ISO_UTC":
        start = pd.to_datetime(
            frame[roles["start"]].astype("string"), utc=True, format="ISO8601", errors="coerce"
        ).dt.tz_localize(None)
    elif fmt == "DATE_PLUS_TIME":
        start, notes["start_date_formats"] = parse_date_plus_time(
            frame[roles["start"]], frame[roles["start_time"]]
        )
        end, notes["end_date_formats"] = parse_date_plus_time(
            frame[roles["end"]], frame[roles["end_time"]]
        )
    else:  # pragma: no cover
        raise ValueError(fmt)
    notes["start_parse_failures"] = int(start.isna().sum())
    if end is not None:
        notes["end_parse_failures"] = int(end.isna().sum())
    return start, end, notes


def parse_date_plus_time(date: pd.Series, time: pd.Series) -> tuple[pd.Series, dict[str, int]]:
    """Separate date and time columns; the date is ISO (YYYY-MM-DD) or day-first (DD/MM/YYYY),
    decided per value. Returns naive timestamps and the count of each date shape."""
    d = date.astype("string").str.strip()
    tm = time.astype("string").str.strip()
    iso = d.str.match(r"^\d{4}-\d{2}-\d{2}$").fillna(False).astype(bool)
    dmy = d.str.match(r"^\d{1,2}/\d{1,2}/\d{4}$").fillna(False).astype(bool)
    out = pd.Series(pd.NaT, index=date.index, dtype="datetime64[ns]")
    out[iso] = pd.to_datetime(d[iso] + " " + tm[iso], format="%Y-%m-%d %H:%M:%S", errors="coerce")
    out[dmy] = pd.to_datetime(d[dmy] + " " + tm[dmy], format="%d/%m/%Y %H:%M:%S", errors="coerce")
    return out, {
        "iso_rows": int(iso.sum()),
        "slash_rows": int(dmy.sum()),
        "other_rows": int((~iso & ~dmy).sum()),
    }


def duration_minutes(rows: pd.DataFrame, roles: dict[str, Any], col_key: str) -> pd.Series | None:
    """A duration column as minutes: hh:mm:ss text, or a number whose unit is declared per file
    (the DfT files publish PluginDuration in minutes in one file and hours in the others)."""
    col = roles.get(col_key)
    if not col:
        return None
    if roles.get(col_key + "_kind") != "numeric":
        return hms_to_minutes(rows[col])
    num = pd.to_numeric(rows[col], errors="coerce")
    units = roles.get(col_key + "_unit_by_file", {})
    factor = rows["_file"].map(
        lambda f: {"minutes": 1.0, "hours": 60.0}.get(units.get(f), float("nan"))
    )
    return num * factor


def days_at_level(
    start: pd.Series, end: pd.Series, by: pd.Series, levels: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 8)
) -> pd.DataFrame:
    """Per key: the number of distinct local dates on which the concurrency reaches each level.
    A sweep per key; a day counts for level k when at some instant on that day k sessions overlap.
    Basis for the robust-max port count (a level counts only if reached on >= N distinct days)."""
    df = pd.DataFrame({"s": start, "e": end, "k": by}).dropna()
    df = df[df["e"] >= df["s"]]
    out = {}
    for key, g in df.groupby("k"):
        ev = pd.concat(
            [pd.DataFrame({"t": g["s"], "d": 1}), pd.DataFrame({"t": g["e"], "d": -1})]
        ).sort_values(["t", "d"])
        ev["c"] = ev["d"].cumsum()
        ev = ev[ev["d"] == 1]
        day = ev["t"].dt.normalize()
        out[str(key)] = {str(k): int(day[ev["c"] >= k].nunique()) for k in levels}
    return pd.DataFrame(out).T.fillna(0).astype(int)


def robust_max_distribution(
    dal: pd.DataFrame, n_values: tuple[int, ...] = (1, 2, 3, 5, 10, 20, 30)
) -> dict[str, dict[str, int]]:
    """For each N: histogram over keys of the highest level reached on at least N distinct days."""
    levels = sorted(int(c) for c in dal.columns)
    out = {}
    for n in n_values:
        rm = pd.Series(0, index=dal.index)
        for k in levels:
            rm[dal[str(k)] >= n] = k
        out[str(n)] = hist(rm)
    return out


def inter_session_gaps(start: pd.Series, end: pd.Series, by: pd.Series) -> dict[str, Any]:
    """Per key, the gap in days between one session's end and the next session's start. The
    distribution calibrates the zero-session-gap threshold for the active window."""
    df = pd.DataFrame({"s": start, "e": end, "k": by}).dropna().sort_values(["k", "s"])
    df["next_s"] = df.groupby("k")["s"].shift(-1)
    gap = (df["next_s"] - df["e"]).dt.total_seconds() / 86400
    gap = gap.dropna()
    gap = gap[gap >= 0]
    q = gap.quantile([0.5, 0.9, 0.99, 0.999, 1.0])
    return {
        "gaps": int(len(gap)),
        "quantiles_days": {str(k): round(float(v), 3) for k, v in q.items()},
        "gaps_over_days": {str(d): int((gap > d).sum()) for d in (1, 3, 7, 14, 30, 60, 90)},
        "keys_with_a_gap_over_30d": int(
            df.assign(g=(df["next_s"] - df["e"]).dt.total_seconds() / 86400)
            .query("g > 30")["k"]
            .nunique()
        ),
    }


def seasonal_hour_shift(start_utc: pd.Series, zone: str) -> dict[str, Any]:
    """Amendment (c): if the published +00:00 timestamps are true UTC, the raw-hour usage profile
    shifts by one hour between summer (DST) and winter, because people keep local habits. If they
    were local time mislabelled, the raw profiles would coincide. Reports the circular mean hour
    of the raw profile in each half and the difference."""
    import math

    local = start_utc.dt.tz_localize("UTC").dt.tz_convert(zone)
    is_dst = local.map(lambda x: bool(x.dst())) if len(local) else pd.Series([], dtype=bool)
    out: dict[str, Any] = {}
    means = {}
    for label, mask in (("summer_dst", is_dst), ("winter_std", ~is_dst)):
        h = start_utc[mask].dt.hour + start_utc[mask].dt.minute / 60
        ang = h * 2 * math.pi / 24
        m = math.atan2(ang.map(math.sin).mean(), ang.map(math.cos).mean()) * 24 / (2 * math.pi) % 24
        means[label] = round(float(m), 3)
        out[label] = {
            "rows": int(mask.sum()),
            "raw_hour_histogram": hist(start_utc[mask].dt.hour),
            "circular_mean_raw_hour": means[label],
        }
    diff = (means["summer_dst"] - means["winter_std"] + 12) % 24 - 12
    out["summer_minus_winter_mean_raw_hour"] = round(float(diff), 3)
    out["reading"] = (
        "about -1 means the raw hours are true UTC (local habits fixed, UTC hour earlier in summer); about 0 means the raw hours are already local"
    )
    return out


def hist(s: pd.Series) -> dict[str, int]:
    return {str(k): int(v) for k, v in s.value_counts().sort_index().items()}


def delivery_blocks(rows: pd.DataFrame, roles: dict[str, Any], nk: list[str]) -> dict[str, Any]:
    """A per-delivery row id that restarts at 0 inside one file marks concatenated deliveries.
    Compare each block with the last one on the natural key."""
    rid = pd.to_numeric(rows[roles["delivery_row_id"]], errors="coerce")
    starts = [int(i) for i in rows.index[rid == 0]]
    bounds = [*starts, len(rows)]
    blocks = [rows.iloc[bounds[i] : bounds[i + 1]] for i in range(len(starts))]
    last = blocks[-1]
    last_keys = last.set_index(nk).index
    out: dict[str, Any] = {
        "blocks": [],
        "note": "block i is compared with the last block on the natural key",
    }
    for i, blk in enumerate(blocks):
        contained = (
            int(blk.set_index(nk).index.isin(last_keys).sum()) if i < len(blocks) - 1 else None
        )
        out["blocks"].append(
            {
                "index": i,
                "first_row": int(bounds[i]),
                "rows": int(len(blk)),
                "start_min": str(blk["_start"].min()),
                "start_max": str(blk["_start"].max()),
                "rows_with_key_in_last_block": contained,
                "natural_key_duplicates_within_block": int(blk.duplicated(nk).sum()),
                "iso_format_rows": int(
                    blk[roles["start"]].astype("string").str.match(r"^\d{4}-").fillna(False).sum()
                ),
            }
        )
    return out


def redelivery_diff(
    frames: dict[str, pd.DataFrame], a: str, b: str, sid: str, cols: list[str]
) -> dict[str, Any]:
    p, q = frames[a], frames[b]
    ps, qs = set(p[sid].dropna()), set(q[sid].dropna())
    shared = ps & qs
    sp = p[p[sid].isin(shared)].drop_duplicates(sid).set_index(sid)
    sq = q[q[sid].isin(shared)].drop_duplicates(sid).set_index(sid)
    dm = sp[cols].fillna("") != sq.loc[sp.index, cols].fillna("")
    return {
        "files": [a, b],
        "ids_a": len(ps),
        "ids_b": len(qs),
        "ids_shared": len(shared),
        "ids_only_a": len(ps - qs),
        "ids_only_b": len(qs - ps),
        "shared_ids_with_any_differing_value": int(dm.any(axis=1).sum()),
        "differing_by_column": {c: int(v) for c, v in dm.sum().items()},
    }


def profile_source(name: str, roles: dict[str, Any], raw_dir: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    frames: dict[str, pd.DataFrame] = {}
    downloads = acquire.read_records(raw_dir / name)
    for fname in roles["files"]:
        path = raw_dir / name / fname
        if not path.exists():
            files.append({"path": str(path), "missing": True})
            continue
        frame = pr.read_raw_strings(path, **roles.get("read", {}))
        fp = pr.file_profile_dict(pr.profile_file(path, frame))
        if roles.get("na_tokens"):
            fp["na_token_counts"] = {
                c: int(frame[c].isin(roles["na_tokens"]).sum())
                for c in frame.columns
                if frame[c].isin(roles["na_tokens"]).any()
            }
            frame = frame.mask(frame.isin(roles["na_tokens"]))
        if roles.get("file_family"):
            fp["family"] = roles["file_family"].get(fname)
        rec = downloads.get(fname)
        fp["download"] = (
            {
                "url": rec.url,
                "retrieved_at": rec.retrieved_at,
                "last_modified_header": rec.last_modified,
            }
            if rec
            else None
        )
        files.append(fp)
        frame = frame.rename(columns=roles.get("aliases", {}))
        frame["_file"] = fname
        frames[fname] = frame
    if not frames:
        return {"files": files, "available": False}
    all_rows = pd.concat(frames.values(), ignore_index=True)
    src_cols = [c for c in all_rows.columns if c != "_file"]
    blank = all_rows[src_cols].isna().all(axis=1)
    answers: dict[str, Any] = {
        "rows_all_files": int(len(all_rows)),
        "fully_blank_rows": int(blank.sum()),
    }
    rows = all_rows[~blank].copy()
    start, end, tnotes = parse_times(rows, roles)
    rows["_start"] = start
    energy = pd.to_numeric(rows[roles["energy_kwh"]], errors="coerce")
    rows["_energy"] = energy
    chg = duration_minutes(rows, roles, "charging_duration")
    con = duration_minutes(rows, roles, "connected_duration")
    if end is not None:
        rows["_start_min"], rows["_end_min"] = start.dt.floor("min"), end.dt.floor("min")

    # 1. stable session id
    sid = roles["session_id"]
    if sid:
        s = rows[sid]
        answers["session_id"] = {
            "column": sid,
            "null_count": int(s.isna().sum()),
            "distinct": int(s.nunique()),
            "rows": int(len(s)),
            "duplicate_ids_within_files": int(rows.duplicated([sid, "_file"]).sum()),
            "ids_in_more_than_one_file": int(
                rows.drop_duplicates([sid, "_file"]).duplicated(sid).sum()
            ),
        }
    else:
        answers["session_id"] = {"column": None, "note": "no session identifier published"}

    # 2. overlap / re-delivery
    nk = roles["natural_key"]
    per_file_overlap: dict[str, int] = {}
    if len(frames) > 1:
        key_files = (
            rows.drop_duplicates(nk + ["_file"]).groupby(nk, dropna=False)["_file"].agg(list)
        )
        multi = key_files[key_files.map(len) > 1]
        per_file_overlap = {
            str(k): int(v)
            for k, v in multi.map(lambda fs: " & ".join(sorted(fs))).value_counts().items()
        }
    answers["overlap"] = {
        "natural_key": nk,
        "exact_duplicate_rows": int(rows.duplicated(src_cols).sum()),
        "natural_key_duplicate_rows": int(rows.duplicated(nk).sum()),
        "keys_shared_between_files": per_file_overlap,
    }
    if roles.get("delivery_row_id"):
        answers["overlap"]["delivery_blocks"] = delivery_blocks(rows, roles, nk)
    if roles["charging_duration"] and not roles["end"]:
        # natural-key conflicts: what differs between the rows sharing a key
        dup = rows[rows.duplicated(nk, keep=False)]
        if len(dup):
            g = dup.groupby(nk)
            answers["overlap"]["natural_key_conflicts"] = {
                "groups": int(g.ngroups),
                "groups_where_one_row_has_zero_charging_and_zero_energy": int(
                    g.apply(
                        lambda x: bool(
                            (
                                (hms_to_minutes(x[roles["charging_duration"]]) == 0)
                                & (pd.to_numeric(x[roles["energy_kwh"]], errors="coerce") == 0)
                            ).any()
                        )
                    ).sum()
                ),
                "groups_where_rows_differ_in_energy": int(
                    g[roles["energy_kwh"]].nunique().gt(1).sum()
                ),
                "note": "a zero-duration, zero-energy row beside a real row at the same second is an aborted plug-in; the rule keeps the row with the larger charging time",
            }
    if roles.get("redelivery_pair"):
        a, b = roles["redelivery_pair"]
        answers["overlap"]["redelivery_diff"] = redelivery_diff(
            frames, a, b, sid, [c for c in src_cols if c != sid]
        )

    # 3. station ids vs names
    st_id, st_name = roles["station_id"], roles["station_name"]
    st: dict[str, Any] = {"station_id_column": st_id, "station_name_column": st_name}
    if st_name:
        st["distinct_names"] = int(rows[st_name].nunique())
        st["null_names"] = int(rows[st_name].isna().sum())
    if roles.get("site_key"):
        st["site_key_column"] = roles["site_key"]
        st["distinct_site_keys"] = int(rows[roles["site_key"]].nunique())
        st["names_per_site_key"] = hist(rows.groupby(roles["site_key"])[st_name or st_id].nunique())
    if st_id:
        st["distinct_ids"] = int(rows[st_id].nunique())
        st["null_ids"] = int(rows[st_id].isna().sum())
        grp = st_name or roles.get("site_key")
        if grp:
            both = rows.dropna(subset=[st_id, grp])
            st["names_with_multiple_ids"] = int((both.groupby(grp)[st_id].nunique() > 1).sum())
            st["ids_with_multiple_names"] = int((both.groupby(st_id)[grp].nunique() > 1).sum())
            st["grouping_column_for_the_two_counts_above"] = grp
        ids = rows[st_id].astype("string")
        st["id_forms"] = {
            "numeric": int(ids.str.fullmatch(r"\d+").fillna(False).sum()),
            "prefixed_or_text": int((~ids.str.fullmatch(r"\d+").fillna(True)).sum()),
            "null": int(ids.isna().sum()),
        }
    per = rows.groupby(st_id or st_name)["_start"].agg(["size", "min", "max"])
    st["sessions_per_station"] = {
        "count": int(len(per)),
        "min": int(per["size"].min()),
        "median": float(per["size"].median()),
        "max": int(per["size"].max()),
        "stations_under_30_sessions": int((per["size"] < 30).sum()),
    }
    answers["stations"] = st

    # 4. port / plug identifier
    if roles["port_id"] and st_id:
        pp = (
            rows.dropna(subset=[st_id, roles["port_id"]]).groupby(st_id)[roles["port_id"]].nunique()
        )
        port_info = {
            "port_id_values": hist(rows[roles["port_id"]].fillna("<null>")),
            "ports_per_station_id": hist(pp),
            "rows_with_null_port_id": int(rows[roles["port_id"]].isna().sum()),
        }
    else:
        port_info = {}
    answers["port"] = {
        **port_info,
        "port_id_column": roles["port_id"],
        "port_type_column": roles.get("port_type"),
        "port_type_values": (
            hist(rows[roles["port_type"]].fillna("<null>")) if roles.get("port_type") else None
        ),
    }

    # 5. durations available
    answers["durations"] = {
        "availability": (
            "both"
            if roles["charging_duration"] and (roles["connected_duration"] or roles["end"])
            else (
                "charging_only"
                if roles["charging_duration"]
                else "plug_in_only" if (roles["connected_duration"] or roles["end"]) else "none"
            )
        ),
        "connected_duration_unit_by_file": roles.get("connected_duration_unit_by_file"),
        "charging_duration_column": roles["charging_duration"],
        "connected_duration_column": roles["connected_duration"],
        "start_column": roles["start"],
        "end_column": roles["end"],
        "connected_duration_derivable_from_start_end": bool(roles["start"] and roles["end"]),
    }
    if con is not None and chg is not None:
        answers["durations"]["idle_share_of_connected_minutes"] = round(
            float(1 - chg.sum() / con.sum()), 6
        )
    if end is not None and chg is not None:
        span = (end - start).dt.total_seconds() / 60
        ref = con if con is not None else chg
        gap = span - ref
        answers["durations"]["span_vs_recorded_duration"] = {
            "compared_with": roles["connected_duration"] or roles["charging_duration"],
            "rows_compared": int(gap.notna().sum()),
            "within_2_min": int(gap.abs().le(2).sum()),
            "span_longer_by_over_5_min": int((gap > 5).sum()),
            "span_shorter_by_over_5_min": int((gap < -5).sum()),
            "one_hour_gap_rows": int(gap.abs().between(55, 65).sum()),
            "one_hour_gap_by_month": hist(
                start[gap.abs().between(55, 65)].dt.to_period("M").astype(str)
            ),
        }

    # 6. implausible sessions
    n = len(rows)
    imp: dict[str, Any] = {
        "rows": int(n),
        "energy_null": int(energy.isna().sum()),
        "energy_zero": int((energy == 0).sum()),
        "energy_negative": int((energy < 0).sum()),
        "energy_min": None if energy.dropna().empty else float(energy.min()),
        "charging_minutes_null": int(chg.isna().sum()) if chg is not None else None,
        "charging_minutes_zero": int((chg == 0).sum()) if chg is not None else None,
        "charging_over_24h": int((chg > 1440).sum()) if chg is not None else None,
        "connected_minutes_zero": int((con == 0).sum()) if con is not None else None,
        "connected_over_24h": int((con > 1440).sum()) if con is not None else None,
        "charging_exceeds_connected": (
            int((chg > con + 1 / 60).sum()) if chg is not None and con is not None else None
        ),
        "energy_zero_with_charging_minutes_over_0": (
            int(((energy == 0) & (chg > 0)).sum()) if chg is not None else None
        ),
        "energy_over_0_with_charging_minutes_zero": (
            int(((energy > 0) & (chg == 0)).sum()) if chg is not None else None
        ),
    }
    kw_basis = chg if chg is not None else con
    if kw_basis is not None:
        kw = energy / (kw_basis / 60)
        ok = kw_basis > 0
        imp["implied_kw_basis"] = "charging_minutes" if chg is not None else "connected_minutes"
        imp["implied_kw_quantiles"] = {
            str(q): round(float(v), 3) for q, v in kw[ok].quantile([0.5, 0.9, 0.99, 0.999]).items()
        }
        if roles.get("rated_kw_ceiling"):
            imp["implied_kw_over_ceiling"] = {
                "ceiling_kw": roles["rated_kw_ceiling"],
                "rows": int((kw[ok] > roles["rated_kw_ceiling"]).sum()),
            }
        if roles.get("port_type") and kw_basis is not None:
            imp["implied_kw_p50_by_port_type"] = {
                str(k): round(float(v), 3)
                for k, v in kw[ok].groupby(rows.loc[ok, roles["port_type"]]).median().items()
            }
    if end is not None:
        span = (end - start).dt.total_seconds() / 60
        epoch = end.dt.year == 1970
        imp.update(
            {
                "end_null": int(end.isna().sum()),
                "end_is_1970_epoch_sentinel": int(epoch.sum()),
                "end_before_start_excluding_sentinel": int(((span < 0) & ~epoch).sum()),
                "end_equals_start": int((span == 0).sum()),
                "span_over_24h": int((span > 1440).sum()),
                "span_over_7d": int((span > 7 * 1440).sum()),
                "crosses_local_midnight": int((start.dt.normalize() != end.dt.normalize()).sum()),
                "crosses_year_boundary": int(((start.dt.year != end.dt.year) & ~epoch).sum()),
            }
        )
    answers["implausible"] = imp
    answers["time_parsing"] = tnotes

    # timezone evidence
    tz: dict[str, Any] = {"assumed_zone": roles["timezone"], "start_format": roles["start_format"]}
    tz["start_hour_histogram_as_published"] = hist(start.dt.hour)
    if roles["start_format"] == "ISO_UTC":
        local = start.dt.tz_localize("UTC").dt.tz_convert(roles["timezone"])
        tz["start_hour_histogram_if_utc_converted_to_local"] = hist(local.dt.hour)
        tz["note"] = (
            "if the +00:00 offset were really local time mislabelled, the overnight trough would sit at the published hours; if it is true UTC, the trough sits at the converted hours"
        )
    if roles.get("seasonal_shift_check"):
        tz["seasonal_shift"] = seasonal_hour_shift(start, roles["timezone"])
    if roles["tz_label"]:
        lab = rows[roles["tz_label"]]
        tz["tz_label_values"] = hist(lab.fillna("<null>"))
        tz["tz_label_by_start_month"] = {
            str(m): {str(c): int(v) for c, v in r.items()}
            for m, r in pd.crosstab(start.dt.month, lab).iterrows()
        }
    if end is not None and roles.get("dst_transitions"):
        ref = con if con is not None else chg
        tz["dst_transition_gaps"] = dst_transition_gaps(start, end, ref, roles["dst_transitions"])
        tz["dst_note"] = (
            "+60 on spring-forward and -60 on fall-back dates means wall-clock local timestamps; 0 would mean UTC"
        )
    answers["timezone"] = tz

    # coverage
    answers["coverage"] = {
        "start_min": str(start.min()),
        "start_max": str(start.max()),
        "sessions_by_year": hist(start.dt.year),
        "files_by_start_range": {
            f: {
                "rows": int((rows["_file"] == f).sum()),
                "start_min": str(start[rows["_file"] == f].min()),
                "start_max": str(start[rows["_file"] == f].max()),
            }
            for f in roles["files"]
            if (rows["_file"] == f).any()
        },
    }

    # observed concurrency (capacity lower bound), on sessions of at least 5 minutes
    if end is not None:
        # after dropping natural-key duplicates: re-delivered rows would otherwise overlap
        # themselves and double every count
        dedup = ~rows.duplicated(nk)
        real = dedup & ((end - start) >= pd.Timedelta("5min"))
        cap: dict[str, Any] = {
            "sessions_used": int(real.sum()),
            "min_session_minutes": 5,
            "natural_key_deduplicated_first": True,
        }
        for label, key in (
            ("by_station_key", st_id or st_name),
            ("by_site_key", roles.get("site_key")),
        ):
            if key:
                conc = max_concurrency(start[real], end[real], rows.loc[real, key])
                cap[label] = {
                    "key": key,
                    "keys": len(conc),
                    "distribution": hist(pd.Series(conc)),
                    "top": dict(sorted(conc.items(), key=lambda kv: -kv[1])[:8]),
                }
        # amendment (f): a level counts only if reached on >= N distinct days
        skey = st_id or st_name
        dal = days_at_level(start[real], end[real], rows.loc[real, skey])
        plain = dal.apply(lambda r: max([int(k) for k in dal.columns if r[k] >= 1] or [0]), axis=1)
        robust5 = dal.apply(
            lambda r: max([int(k) for k in dal.columns if r[k] >= 5] or [0]), axis=1
        )
        cap["days_at_level"] = {
            "key": skey,
            "note": "per key, distinct local dates on which concurrency reaches the level; robust_max(N) = highest level reached on >= N days",
            "robust_max_histogram_by_n": robust_max_distribution(dal),
            "keys_where_plain_max_exceeds_robust_max_n5": int((plain > robust5).sum()),
            "days_at_level_quantiles": {
                lvl: {str(q): int(v) for q, v in dal[lvl].quantile([0.1, 0.5, 0.9]).items()}
                for lvl in dal.columns
            },
        }
        # amendment (g): inter-session gaps calibrate the active-window threshold
        cap["inter_session_gaps"] = {
            "key": skey,
            **inter_session_gaps(start[dedup], end[dedup], rows.loc[dedup, skey]),
        }
        answers["observed_concurrency"] = cap
    if st_id:
        grp = st_name or roles.get("site_key")
        cps = rows.dropna(subset=[st_id, grp]).groupby(grp)[st_id].nunique()
        answers["charge_points_per_site"] = {
            "sites": int(len(cps)),
            "distribution": hist(cps),
            "top": {str(k): int(v) for k, v in cps.sort_values(ascending=False).head(8).items()},
        }
    if roles.get("location_layer"):
        import json

        lp = raw_dir / roles["location_layer"]
        if lp.exists():
            j = json.loads(lp.read_text())
            loc = pd.DataFrame([f["attributes"] for f in j["features"]])
            base = (
                loc["Charge_Point_ID"]
                .astype(str)
                .str.replace(r"\s*\(.*\)$", "", regex=True)
                .str.strip()
            )
            ids = rows[st_id].dropna().unique()
            answers["location_layer_match"] = {
                "file": roles["location_layer"],
                "features": int(len(loc)),
                "distinct_connector_ids": int(loc["Charge_Point_ID"].nunique()),
                "distinct_base_charge_point_ids": int(base.nunique()),
                "usage_charge_point_ids": int(len(ids)),
                "usage_ids_found_in_layer": int(pd.Series(ids).isin(set(base)).sum()),
                "share_of_sessions_with_id_in_layer": round(
                    float(rows[st_id].isin(set(base)).mean()), 6
                ),
            }

    answers["personal_data"] = {
        "user_level_columns": roles["user_level_columns"],
        "columns_present": src_cols,
    }
    return {"files": files, "available": True, "roles": roles, "answers": answers}


DEFINITIONS = {
    "null_rate": "share of rows whose value is null or an empty/whitespace string",
    "exact_duplicate_rows": "rows identical on every source column to an earlier row (pandas duplicated, first kept)",
    "natural_key_duplicate_rows": "rows whose natural key repeats an earlier row across all of the source's files",
    "charging_over_24h": "rows whose hh:mm:ss charging duration exceeds 1440 minutes",
    "span_over_24h": "rows whose parsed end minus start exceeds 1440 minutes",
    "end_before_start_excluding_sentinel": "rows whose parsed end is earlier than start, excluding ends in 1970 (a missing-value sentinel)",
    "energy_zero": "rows whose energy parses to exactly 0",
    "implied_kw": "energy_kwh / (charging_minutes / 60) on rows with charging_minutes > 0",
    "observed_concurrency": "after natural-key deduplication, the maximum number of sessions (>= 5 minutes) at one key whose [start, end] intervals overlap; a lower bound on ports in service",
    "idle_share_of_connected_minutes": "1 - sum(charging minutes) / sum(connected minutes) over all rows",
    "dst_transition_gaps": "sessions spanning local 01:00-02:00 on a DST transition date, with (end - start) - recorded duration in minutes",
    "one_hour_gap_rows": "rows where (end - start) differs from the recorded duration by 55..65 minutes",
    "delivery_blocks": "segments of one file delimited by the per-delivery row id restarting at 0; each compared with the last block on the natural key",
}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    p.add_argument("--out", type=Path, default=ARTIFACTS_DIR / "profile")
    a = p.parse_args(argv)
    rid = pr.run_id()
    payload: dict[str, Any] = {
        "artifact": "profile",
        "run_id": rid,
        "generated_at_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "code_commit": pr.git_commit(),
        "package_version": __version__,
        "pandas_version": pd.__version__,
        "definitions": DEFINITIONS,
        "sources": {},
    }
    for name, roles in ROLES.items():
        print(f"profiling {name} ...", flush=True)
        payload["sources"][name] = profile_source(name, roles, a.raw_dir)
    path = pr.write_artifact(payload, a.out, rid)
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
