#!/usr/bin/env python
"""Write exports/ from the built warehouse (ADR-0015): Parquet for every exportable gold
relation, JSON for the small ones, manifest.json with hashes, SCHEMA.md with the column
descriptions and the licence attribution.

    python scripts/export.py [--db .duckdb/dev.duckdb] [--out exports] [--dbt-manifest dbt/target/manifest.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ev_charging_data_unified_schema.config import EXPORTS_DIR, REPO_ROOT  # noqa: E402
from ev_charging_data_unified_schema.exports import run_id, write_exports  # noqa: E402
from ev_charging_data_unified_schema.profiling import git_commit  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--db", type=Path, default=Path(".duckdb/dev.duckdb"))
    p.add_argument("--out", type=Path, default=EXPORTS_DIR)
    p.add_argument(
        "--dbt-manifest", type=Path, default=REPO_ROOT / "dbt" / "target" / "manifest.json"
    )
    a = p.parse_args(argv)
    dbt_manifest = json.loads(a.dbt_manifest.read_text())
    con = duckdb.connect(str(a.db), read_only=True)
    try:
        manifest = write_exports(con, dbt_manifest, a.out, rid=run_id(), code_commit=git_commit())
    finally:
        con.close()
    for name, f in manifest["files"].items():
        print(f"  {name:28s} {f['rows']:>8,} rows {f['bytes'] / 1e6:6.2f} MB")
    print(f"wrote {a.out}/manifest.json and SCHEMA.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
