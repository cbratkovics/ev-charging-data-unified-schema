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
from ev_charging_data_unified_schema.config import ARTIFACTS_DIR, REPO_ROOT  # noqa: E402


def latest(kind: str) -> dict[str, Any] | None:
    d = ARTIFACTS_DIR / kind
    if not (d / "latest.json").exists():
        return None
    return json.loads((d / json.loads((d / "latest.json").read_text())["path"]).read_text())


def n(x: Any) -> str:
    return f"{x:,}" if isinstance(x, int) else f"{x:,.0f}"


def pct(x: float | None, d: int = 1) -> str:
    return "n/a" if x is None else f"{100 * x:.{d}f}%"


def results_block(
    silver: dict[str, Any], sens: dict[str, Any], findings: dict[str, Any] | None
) -> str:
    rows = [
        "| Source | Raw rows | Sessions in the fact | Quarantined | Non-trivial sessions | Stations with capacity | Utilization (production port count) |",
        "|---|---|---|---|---|---|---|",
    ]
    prod = {}
    if findings:
        for k, v in findings["utilization_ranges"].items():
            src, fl = k.split("__")
            if v.get("production") is not None:
                prod.setdefault(src, []).append(f"{fl} {pct(v['production'])}")
    stations = {}
    for s in silver["by_source"]:
        stations[s] = None
    dim = sens.get("dim_station", {})
    for s, v in silver["by_source"].items():
        util = ", ".join(prod.get(s, [])) or "n/a"
        rows.append(
            f"| {s} | {n(v['bronze'])} | {n(v['accepted'])} | {n(v['quarantined'])} | {n(v['non_trivial'])} | see below | {util} |"
        )
    lines = [
        f"_Rendered by `scripts/render_docs.py` from `artifacts/silver/{silver['run_id']}.json` and `artifacts/sensitivity/{sens['run_id']}.json`"
        + (f" and `artifacts/findings/{findings['run_id']}.json`" if findings else "")
        + "._",
        "",
        *rows,
        "",
        f"Stations with inferred capacity: {n(dim.get('stations', 0))} ({', '.join(f'{k} ports: {n(v)}' for k, v in sorted(dim.get('ports_inferred_distribution', {}).items(), key=lambda kv: int(kv[0])))}); "
        f"binding bound: {', '.join(f'{k} {n(v)}' for k, v in sorted(dim.get('ports_source', {}).items()))}. "
        f"Excluded days: {n(dim.get('excluded_days_total', 0))} of {n(dim.get('window_days_total', 0))} station-window days.",
        "",
        f"Reconciliation status: **{silver.get('status', 'n/a')}** (both identities per source and month; ADR-0013).",
    ]
    return "\n".join(lines)


BLOCKS = {
    "results": lambda: results_block(latest("silver"), latest("sensitivity"), latest("findings")),
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
