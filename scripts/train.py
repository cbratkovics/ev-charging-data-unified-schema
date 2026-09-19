#!/usr/bin/env python
"""Train champion/challenger candidates on the loader's rows and write a model artifact.

python scripts/train.py [--refresh]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run without installing

import argparse

from ev_charging_data_unified_schema.config import PROJECT
from ev_charging_data_unified_schema.data import loader
from ev_charging_data_unified_schema.models import train


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--refresh", action="store_true", help="bypass the loader cache")
    a = p.parse_args()
    seasons = range(PROJECT.min_season, PROJECT.test_season + 1)
    rows = loader.load_period_rows(seasons, refresh=a.refresh)
    meta = train.train_all(rows)
    print(f"trained {meta['model_version']} on {meta['input_rows']} rows")
    for c, m in meta["cohorts"].items():
        print(
            f"  {c}: champion {m['champion']} "
            + ", ".join(
                f"{k} val {v['val_mae']:.3f} test {v['test_mae']:.3f}"
                for k, v in m["candidates"].items()
            )
        )


if __name__ == "__main__":
    main()
