"""Reconciliation identities and residual classification (ADR-0013 item 1).

Pure over a DuckDB connection to the built warehouse. Two identities per source, overall and
per month of the session's local start:

* (i)  raw = fact + quarantined by primary reason, for rows and for kWh on parsed values;
* (ii) fact = counted in station-day measures + trivial + unknown-station, for sessions and
       kWh (kWh per month carries the documented ``midnight_spill_kwh`` term, zero overall).

Only the residual is compared with the tolerance: rows and sessions exactly, kWh within
``KWH_REL_TOL`` relative. ``classify`` is pure and tested per branch.
"""

from __future__ import annotations

from typing import Any

import duckdb

KWH_REL_TOL = 1e-6
ROW_TOL = 0


def classify(residual: float, reference: float, *, kind: str) -> dict[str, Any]:
    """Classify a residual. ``kind`` is 'rows', 'sessions' or 'kwh'. Returns status ok,
    non_blocking or blocking with a one-line interpretation."""
    if kind in ("rows", "sessions"):
        if residual == 0:
            return {
                "status": "ok",
                "residual": 0,
                "tolerance": ROW_TOL,
                "interpretation": "identity holds exactly",
            }
        return {
            "status": "blocking",
            "residual": residual,
            "tolerance": ROW_TOL,
            "interpretation": f"{abs(residual):g} {kind} unaccounted for: a row is in neither the fact nor the quarantine, or in both",
        }
    scale = max(abs(reference), 1.0)
    rel = abs(residual) / scale
    if residual == 0:
        return {
            "status": "ok",
            "residual": 0.0,
            "relative": 0.0,
            "tolerance": KWH_REL_TOL,
            "interpretation": "identity holds exactly",
        }
    if rel <= KWH_REL_TOL:
        return {
            "status": "non_blocking",
            "residual": residual,
            "relative": rel,
            "tolerance": KWH_REL_TOL,
            "interpretation": "floating-point residual within tolerance (summation order); no row is missing",
        }
    return {
        "status": "blocking",
        "residual": residual,
        "relative": rel,
        "tolerance": KWH_REL_TOL,
        "interpretation": f"kWh residual of {residual:.3f} ({rel:.2e} relative) exceeds tolerance: energy was created or lost between raw and gold",
    }


