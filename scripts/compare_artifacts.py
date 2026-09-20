#!/usr/bin/env python
"""Compare fresh full-build artifacts with the committed latest ones (ADR-0015 item 1).

    python scripts/compare_artifacts.py --fresh-dir <dir with silver/ and sensitivity/> [--report out.json] [--issue-body out.md]

Exit codes: 0 ok, 2 upstream data changed (informational), 3 regression or blocking.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ev_charging_data_unified_schema.compare import classify_run, issue_body  # noqa: E402
from ev_charging_data_unified_schema.config import ARTIFACTS_DIR  # noqa: E402

EXIT = {"ok": 0, "upstream_changed": 2, "regression": 3}


def latest(root: Path, kind: str) -> dict:
    d = root / kind
    return json.loads((d / json.loads((d / "latest.json").read_text())["path"]).read_text())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--fresh-dir", type=Path, required=True)
    p.add_argument("--committed-dir", type=Path, default=ARTIFACTS_DIR)
    p.add_argument("--report", type=Path, default=None)
    p.add_argument("--issue-body", type=Path, default=None)
    a = p.parse_args(argv)
    report = classify_run(
        latest(a.committed_dir, "silver"),
        latest(a.fresh_dir, "silver"),
        latest(a.committed_dir, "sensitivity"),
        latest(a.fresh_dir, "sensitivity"),
    )
    title, body = issue_body(report)
    report["issue_title"] = title
    if a.report:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(json.dumps(report, indent=2, default=str) + "\n")
    if a.issue_body:
        a.issue_body.parent.mkdir(parents=True, exist_ok=True)
        a.issue_body.write_text(body + "\n")
    print(
        f"status: {report['status']} ({len(report['input_changes'])} input change(s), {len(report['output_differences'])} output difference(s), reconciliation {report['reconciliation_status']})"
    )
    return EXIT[report["status"]]


if __name__ == "__main__":
    sys.exit(main())
