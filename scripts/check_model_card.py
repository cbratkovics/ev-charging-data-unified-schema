#!/usr/bin/env python
"""Fail when docs/MODEL_CARD.md (or the README results section) still carries placeholders.

The shipped MODEL_CARD.md is a placeholder until `python scripts/evaluate.py` regenerates it
from artifacts; any of the markers below means a number is not backed by an artifact:

    python scripts/check_model_card.py [--paths docs/MODEL_CARD.md README.md]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

MARKERS = (
    re.compile(r"\bTBD\b"),
    re.compile(r"\bXX\.?X*\b"),
    re.compile(r"PLACEHOLDER", re.IGNORECASE),
    re.compile(r"\{\{\s*[a-z_]+\s*\}\}"),  # unrendered template expression
    re.compile(r"<fill[^>]*>", re.IGNORECASE),
)


def find_placeholders(text: str) -> list[str]:
    hits = []
    for i, line in enumerate(text.splitlines(), start=1):
        for m in MARKERS:
            if m.search(line):
                hits.append(f"{i}: {line.strip()[:100]}")
                break
    return hits


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--paths", nargs="*", default=["docs/MODEL_CARD.md"])
    a = p.parse_args(argv)
    bad = 0
    for path in a.paths:
        text = Path(path).read_text(encoding="utf-8")
        hits = find_placeholders(text)
        if "Generated" not in text.splitlines()[2] if len(text.splitlines()) > 2 else True:
            hits.insert(0, "header: not a generated card (run python scripts/evaluate.py)")
        for h in hits:
            print(f"{path}:{h}")
        bad += len(hits)
    print("ok: no placeholder numbers" if not bad else f"{bad} placeholder(s) found")
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from ev_charging_data_unified_schema.eval import drift

        if not drift.CALIBRATED:
            print(
                "WARNING: drift thresholds are NOT calibrated (ev_charging_data_unified_schema/eval/drift.py: CALIBRATED = False); "
                "the scheduled job cannot HOLD on drift until the calibration recipe has been followed"
            )
    except ImportError:
        pass
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
