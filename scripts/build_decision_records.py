#!/usr/bin/env python
"""Build or check the committed Boulder decision record from pinned aggregate artifacts."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ev_charging_data_unified_schema.config import REPO_ROOT  # noqa: E402
from ev_charging_data_unified_schema.decision_records import (  # noqa: E402
    build_record,
    validate_record,
    write_record,
)


def check_record(*, repo_root: Path, artifacts_dir: Path, builder_commit: str) -> str:
    """Run the same freshness and byte-equality check used by ``--check``."""
    candidate = build_record(
        artifacts_dir=artifacts_dir, repo_root=repo_root, builder_commit=builder_commit
    )
    version = candidate["record_version"]
    artifact = repo_root / "artifacts" / "decisions" / f"{version}.json"
    public = repo_root / "exports" / "decision_lab" / f"{version}.json"
    if not artifact.exists() or not public.exists():
        raise FileNotFoundError(f"missing generated decision record {version}")
    committed = json.loads(artifact.read_text(encoding="utf-8"))
    validate_record(committed, repo_root=repo_root)
    if committed["record_version"] != version or artifact.read_bytes() != public.read_bytes():
        raise ValueError("decision record analytical version or public copy is stale")
    return version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    if args.check:
        try:
            version = check_record(
                repo_root=REPO_ROOT,
                artifacts_dir=REPO_ROOT / "artifacts",
                builder_commit=commit,
            )
        except (FileNotFoundError, ValueError) as exc:
            print(exc)
            return 1
        print(f"ok: decision record {version} and pinned evidence are valid")
        return 0
    candidate = build_record(builder_commit=commit)
    artifact, public = write_record(candidate)
    print(f"wrote {artifact.relative_to(REPO_ROOT)} and {public.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
