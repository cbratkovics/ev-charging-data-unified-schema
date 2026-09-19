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
DST_LONDON = [
    "2021-10-31",
    "2022-03-27",
    "2022-10-30",
    "2023-03-26",
    "2023-10-29",
    "2024-03-31",
    "2024-10-27",
    "2025-03-30",
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
    "dundee": {
        "files": [
            "dundee_2021_jul_dec.csv",
            "dundee_2022.csv",
            "dundee_2023.csv",
            "dundee_2024.csv",
            "dundee_2024_duplicate_upload.csv",
            "dundee_2025_jan_aug.csv",
        ],
        "read": {},
        "timezone": "Europe/London",
        "session_id": "SDR ID",
        "station_id": "CP ID",
        "station_name": "Site",
        "port_id": None,
        "port_type": "Connector Type",
        "start": "Start",
        "end": "End",
        "start_format": "DMY",
        "charging_duration": "Duration",
        "connected_duration": None,
        "energy_kwh": "Consum(kWh)",
        "tz_label": None,
        "user_level_columns": [],
        "natural_key": ["SDR ID"],
        "aliases": {"Column1": "Postcode"},
        "dst_transitions": DST_LONDON,
        "redelivery_pair": ["dundee_2024.csv", "dundee_2024_duplicate_upload.csv"],
        "location_layer": "dundee_chargepoints/all_public_chargers_one_layer.json",
    },
}

# Palo Alto: no file could be downloaded (portal 502 at profiling time). The column list below
# was recorded by the discovery step from a third-party re-upload's metadata and is NOT verified
# against the city's file. It is kept only so the personal-data check can name the fields that
# will need a policy once the file is available.
PALO_ALTO_UNVERIFIED = {
    "user_level_columns": ["User ID", "Driver Postal Code"],
    "device_level_columns": ["MAC Address", "System S/N", "EVSE ID", "Model Number"],
    "note": "column names from a third-party re-upload's metadata; not verified against the city file",
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
    elif fmt == "DMY":
        start = pd.to_datetime(
            frame[roles["start"]].astype("string").str.strip(),
            format="%d/%m/%Y %H:%M",
            errors="coerce",
        )
        end = pd.to_datetime(
            frame[roles["end"]].astype("string").str.strip(),
            format="%d/%m/%Y %H:%M",
            errors="coerce",
        )
    else:  # pragma: no cover
        raise ValueError(fmt)
    notes["start_parse_failures"] = int(start.isna().sum())
    if end is not None:
        notes["end_parse_failures"] = int(end.isna().sum())
    return start, end, notes


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
    chg = hms_to_minutes(rows[roles["charging_duration"]]) if roles["charging_duration"] else None
    con = hms_to_minutes(rows[roles["connected_duration"]]) if roles["connected_duration"] else None
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
    if roles.get("redelivery_pair"):
        a, b = roles["redelivery_pair"]
        answers["overlap"]["redelivery_diff"] = redelivery_diff(
            frames, a, b, sid, [c for c in src_cols if c != sid]
        )

    # 3. station ids vs names
    st_id, st_name = roles["station_id"], roles["station_name"]
    st: dict[str, Any] = {"station_id_column": st_id, "station_name_column": st_name}
    st["distinct_names"] = int(rows[st_name].nunique())
    st["null_names"] = int(rows[st_name].isna().sum())
    if roles.get("site_key"):
        st["site_key_column"] = roles["site_key"]
        st["distinct_site_keys"] = int(rows[roles["site_key"]].nunique())
        st["names_per_site_key"] = hist(rows.groupby(roles["site_key"])[st_name].nunique())
    if st_id:
        st["distinct_ids"] = int(rows[st_id].nunique())
        st["null_ids"] = int(rows[st_id].isna().sum())
        both = rows.dropna(subset=[st_id, st_name])
        st["names_with_multiple_ids"] = int((both.groupby(st_name)[st_id].nunique() > 1).sum())
        st["ids_with_multiple_names"] = int((both.groupby(st_id)[st_name].nunique() > 1).sum())
        ids = rows[st_id].astype("string")
        st["id_forms"] = {
            "numeric": int(ids.str.fullmatch(r"\d+").fillna(False).sum()),
            "apt_prefixed": int(ids.str.startswith("APT").fillna(False).sum()),
            "other": int((~ids.str.fullmatch(r"\d+|APT.*").fillna(True)).sum()),
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
    answers["port"] = {
        "port_id_column": roles["port_id"],
        "port_type_column": roles.get("port_type"),
        "port_type_values": (
            hist(rows[roles["port_type"]].fillna("<null>")) if roles.get("port_type") else None
        ),
    }

    # 5. durations available
    answers["durations"] = {
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
    if chg is not None:
        kw = energy / (chg / 60)
        ok = chg > 0
        imp["implied_kw_quantiles"] = {
            str(q): round(float(v), 3) for q, v in kw[ok].quantile([0.5, 0.9, 0.99, 0.999]).items()
        }
        if roles.get("rated_kw_ceiling"):
            imp["implied_kw_over_ceiling"] = {
                "ceiling_kw": roles["rated_kw_ceiling"],
                "rows": int((kw[ok] > roles["rated_kw_ceiling"]).sum()),
            }
        if roles.get("port_type"):
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
        answers["observed_concurrency"] = cap
    if st_id:
        cps = rows.dropna(subset=[st_id, st_name]).groupby(st_name)[st_id].nunique()
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
        "palo_alto_unverified": PALO_ALTO_UNVERIFIED,
    }
    for name, roles in ROLES.items():
        print(f"profiling {name} ...", flush=True)
        payload["sources"][name] = profile_source(name, roles, a.raw_dir)
    payload["sources"]["palo_alto"] = {
        "available": False,
        "files": [],
        "reason": "the city portal's file endpoint returned HTTP 502 on every attempt during profiling; the ORNL mirror holds zero records",
    }
    path = pr.write_artifact(payload, a.out, rid)
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
