#!/usr/bin/env python
"""Keep only artifacts still referenced by latest, an ADR, or an immutable decision record.

python scripts/prune_artifacts.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ev_charging_data_unified_schema.config import ARTIFACTS_DIR, REPO_ROOT  # noqa: E402

CITED_RE = re.compile(r"artifacts/([\w-]+)/([\w-]+\.json)")


def cited_by_adrs() -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for adr in (REPO_ROOT / "docs" / "adr").glob("*.md"):
        for kind, name in CITED_RE.findall(adr.read_text(encoding="utf-8")):
            out.add((kind, name))
    return out


def cited_by_decisions() -> set[tuple[str, str]]:
    """Protect the bounded evidence paths pinned by committed decision records."""
    out: set[tuple[str, str]] = set()
    for record in (ARTIFACTS_DIR / "decisions").glob("*.json"):
        if record.name == "latest.json":
            continue
        value = json.loads(record.read_text(encoding="utf-8"))
        for ref in value.get("evidence", {}).get("artifacts", {}).values():
            match = CITED_RE.fullmatch(ref.get("path", ""))
            if match:
                out.add((match.group(1), match.group(2)))
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    adr_keep = cited_by_adrs()
    decision_keep = cited_by_decisions()
    keep = adr_keep | decision_keep
    removed: list[Path] = []
    for kind_dir in sorted(d for d in ARTIFACTS_DIR.iterdir() if d.is_dir()):
        latest = kind_dir / "latest.json"
        current = json.loads(latest.read_text())["path"] if latest.exists() else None
        for f in sorted(kind_dir.glob("*.json")):
            if f.name == "latest.json" or f.name == current or (kind_dir.name, f.name) in keep:
                continue
            removed.append(f)
            if not a.dry_run:
                f.unlink()
    for f in removed:
        print(("would remove " if a.dry_run else "removed ") + f.relative_to(REPO_ROOT).as_posix())
    print(
        f"{'dry run: ' if a.dry_run else ''}{len(removed)} artifact(s) pruned; kept latest per kind plus {len(adr_keep)} ADR-cited and {len(decision_keep)} decision-cited file(s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
