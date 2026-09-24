#!/usr/bin/env python
"""Render the number-bearing blocks of README.md and docs/CARD.md from the artifacts, between
`<!-- generated:<name> start -->` / `end` markers (ADR-0013 item 3). --check fails when a
committed document differs from its render.

    python scripts/render_docs.py [--check]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ev_charging_data_unified_schema.config import ARTIFACTS_DIR, PROJECT, REPO_ROOT  # noqa: E402


def latest(kind: str) -> dict[str, Any] | None:
    d = ARTIFACTS_DIR / kind
    if not (d / "latest.json").exists():
        return None
    return json.loads((d / json.loads((d / "latest.json").read_text())["path"]).read_text())


def n(x: Any) -> str:
    return f"{x:,}" if isinstance(x, int) else f"{x:,.0f}"


def pct(x: float | None, d: int = 1) -> str:
    return "n/a" if x is None else f"{100 * x:.{d}f}%"


def source_label(code: str) -> str:
    """The source's display name; the code id stays in the artifact keys."""
    return PROJECT.source(code).display_name


def results_block(
    silver: dict[str, Any], sens: dict[str, Any], findings: dict[str, Any] | None
) -> str:
    """Utilization with its range per source, and the reconciliation status; nothing more."""
    labels = {"connected": "connected-time", "charging": "charging-time"}
    rows = [
        "| Source | Period | Utilization (production port count) | Range across denominator definitions |",
        "|---|---|---|---|",
    ]
    if findings:
        periods = findings["periods"]
        for key, r in sorted(findings["utilization_ranges"].items()):
            src, fl = key.split("__")
            per = (
                f"{periods[src]['first_start_local'][:7]} to {periods[src]['last_start_local'][:7]}"
            )
            rows.append(
                f"| {source_label(src)} | {per} | {labels[fl]} {pct(r['production'])} | {pct(r['min'])} ({r['min_definition']}) to {pct(r['max'])} ({r['max_definition']}) |"
            )
    lines = [
        (
            f"_Rendered by `scripts/render_docs.py` from `artifacts/findings/{findings['run_id']}.json` and "
            f"`artifacts/silver/{silver['run_id']}.json`; a ratio of summed minutes over summed available port minutes, "
            "never an average of daily percentages; ports are inferred lower bounds, so these are upper bounds on utilization._"
            if findings
            else "_No findings artifact yet._"
        ),
        "",
        (
            f"**Boulder, {periods['boulder']['first_start_local'][:10]} to "
            f"{periods['boulder']['last_start_local'][:10]}.** "
            f"{pct(findings['boulder_idle']['production']['idle_share_of_connected'])} of connected time was idle after charging, "
            f"but only **up to {pct(findings['boulder_idle']['production']['full_occupancy_idle_share_of_connected'])} of connected time** "
            "was idle while every inferred port was occupied. The first measures plug-in time after charging ended; the second asks when that idle time "
            "coincided with inferred full occupancy. Neither measures a queue, and even the smaller figure does not show that a driver was waiting."
            if findings
            else ""
        ),
        "",
        *rows,
        "",
        f"Reconciliation status (both identities, every source and month): **{silver.get('status', 'n/a')}**. "
        "Sources cover different years and countries; nothing here compares one with another.",
    ]
    return "\n".join(lines)


def card_block(silver: dict[str, Any], findings: dict[str, Any] | None) -> str:
    """The card's headline figures, each with its key."""
    if not findings:
        return "_No findings artifact yet._"
    labels = {"connected": "connected-time", "charging": "charging-time"}
    idle = findings["boulder_idle"]["production"]
    period = findings["periods"]["boulder"]
    rows = [
        f"- {source_label('boulder')}, {period['first_start_local'][:10]} to {period['last_start_local'][:10]}: "
        f"{pct(idle['idle_share_of_connected'])} of connected time was idle after charging, but **up to "
        f"{pct(idle['full_occupancy_idle_share_of_connected'])} of connected time** was idle while every inferred port was occupied. "
        "These answer different questions: post-charge plug-in time versus its overlap with inferred full occupancy. "
        "Neither observes a queue, so even the smaller figure does not prove a driver was waiting.",
        "- Within-source utilization only (different operators, places and periods; production port count; range across denominator definitions): "
        + "; ".join(
            f"{source_label(k.split('__')[0])}, "
            f"{findings['periods'][k.split('__')[0]]['first_start_local'][:10]} to {findings['periods'][k.split('__')[0]]['last_start_local'][:10]}, "
            f"{labels[k.split('__')[1]]} {pct(r['production'])} ({pct(r['min'])} to {pct(r['max'])})"
            for k, r in sorted(findings["utilization_ranges"].items())
        )
        + ".",
        f"- Reconciliation: every source reconciles exactly on rows and sessions; status **{silver.get('status', 'n/a')}**.",
        f"- Rows: {n(sum(v['bronze'] for v in silver['by_source'].values()))} landed, "
        f"{n(sum(v['accepted'] for v in silver['by_source'].values()))} accepted sessions, "
        f"{n(sum(v['quarantined'] for v in silver['by_source'].values()))} quarantined with a primary reason each.",
        f"_Keys: `artifacts/findings/{findings['run_id']}.json` boulder_idle.production, utilization_ranges; "
        f"`artifacts/silver/{silver['run_id']}.json` status, by_source._",
    ]
    return "\n".join(rows)


BLOCKS = {
    "results": lambda: results_block(latest("silver"), latest("sensitivity"), latest("findings")),
    "card": lambda: card_block(latest("silver"), latest("findings")),
}


def splice(doc: str, name: str, body: str) -> str:
    pat = re.compile(
        rf"(<!-- generated:{name} start -->\n).*?(<!-- generated:{name} end -->)", re.S
    )
    if not pat.search(doc):
        raise SystemExit(f"no generated:{name} markers found")
    return pat.sub(lambda m: m.group(1) + body + "\n" + m.group(2), doc)


def render_file(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    for name, fn in BLOCKS.items():
        if f"<!-- generated:{name} start -->" in text:
            text = splice(text, name, fn())
    return text


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--check", action="store_true")
    a = p.parse_args(argv)
    targets = [REPO_ROOT / "README.md", REPO_ROOT / "docs" / "CARD.md"]
    stale = []
    for t in targets:
        if not t.exists():
            continue
        rendered = render_file(t)
        if a.check:
            if t.read_text(encoding="utf-8") != rendered:
                stale.append(t.relative_to(REPO_ROOT).as_posix())
        else:
            t.write_text(rendered, encoding="utf-8")
            print(f"rendered {t.relative_to(REPO_ROOT)}")
    if a.check:
        if stale:
            print(
                "stale generated blocks: "
                + ", ".join(stale)
                + "; run python scripts/render_docs.py"
            )
            return 1
        print("ok: generated blocks match the artifacts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
