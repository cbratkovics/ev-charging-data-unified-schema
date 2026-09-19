#!/usr/bin/env python
"""Run the scheduled scoring job (see ev_charging_data_unified_schema/pipeline/scheduled.py).

    python scripts/run_scheduled.py [--season S --period P] [--dry-run]

Exit code 0 for PUBLISH/PROMOTE and 2 for HOLD so the workflow can branch on it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run without installing

import argparse
import json

from ev_charging_data_unified_schema.pipeline import scheduled


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--season", type=int)
    p.add_argument("--period", type=int)
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    log = scheduled.run_scheduled(season=a.season, period=a.period, dry_run=a.dry_run)
    print(json.dumps(log, indent=2))
    return 2 if log["action"] == scheduled.ACTION_HOLD else 0


if __name__ == "__main__":
    sys.exit(main())
