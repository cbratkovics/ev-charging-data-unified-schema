#!/usr/bin/env python
"""Write artifacts/silver/<run_id>.json from the built warehouse (docs/BRIEF.md § 5; owner
item b before Phase 4). Reads the dev DuckDB file and the landing manifest.

    python scripts/silver_summary.py [--db .duckdb/dev.duckdb] [--landed-dir data/landed] [--out artifacts/silver]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ev_charging_data_unified_schema.config import ARTIFACTS_DIR, LANDED_DIR  # noqa: E402
from ev_charging_data_unified_schema.data.loader import read_manifest  # noqa: E402
from ev_charging_data_unified_schema.profiling import git_commit  # noqa: E402
from ev_charging_data_unified_schema.summaries import run_id, silver_summary  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--db", type=Path, default=Path(".duckdb/dev.duckdb"))
    p.add_argument("--landed-dir", type=Path, default=LANDED_DIR)
    p.add_argument("--out", type=Path, default=ARTIFACTS_DIR / "silver")
    a = p.parse_args(argv)
    rid = run_id()
    con = duckdb.connect(str(a.db), read_only=True)
    try:
        payload = silver_summary(
            con, read_manifest(a.landed_dir), rid=rid, code_commit=git_commit()
        )
    finally:
        con.close()
    a.out.mkdir(parents=True, exist_ok=True)
    path = a.out / f"{rid}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    (a.out / "latest.json").write_text(json.dumps({"run_id": rid, "path": path.name}) + "\n")
    print(f"wrote {path}")
    for s, v in payload["by_source"].items():
        print(
            f"  {s}: bronze {v['bronze']} accepted {v['accepted']} non_trivial {v['non_trivial']} quarantined {v['quarantined']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