def _rows(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict[str, Any]]:
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def reconciliation(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    # identity (i): every silver row (= every bronze row) by source and start month
    raw = _rows(
        con,
        """
        with all_rows as (
            select source, coalesce(strftime(start_local, '%Y-%m'), 'unparsed') as month, energy_kwh, primary_reason
            from (
                select source, start_local, energy_kwh, primary_reason from silver.slv_sessions__boulder
                union all select source, start_local, energy_kwh, primary_reason from silver.slv_sessions__cary
                union all select source, start_local, energy_kwh, primary_reason from silver.slv_sessions__dft_2017
            )
        )
        select source, month,
               count(*) as raw_rows, sum(energy_kwh) as raw_kwh,
               count(*) filter (where primary_reason is null) as silver_accepted_rows
        from all_rows group by 1, 2 order by 1, 2
        """,
    )
    fact = _rows(
        con,
        """
        select source, strftime(start_local, '%Y-%m') as month, count(*) as fact_rows, sum(energy_kwh) as fact_kwh,
               count(*) filter (where is_non_trivial and not contains(station_key, '/unknown/')) as counted_sessions,
               sum(energy_kwh) filter (where is_non_trivial and not contains(station_key, '/unknown/')) as counted_kwh_by_start_month,
               count(*) filter (where not is_non_trivial) as trivial_sessions,
               sum(energy_kwh) filter (where not is_non_trivial) as trivial_kwh,
               count(*) filter (where is_non_trivial and contains(station_key, '/unknown/')) as unknown_sessions,
               sum(energy_kwh) filter (where is_non_trivial and contains(station_key, '/unknown/')) as unknown_kwh
        from gold.fct_charging_session group by 1, 2 order by 1, 2
        """,
    )
    quarantined = _rows(
        con,
        """
        select source, coalesce(strftime(start_local, '%Y-%m'), 'unparsed') as month, primary_reason,
               count(*) as rows_, sum(energy_kwh) as kwh
        from silver.slv_sessions_quarantined group by 1, 2, 3 order by 1, 2, 3
        """,
    )
    station_day = _rows(
        con,
        """
        select source, strftime(local_date, '%Y-%m') as month, sum(sessions) as sessions, sum(energy_kwh) as kwh
        from gold.fct_station_day group by 1, 2 order by 1, 2
        """,
    )
    dup_breakdown = _rows(
        con,
        """
        with q as (
            select q.source, q.source_family, q.natural_key_hash
            from silver.slv_sessions_quarantined as q where q.primary_reason = 'natural_key_duplicate'
        ),
        survivor as (
            select source, natural_key_hash, source_family from gold.fct_charging_session
        )
        select q.source,
               case
                   when q.source = 'dft_2017' and s.source_family in ('rapids', 'fasts') and q.source_family not in ('rapids', 'fasts')
                       then 'same_event_in_raw_file'
                   when s.source_family = q.source_family then 'within_family'
                   else 'other'
               end as bucket,
               count(*) as rows_
        from q left join survivor as s on q.source = s.source and q.natural_key_hash = s.natural_key_hash
        group by 1, 2 order by 1, 2
        """,
    )

    def f(v: Any) -> float:
        return float(v) if v is not None else 0.0

    sources = sorted({r["source"] for r in raw})
    out: dict[str, Any] = {
        "definitions": {
            "identity_i": "raw rows (every bronze row, parsed in silver) = fact rows + quarantined rows by primary reason; kWh on parsed values the same way",
            "identity_ii": "fact sessions = counted in fct_station_day (non-trivial, known station) + trivial + unknown-station; kWh the same, with midnight_spill_kwh per month = fact kWh by start month minus station-day kWh by piece month (zero at source level)",
            "natural_key_duplicate_breakdown": "same_event_in_raw_file: DfT anomalies rows whose surviving twin is in a raw file (the events the publisher moved); within_family: twin in the same file family; other",
            "tolerance": {"rows": ROW_TOL, "sessions": ROW_TOL, "kwh_relative": KWH_REL_TOL},
            "month": "YYYY-MM of the session's local start; 'unparsed' where the start could not be parsed",
        },
        "by_source": {},
        "status": "ok",
    }
    worst = "ok"
    rank = {"ok": 0, "non_blocking": 1, "blocking": 2}
    for s in sources:
        months = sorted({r["month"] for r in raw if r["source"] == s})
        per_month = {}
        for m in months + ["__total__"]:

            def sel(rows_: list[dict[str, Any]], _m: str = m, _s: str = s) -> list[dict[str, Any]]:
                return [
                    r
                    for r in rows_
                    if r["source"] == _s and (_m == "__total__" or r["month"] == _m)
                ]

            raw_rows = sum(r["raw_rows"] for r in sel(raw))
            raw_kwh = sum(f(r["raw_kwh"]) for r in sel(raw))
            fact_rows = sum(r["fact_rows"] for r in sel(fact))
            fact_kwh = sum(f(r["fact_kwh"]) for r in sel(fact))
            q_by_reason = {}
            for r in sel(quarantined):
                q_by_reason.setdefault(r["primary_reason"], {"rows": 0, "kwh": 0.0})
                q_by_reason[r["primary_reason"]]["rows"] += r["rows_"]
                q_by_reason[r["primary_reason"]]["kwh"] += f(r["kwh"])
            q_rows = sum(v["rows"] for v in q_by_reason.values())
            q_kwh = sum(v["kwh"] for v in q_by_reason.values())
            counted_kwh_start = sum(f(r["counted_kwh_by_start_month"]) for r in sel(fact))
            trivial_sessions = sum(r["trivial_sessions"] for r in sel(fact))
            trivial_kwh = sum(f(r["trivial_kwh"]) for r in sel(fact))
            unknown_sessions = sum(r["unknown_sessions"] for r in sel(fact))
            unknown_kwh = sum(f(r["unknown_kwh"]) for r in sel(fact))
            sd_sessions = sum(f(r["sessions"]) for r in sel(station_day))
            sd_kwh = sum(f(r["kwh"]) for r in sel(station_day))
            spill = counted_kwh_start - sd_kwh
            entry = {
                "identity_i": {
                    "raw_rows": raw_rows,
                    "fact_rows": fact_rows,
                    "quarantined_rows": q_rows,
                    "quarantined_by_primary_reason": {
                        k: v["rows"] for k, v in sorted(q_by_reason.items())
                    },
                    "raw_kwh": round(raw_kwh, 6),
                    "fact_kwh": round(fact_kwh, 6),
                    "quarantined_kwh": round(q_kwh, 6),
                    "quarantined_kwh_by_primary_reason": {
                        k: round(v["kwh"], 6) for k, v in sorted(q_by_reason.items())
                    },
                    "rows": classify(raw_rows - fact_rows - q_rows, raw_rows, kind="rows"),
                    "kwh": classify(raw_kwh - fact_kwh - q_kwh, raw_kwh, kind="kwh"),
                },
                "identity_ii": {
                    "fact_sessions": fact_rows,
                    "counted_sessions": int(sd_sessions),
                    "trivial_sessions": trivial_sessions,
                    "unknown_station_sessions": unknown_sessions,
                    "fact_kwh": round(fact_kwh, 6),
                    "counted_kwh": round(sd_kwh, 6),
                    "trivial_kwh": round(trivial_kwh, 6),
                    "unknown_station_kwh": round(unknown_kwh, 6),
                    "midnight_spill_kwh": round(spill, 6),
                    "sessions": classify(
                        fact_rows - int(sd_sessions) - trivial_sessions - unknown_sessions,
                        fact_rows,
                        kind="sessions",
                    ),
                    "kwh": classify(
                        fact_kwh - sd_kwh - trivial_kwh - unknown_kwh - spill, fact_kwh, kind="kwh"
                    ),
                },
            }
            if m == "unparsed":
                # unparsed rows are quarantined by construction; identity (ii) has nothing to say
                entry["identity_ii"] = {
                    "note": "no parsed start; every row is quarantined (unparseable_timestamp)"
                }
            for ident in ("identity_i", "identity_ii"):
                for k in ("rows", "sessions", "kwh"):
                    c = entry[ident].get(k)
                    if isinstance(c, dict) and "status" in c and rank[c["status"]] > rank[worst]:
                        worst = c["status"]
            per_month[m] = entry
        total = per_month.pop("__total__")
        total["natural_key_duplicate_breakdown"] = {
            r["bucket"]: r["rows_"] for r in dup_breakdown if r["source"] == s
        }
        out["by_source"][s] = {"total": total, "by_month": per_month}
    out["status"] = worst
    return out
