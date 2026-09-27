#!/usr/bin/env python
"""Validate and stage the Decision Lab into an owned ``lab/`` site subtree."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ev_charging_data_unified_schema.config import REPO_ROOT  # noqa: E402
from ev_charging_data_unified_schema.decision_records import validate_record  # noqa: E402

APP = REPO_ROOT / "apps" / "decision-lab"
PUBLIC = REPO_ROOT / "exports" / "decision_lab"
CANONICAL = REPO_ROOT / "artifacts" / "decisions"


def load_pointer(path: Path) -> dict:
    pointer = json.loads(path.read_text(encoding="utf-8"))
    required = {"decision_id", "record_version", "path"}
    if set(pointer) != required:
        raise ValueError(f"{path}: pointer fields must be exactly {sorted(required)}")
    filename = pointer["path"]
    if (
        not isinstance(filename, str)
        or Path(filename).name != filename
        or f"{pointer['record_version']}.json" != filename
    ):
        raise ValueError(f"{path}: unsafe or inconsistent record path")
    return pointer


def git_state(root: Path) -> tuple[str, bool]:
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    dirty = bool(
        subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip()
    )
    return commit, dirty


def build_lab(output: Path, *, repo_root: Path = REPO_ROOT) -> Path:
    """Replace only ``output/lab``; existing site root files are never touched."""
    app = repo_root / "apps" / "decision-lab"
    public = repo_root / "exports" / "decision_lab"
    canonical = repo_root / "artifacts" / "decisions"
    pointer = load_pointer(public / "latest.json")
    canonical_pointer = load_pointer(canonical / "latest.json")
    if pointer != canonical_pointer:
        raise ValueError("canonical and public latest pointers differ")
    record_path = public / pointer["path"]
    canonical_path = canonical / pointer["path"]
    if not record_path.is_file() or not canonical_path.is_file():
        raise FileNotFoundError("latest pointer target is missing")
    record_bytes = record_path.read_bytes()
    if record_bytes != canonical_path.read_bytes():
        raise ValueError("canonical and public record bytes differ")
    record = json.loads(record_bytes)
    if (
        record["decision_id"] != pointer["decision_id"]
        or record["record_version"] != pointer["record_version"]
    ):
        raise ValueError("latest pointer and record identity differ")
    validate_record(record, repo_root=repo_root)

    output.mkdir(parents=True, exist_ok=True)
    lab = output / "lab"
    if lab.exists():
        if lab.is_symlink() or not lab.is_dir():
            raise ValueError(f"refusing to replace unsafe owned path: {lab}")
        shutil.rmtree(lab)
    shutil.copytree(app, lab, symlinks=False)
    data = lab / "data"
    data.mkdir()
    shutil.copyfile(public / "latest.json", data / "latest.json")
    shutil.copyfile(record_path, data / pointer["path"])
    commit, dirty = git_state(repo_root)
    info = {
        "site_source_commit": commit,
        "dirty": dirty,
        "record_version": pointer["record_version"],
        "record_filename": pointer["path"],
        "record_sha256": hashlib.sha256(record_bytes).hexdigest(),
    }
    (lab / "build-info.json").write_text(json.dumps(info, indent=2, sort_keys=True) + "\n")
    return lab


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "site")
    args = parser.parse_args(argv)
    lab = build_lab(args.output.resolve())
    print(f"staged {lab}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
