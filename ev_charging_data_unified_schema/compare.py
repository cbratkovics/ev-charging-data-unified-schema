"""Compare a fresh full-build run with the committed latest artifacts (ADR-0015 item 1).

Two cases, decided from the input hashes recorded in the silver summary artifacts:

* ``upstream_changed``: the fresh run's input hashes differ from the committed ones. Upstream
  data changed; output differences are expected and are not a regression. The report lists the
  files whose hash or row count changed.
* ``regression``: input hashes are identical but an output differs beyond tolerance, or the
  fresh reconciliation status is blocking.
* ``ok``: identical inputs, outputs within tolerance, reconciliation not blocking.

Tolerances: row and session counts exact; kWh, utilization and shares within 1e-6 relative.
Pure over the loaded JSON payloads; tested per branch.
"""

from __future__ import annotations

from typing import Any

REL_TOL = 1e-6


def _num_diff(a: Any, b: Any, *, exact: bool) -> bool:
    if a is None or b is None:
        return a != b
    if exact:
        return a != b
    scale = max(abs(float(a)), abs(float(b)), 1.0)
    return abs(float(a) - float(b)) / scale > REL_TOL


def compare_inputs(committed: dict[str, Any], fresh: dict[str, Any]) -> list[dict[str, Any]]:
    """Files whose sha256 or row count differs, plus files added or removed."""
    c, f = committed.get("inputs", {}), fresh.get("inputs", {})
    out = []
    for key in sorted(set(c) | set(f)):
        if key not in c:
            out.append(
                {
                    "file": key,
                    "change": "added",
                    "rows_committed": None,
                    "rows_fresh": f[key]["rows"],
                }
            )
        elif key not in f:
            out.append(
                {
                    "file": key,
                    "change": "removed",
                    "rows_committed": c[key]["rows"],
                    "rows_fresh": None,
                }
            )
        elif c[key]["sha256"] != f[key]["sha256"]:
            out.append(
                {
                    "file": key,
                    "change": "changed",
                    "rows_committed": c[key]["rows"],
                    "rows_fresh": f[key]["rows"],
                    "row_delta": f[key]["rows"] - c[key]["rows"],
                }
            )
    return out


def compare_outputs(
    committed_silver: dict, fresh_silver: dict, committed_sens: dict, fresh_sens: dict
) -> list[dict[str, Any]]:
    diffs = []
    for s in sorted(set(committed_silver["by_source"]) | set(fresh_silver["by_source"])):
        c = committed_silver["by_source"].get(s, {})
        f = fresh_silver["by_source"].get(s, {})
        for k, exact in (
            ("bronze", True),
            ("accepted", True),
            ("non_trivial", True),
            ("quarantined", True),
            ("accepted_kwh", False),
        ):
            if _num_diff(c.get(k), f.get(k), exact=exact):
                diffs.append(
                    {"where": f"silver.by_source.{s}.{k}", "committed": c.get(k), "fresh": f.get(k)}
                )
    c_rows = {
        (r["session_rule"], r["source"], r["definition"], r["flavour"]): r
        for r in committed_sens["results"]
    }
    f_rows = {
        (r["session_rule"], r["source"], r["definition"], r["flavour"]): r
        for r in fresh_sens["results"]
    }
    for key in sorted(set(c_rows) | set(f_rows)):
        c, f = c_rows.get(key), f_rows.get(key)
        if c is None or f is None:
            diffs.append(
                {
                    "where": f"sensitivity.results[{key}]",
                    "committed": c and c["utilization"],
                    "fresh": f and f["utilization"],
                }
            )
        elif (
            _num_diff(c["utilization"], f["utilization"], exact=False)
            or c["station_days_over_100pct"] != f["station_days_over_100pct"]
        ):
            diffs.append(
                {
                    "where": f"sensitivity.results[{key}]",
                    "committed": (c["utilization"], c["station_days_over_100pct"]),
                    "fresh": (f["utilization"], f["station_days_over_100pct"]),
                }
            )
    return diffs


def classify_run(
    committed_silver: dict, fresh_silver: dict, committed_sens: dict, fresh_sens: dict
) -> dict[str, Any]:
    inputs = compare_inputs(committed_silver, fresh_silver)
    outputs = compare_outputs(committed_silver, fresh_silver, committed_sens, fresh_sens)
    blocking = fresh_silver.get("status") == "blocking"
    if blocking:
        status = "regression"
    elif inputs:
        status = "upstream_changed"
    elif outputs:
        status = "regression"
    else:
        status = "ok"
    return {
        "status": status,
        "reconciliation_status": fresh_silver.get("status"),
        "input_changes": inputs,
        "output_differences": outputs,
        "committed_run_id": committed_silver.get("run_id"),
        "fresh_run_id": fresh_silver.get("run_id"),
        "tolerance": {"counts": "exact", "measures_relative": REL_TOL},
    }


def issue_body(report: dict[str, Any]) -> tuple[str, str]:
    """(title, markdown body) for the issue the scheduled run opens."""
    if report["status"] == "upstream_changed":
        title = "New source data available"
        lines = [
            "The scheduled full build found changed input files. Output differences are expected and were not judged as a regression.",
            "",
            "| File | Change | Rows committed | Rows fresh |",
            "|---|---|---|---|",
        ]
        for c in report["input_changes"]:
            lines.append(
                f"| `{c['file']}` | {c['change']} | {c['rows_committed']} | {c['rows_fresh']} |"
            )
        lines += [
            "",
            f"Fresh reconciliation status: **{report['reconciliation_status']}**. Review the uploaded artifacts and run `make release` locally to publish a new version.",
        ]
    else:
        title = "Full build regression"
        lines = [
            f"Inputs are identical to the committed run `{report['committed_run_id']}` but the fresh run `{report['fresh_run_id']}` differs, or reconciliation is blocking (status: **{report['reconciliation_status']}**).",
            "",
            "| Where | Committed | Fresh |",
            "|---|---|---|",
        ]
        for d in report["output_differences"][:100]:
            lines.append(f"| `{d['where']}` | {d['committed']} | {d['fresh']} |")
        lines += [
            "",
            "Tolerance: counts exact; measures within 1e-6 relative. Artifacts are attached to the workflow run.",
        ]
    return title, "\n".join(lines)
