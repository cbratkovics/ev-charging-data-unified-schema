#!/usr/bin/env python
"""Write artifacts/sensitivity/<run_id>.json from the built warehouse (ADR-0006 h).

python scripts/sensitivity.py [--db .duckdb/dev.duckdb] [--out artifacts/sensitivity]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ev_charging_data_unified_schema.config import ARTIFACTS_DIR  # noqa: E402
from ev_charging_data_unified_schema.profiling import git_commit  # noqa: E402
from ev_charging_data_unified_schema.sensitivity import run_id, sensitivity  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--db", type=Path, default=Path(".duckdb/dev.duckdb"))
    p.add_argument("--out", type=Path, default=ARTIFACTS_DIR / "sensitivity")
    a = p.parse_args(argv)
    rid = run_id()
    con = duckdb.connect(str(a.db), read_only=True)
    try:
        payload = sensitivity(con, rid=rid, code_commit=git_commit())
    finally:
        con.close()
    a.out.mkdir(parents=True, exist_ok=True)
    path = a.out / f"{rid}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    (a.out / "latest.json").write_text(json.dumps({"run_id": rid, "path": path.name}) + "\n")
    print(f"wrote {path}")
    for r in payload["results"]:
        if r["session_rule"] == "non_trivial_only" and r["utilization"] is not None:
            print(
                f"  {r['source']:9s} {r['definition']:16s} {r['flavour']:9s} {r['utilization']:.4f}  over100: {r['station_days_over_100pct']}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
