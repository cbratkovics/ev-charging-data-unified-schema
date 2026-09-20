"""Committed summary artifacts read from the built warehouse.

``silver_summary(con, manifest)`` is pure over a DuckDB connection and the landing manifest and
returns the payload for ``artifacts/silver/<run_id>.json``: accepted, non-trivial and quarantined
rows by primary reason and by flag, per source and per file, plus the publisher-rule
decomposition for the DfT files, with run id, code commit and every input file's sha256. Phase 6
extends this artifact with the reconciliation sections rather than replacing it.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import duckdb

from ev_charging_data_unified_schema.interfaces import ManifestEntry

SILVER = "silver"


def _rows(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict[str, Any]]:
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def run_id(now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now(dt.UTC)
    return "silver-" + now.strftime("%Y%m%dT%H%M%SZ")


def silver_summary(
    con: duckdb.DuckDBPyConnection,
    manifest: dict[str, ManifestEntry],
    *,
    rid: str,
    code_commit: str,
) -> dict[str, Any]:
    by_file = _rows(
        con,
        f"""
        with acc as (
            select source, source_file, count(*) as accepted, count(*) filter (where is_non_trivial) as non_trivial,
                   sum(energy_kwh) as accepted_kwh
            from {SILVER}.slv_sessions_unioned group by 1, 2
        ),
        q as (
            select source, source_file, count(*) as quarantined from {SILVER}.slv_sessions_quarantined group by 1, 2
        ),
        b as (
            select source, source_file, count(*) as bronze from (
                select source, source_file from {SILVER}.slv_sessions_unioned
                union all select source, source_file from {SILVER}.slv_sessions_quarantined
            ) group by 1, 2
        )
        select b.source, b.source_file, b.bronze, coalesce(acc.accepted, 0) as accepted,
               coalesce(acc.non_trivial, 0) as non_trivial, coalesce(acc.accepted_kwh, 0) as accepted_kwh,
               coalesce(q.quarantined, 0) as quarantined
        from b left join acc using (source, source_file) left join q using (source, source_file)
        order by 1, 2
        """,
    )
    reasons = _rows(
        con,
        f"select source, source_file, primary_reason, count(*) as n from {SILVER}.slv_sessions_quarantined group by 1, 2, 3 order by 1, 2, 4 desc",
    )
    all_reasons = _rows(
        con,
        f"select source, reason, count(*) as n from (select source, unnest(quarantine_reasons) as reason from {SILVER}.slv_sessions_quarantined) group by 1, 2 order by 1, 2",
    )
    flags = _rows(
        con,
        f"select source, source_file, flag, count(*) as n from (select source, source_file, unnest(quality_flags) as flag from {SILVER}.slv_sessions_unioned) group by 1, 2, 3 order by 1, 2, 3",
    )
    dst = _rows(
        con,
        f"select source, count(*) filter (where is_dst_ambiguous) as ambiguous_starts from {SILVER}.slv_sessions_unioned group by 1 order by 1",
    )
    unknown = _rows(
        con,
        f"""
        select source,
               count(*) filter (where contains(station_key, '/unknown/')) as unknown_station_sessions,
               coalesce(sum(energy_kwh) filter (where contains(station_key, '/unknown/')), 0) as unknown_station_kwh,
               count(*) as sessions, coalesce(sum(energy_kwh), 0) as kwh
        from {SILVER}.slv_sessions_unioned group by 1 order by 1
        """,
    )
    # publisher rule versus the publisher's own split (DfT): per family, rows meeting the rule;
    # and the decomposition of anomalies rows that do NOT meet it (owner item c)
    publisher = _rows(
        con,
        f"""
        select source_family, count(*) as accepted, count(*) filter (where publisher_excluded_rule) as meets_rule
        from {SILVER}.slv_sessions_unioned where source = 'dft_2017' group by 1 order by 1
        """,
    )
    decomposition = _rows(
        con,
        f"""
        with anomalies_not_meeting as (
            select a.natural_key_hash, a.source_family
            from {SILVER}.slv_sessions__dft_2017 as a
            where a.source_family in ('rapids_anomalies', 'fasts_anomalies') and not a.publisher_excluded_rule
        ),
        classified as (
            select
                n.source_family,
                case
                    when q.primary_reason is not null and q.primary_reason <> 'natural_key_duplicate' then 'quarantined_' || q.primary_reason
                    when raw.natural_key_hash is not null and raw.source_family = 'fasts' and n.source_family = 'rapids_anomalies' then 'same_event_in_fasts_raw'
                    when raw.natural_key_hash is not null then 'same_event_in_' || raw.source_family
                    when u.natural_key_hash is not null then 'accepted_unexplained'
                    else 'other'
                end as bucket
            from anomalies_not_meeting as n
            left join (
                select natural_key_hash, source_family from {SILVER}.slv_sessions__dft_2017
                where source_family in ('rapids', 'fasts')
                qualify row_number() over (partition by natural_key_hash order by source_family) = 1
            ) as raw on n.natural_key_hash = raw.natural_key_hash
            left join {SILVER}.slv_sessions_quarantined as q
                on q.source = 'dft_2017' and q.natural_key_hash = n.natural_key_hash and q.source_family = n.source_family
            left join {SILVER}.slv_sessions_unioned as u
                on u.source = 'dft_2017' and u.natural_key_hash = n.natural_key_hash and u.source_family = n.source_family
        )
        select source_family, bucket, count(*) as n from classified group by 1, 2 order by 1, 3 desc
        """,
    )
    return {
        "artifact": "silver_summary",
        "run_id": rid,
        "generated_at_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "code_commit": code_commit,
        "inputs": {
            k: {"sha256": v.sha256, "rows": v.row_count, "retrieved_at": v.retrieved_at}
            for k, v in sorted(manifest.items())
        },
        "definitions": {
            "accepted": "rows of slv_sessions_unioned (primary_reason null)",
            "non_trivial": "accepted rows with energy_kwh > 0 and the available duration (connected, else charging) > 3 minutes (ADR-0007 item 3)",
            "quarantined": "rows of slv_sessions_quarantined; by_primary_reason sums to it (ADR-0009 item 4)",
            "all_reasons": "every failing reason on quarantined rows; a row counts once per reason",
            "flags": "quality flags on accepted rows; a row counts once per flag",
            "publisher_rule.meets_rule": "DfT accepted rows with energy 0 or plug-in of 3 minutes or less, the publisher's stated exclusion rule (ADR-0007 item 2)",
            "publisher_rule.anomalies_not_meeting_rule": "rows of the publisher's anomalies files that do not meet the rule, decomposed: quarantined here for a reason other than duplication (quarantined_<reason>); the same natural key present in a raw file (same_event_in_<family>: for rapids_anomalies these are the fast-charger events the revision moved to the fasts publication); accepted with no explanation (accepted_unexplained); other = a duplicate whose surviving twin is in the other anomalies family",
            "unknown_station": "DfT sessions whose CPID is null, keyed unknown/<Name> (ADR-0007 item 1)",
        },
        "by_source": {
            s: {
                "bronze": sum(r["bronze"] for r in by_file if r["source"] == s),
                "accepted": sum(r["accepted"] for r in by_file if r["source"] == s),
                "non_trivial": sum(r["non_trivial"] for r in by_file if r["source"] == s),
                "accepted_kwh": round(
                    sum(r["accepted_kwh"] for r in by_file if r["source"] == s), 3
                ),
                "quarantined": sum(r["quarantined"] for r in by_file if r["source"] == s),
                "by_primary_reason": {
                    reason: sum(
                        r["n"]
                        for r in reasons
                        if r["source"] == s and r["primary_reason"] == reason
                    )
                    for reason in sorted({r["primary_reason"] for r in reasons if r["source"] == s})
                },
                "all_reasons": {r["reason"]: r["n"] for r in all_reasons if r["source"] == s},
                "flags": {
                    flag: sum(r["n"] for r in flags if r["source"] == s and r["flag"] == flag)
                    for flag in sorted({r["flag"] for r in flags if r["source"] == s})
                },
                "dst_ambiguous_starts": next(
                    (r["ambiguous_starts"] for r in dst if r["source"] == s), 0
                ),
            }
            for s in sorted({r["source"] for r in by_file})
        },
        "by_file": [
            {
                **r,
                "accepted_kwh": round(r["accepted_kwh"], 3),
                "by_primary_reason": {
                    x["primary_reason"]: x["n"]
                    for x in reasons
                    if x["source"] == r["source"] and x["source_file"] == r["source_file"]
                },
                "flags": {
                    x["flag"]: x["n"]
                    for x in flags
                    if x["source"] == r["source"] and x["source_file"] == r["source_file"]
                },
            }
            for r in by_file
        ],
        "unknown_station": {
            r["source"]: {
                k: (round(v, 3) if isinstance(v, float) else v)
                for k, v in r.items()
                if k != "source"
            }
            for r in unknown
        },
        "publisher_rule": {
            "by_family": {
                r["source_family"]: {"accepted": r["accepted"], "meets_rule": r["meets_rule"]}
                for r in publisher
            },
            "anomalies_not_meeting_rule": {
                fam: {r["bucket"]: r["n"] for r in decomposition if r["source_family"] == fam}
                for fam in sorted({r["source_family"] for r in decomposition})
            },
        },
    }
