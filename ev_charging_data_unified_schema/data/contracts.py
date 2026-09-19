"""Data contracts = the dbt silver tests, run by the scheduled job through this thin wrapper.

The checks live in ``dbt/models/silver/_silver.yml`` and ``dbt/tests/silver/`` (grain
uniqueness, required columns, ranges, accepted cohorts, not-null, freshness through the expected
period, newest-period row count versus the prior period, row-count monotonicity, target-rules
reconciliation). This module runs ``dbt build --select +tag:silver`` with the run's parameters
as dbt vars and maps ``target/run_results.json`` into ``{"ok", "checks", "summary"}`` so a
failing silver test becomes a HOLD. ``summarise_run_results`` is pure and unit-tested.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from ev_charging_data_unified_schema.config import REPO_ROOT, env

DBT_PROJECT_DIR = REPO_ROOT / "dbt"
DBT_SELECT = "+tag:silver"
DEFAULT_TARGET = "dev"
FAILING_STATUSES = frozenset({"fail", "error"})
CHECK_NAME_HINTS: tuple[tuple[str, str], ...] = (
    ("assert_rows_fresh_through_expected_period", "freshness"),
    ("row_count_within_pct_of_prior_period", "newest_period_row_count"),
    ("assert_rows_count_not_below_prior_run", "row_count_monotonic"),
    ("assert_target_rules_reconcile_to_source", "target_reconciliation"),
    ("unique_combination_of_columns_slv_period_rows", "grain_unique"),
    ("expect_table_columns_to_contain_set", "required_columns"),
    ("accepted_values_slv_period_rows", "cohorts_in_scope"),
)


def dbt_target() -> str:
    return env("DBT_TARGET", DEFAULT_TARGET)


def dbt_full_refresh() -> bool:
    return env("DBT_FULL_REFRESH").strip().lower() in {"1", "true", "yes"}


def _short_name(unique_id: str) -> str:
    parts = unique_id.split(".")
    if parts[0] == "test" and len(parts) >= 4:
        return parts[2]
    return parts[-1]


def check_name(unique_id: str) -> str:
    short = _short_name(unique_id)
    for needle, name in CHECK_NAME_HINTS:
        if needle in short:
            return name
    return short


def summarise_run_results(run_results: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for r in run_results.get("results", []):
        uid = r.get("unique_id", "")
        status = str(r.get("status", "")).lower()
        kind = uid.split(".")[0]
        counts[status] = counts.get(status, 0) + 1
        if kind in ("test", "unit_test"):
            checks.append(
                {
                    "name": check_name(uid),
                    "ok": status not in FAILING_STATUSES,
                    "detail": {
                        "status": status,
                        "failures": r.get("failures"),
                        "message": r.get("message"),
                        "node": uid,
                    },
                }
            )
        elif kind == "model" and status in FAILING_STATUSES:
            checks.append(
                {
                    "name": f"model:{uid.split('.')[-1]}",
                    "ok": False,
                    "detail": {"status": status, "message": r.get("message"), "node": uid},
                }
            )
    return {
        "ok": all(c["ok"] for c in checks),
        "checks": checks,
        "summary": {
            "dbt": {
                "elapsed_s": run_results.get("elapsed_time"),
                "invocation_id": (run_results.get("metadata") or {}).get("invocation_id"),
                "status_counts": counts,
                "n_checks": len(checks),
            }
        },
    }


def dbt_vars(
    *,
    rows_path: str | Path | None = None,
    target_season: int | None = None,
    target_period: int | None = None,
    expected_through: tuple[int, int] | None = None,
    prior_row_count: int | None = None,
) -> dict[str, Any]:
    v: dict[str, Any] = {}
    if rows_path is not None:
        p = Path(rows_path)
        v["rows_path"] = (
            p.relative_to(REPO_ROOT).as_posix()
            if p.is_absolute() and p.is_relative_to(REPO_ROOT)
            else p.as_posix()
        )
    if target_season is not None and target_period is not None:
        v["target_season"], v["target_period"] = int(target_season), int(target_period)
    if expected_through is not None:
        v["expected_season"], v["expected_period"] = int(expected_through[0]), int(
            expected_through[1]
        )
    if prior_row_count is not None:
        v["prior_row_count"] = int(prior_row_count)
    return v


def dbt_command(
    vars_: dict[str, Any],
    *,
    target: str,
    project_dir: Path = DBT_PROJECT_DIR,
    full_refresh: bool = False,
) -> list[str]:
    cmd = [
        sys.executable,
        "-m",
        "dbt.cli.main",
        "build",
        "--select",
        DBT_SELECT,
        "--indirect-selection",
        "cautious",
        "--project-dir",
        str(project_dir),
        "--profiles-dir",
        str(project_dir),
        "--target",
        target,
        "--vars",
        json.dumps(vars_),
    ]
    if full_refresh:
        cmd.append("--full-refresh")
    return cmd


def run_silver_contracts(
    *,
    rows_path: str | Path | None = None,
    target_season: int | None = None,
    target_period: int | None = None,
    expected_through: tuple[int, int] | None = None,
    prior_row_count: int | None = None,
    target: str | None = None,
    project_dir: Path = DBT_PROJECT_DIR,
) -> dict[str, Any]:
    target = target or dbt_target()
    vars_ = dbt_vars(
        rows_path=rows_path,
        target_season=target_season,
        target_period=target_period,
        expected_through=expected_through,
        prior_row_count=prior_row_count,
    )
    cmd = dbt_command(
        vars_, target=target, project_dir=project_dir, full_refresh=dbt_full_refresh()
    )
    results_path = project_dir / "target" / "run_results.json"
    results_path.unlink(missing_ok=True)
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if not results_path.exists():
        return {
            "ok": False,
            "checks": [
                {
                    "name": "dbt",
                    "ok": False,
                    "detail": {
                        "returncode": proc.returncode,
                        "stderr": proc.stderr[-2000:],
                        "stdout": proc.stdout[-2000:],
                    },
                }
            ],
            "summary": {"dbt": {"target": target, "vars": vars_}},
        }
    report = summarise_run_results(json.loads(results_path.read_text(encoding="utf-8")))
    report["summary"]["dbt"].update(
        {"target": target, "vars": vars_, "returncode": proc.returncode}
    )
    if proc.returncode not in (0, 1) and report["ok"]:
        report["ok"] = False
        report["checks"].append(
            {
                "name": "dbt",
                "ok": False,
                "detail": {"returncode": proc.returncode, "stderr": proc.stderr[-2000:]},
            }
        )
    return report
