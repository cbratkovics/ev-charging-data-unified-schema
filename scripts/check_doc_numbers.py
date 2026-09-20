#!/usr/bin/env python
"""Claim discipline (docs/BRIEF.md rule 3, ADR-0013 item 4): every measured number in README.md,
docs/FINDINGS.md, docs/CARD.md and docs/adr/*.md is covered by an artifact citation whose value
matches, or sits in a generated block validated by its renderer. Dangling citations fail.

    python scripts/check_doc_numbers.py [paths...]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ev_charging_data_unified_schema.citations import check_document  # noqa: E402
from ev_charging_data_unified_schema.config import REPO_ROOT  # noqa: E402

DEFAULT = ["README.md", "docs/FINDINGS.md", "docs/CARD.md", "docs/adr"]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("paths", nargs="*", default=DEFAULT)
    a = p.parse_args(argv)
    files: list[Path] = []
    for raw in a.paths:
        path = REPO_ROOT / raw
        if path.is_dir():
            files += sorted(path.glob("*.md"))
        elif path.exists():
            files.append(path)
    problems: list[str] = []
    checked = scratch = params = 0
    for f in files:
        is_adr = f.parent.name == "adr"
        pr, n, s, pm = check_document(f, REPO_ROOT, allow_scratch=is_adr)
        problems += pr
        checked += n
        scratch += s
        params += pm
    for pr in problems:
        print(pr)
    print(
        f"{'FAIL' if problems else 'ok'}: {len(files)} files, {checked} cited numbers verified, {scratch} scratch-marked and {params} param-marked sentences, {len(problems)} problem(s)"
    )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
