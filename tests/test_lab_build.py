from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from ev_charging_data_unified_schema.config import REPO_ROOT
from scripts.build_lab import build_lab, load_pointer


def test_combined_site_preserves_docs_and_packages_only_allowlisted_files(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    docs = b"fixture docs\n"
    manifest = b'{"fixture":true}\n'
    (site / "index.html").write_bytes(docs)
    (site / "manifest.json").write_bytes(manifest)
    build_lab(site)
    build_lab(site)
    assert (site / "index.html").read_bytes() == docs
    assert (site / "manifest.json").read_bytes() == manifest
    files = {
        p.relative_to(site / "lab").as_posix() for p in (site / "lab").rglob("*") if p.is_file()
    }
    pointer = json.loads((site / "lab/data/latest.json").read_text())
    assert files == {
        "index.html",
        "assets/app.js",
        "assets/contract.js",
        "assets/styles.css",
        "build-info.json",
        "data/latest.json",
        f"data/{pointer['path']}",
    }
    source = REPO_ROOT / "exports/decision_lab" / pointer["path"]
    packaged = site / "lab/data" / pointer["path"]
    assert packaged.read_bytes() == source.read_bytes()
    assert (
        json.loads((site / "lab/build-info.json").read_text())["record_sha256"]
        == hashlib.sha256(source.read_bytes()).hexdigest()
    )
    assert not (site / "lab/fresh").exists()


def test_pointer_validation_rejects_traversal_and_inconsistent_identity(tmp_path: Path) -> None:
    pointer = tmp_path / "latest.json"
    pointer.write_text(json.dumps({"decision_id": "x", "record_version": "x", "path": "../x.json"}))
    with pytest.raises(ValueError, match="unsafe or inconsistent"):
        load_pointer(pointer)


def test_build_rejects_public_pointer_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "apps", root / "apps")
    shutil.copytree(REPO_ROOT / "exports/decision_lab", root / "exports/decision_lab")
    shutil.copytree(REPO_ROOT / "artifacts", root / "artifacts")
    pointer = json.loads((root / "exports/decision_lab/latest.json").read_text())
    pointer["decision_id"] = "different"
    (root / "exports/decision_lab/latest.json").write_text(json.dumps(pointer))
    with pytest.raises(ValueError, match="pointers differ"):
        build_lab(tmp_path / "site", repo_root=root)
