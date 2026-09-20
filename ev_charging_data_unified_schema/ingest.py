"""Download, check, land: ``python -m ev_charging_data_unified_schema.ingest``.

For every source in ``config.PROJECT.sources``: download the published files (skipping files
already on disk), and for each file whose sha256 is not already in the landing manifest, read it
as strings, check it against the source contract, and land it as parquet under
``LANDED_DIR/<source>/`` (or ``LANDED_DIR/<source>/_quarantined/`` when the contract
quarantines the batch). The manifest records URL, retrieval time, bytes, sha256, row count and
landed path per file; the drift artifact records every contract finding. Re-running with
unchanged files lands nothing and still writes a drift artifact for the run.

Options: ``--sources a b`` to restrict; ``--no-download`` to land what is already in
``--raw-dir`` (the fixture path used by tests and CI); ``--refresh`` to re-request files with
conditional headers.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

from ev_charging_data_unified_schema import acquire
from ev_charging_data_unified_schema.config import ARTIFACTS_DIR, LANDED_DIR, PROJECT, RAW_DIR
from ev_charging_data_unified_schema.data import loader as landing
from ev_charging_data_unified_schema.data.contracts import (
    CONTRACTS,
    FileDrift,
    check_file,
    drift_artifact,
)
from ev_charging_data_unified_schema.interfaces import ManifestEntry
from ev_charging_data_unified_schema.profiling import git_commit
from ev_charging_data_unified_schema.sources import LOADERS

QUARANTINE_DIR = "_quarantined"


def run_id(now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now(dt.UTC)
    return "ingest-" + now.strftime("%Y%m%dT%H%M%SZ")


def land_source(
    name: str,
    raw_dir: Path,
    landed_dir: Path,
    manifest: dict[str, ManifestEntry],
    *,
    download: bool,
    refresh: bool,
    retrieved_at: str | None = None,
) -> tuple[list[FileDrift], list[str]]:
    """Land one source. Returns the drift records for every file seen and the manifest keys
    that were (re)landed."""
    loader_ = LOADERS[name]
    contract = CONTRACTS[name]
    if download:
        paths = loader_.download(raw_dir, refresh=refresh)
    else:
        paths = sorted((raw_dir / name).glob("*.csv"))
    records = acquire.read_records(raw_dir / name)
    drifts: list[FileDrift] = []
    landed_keys: list[str] = []
    for path in paths:
        key = landing.manifest_key(name, path.name)
        prior = manifest.get(key)
        frame = loader_.read_raw(path)
        frame, drift = check_file(frame, contract, path.name)
        drifts.append(drift)
        if (
            landing.is_unchanged(prior, path)
            and prior is not None
            and ((drift.outcome == "quarantine") == (QUARANTINE_DIR in prior.landed_path))
        ):
            continue  # unchanged bytes, same outcome: a no-op
        sub = landed_dir / name / (QUARANTINE_DIR if drift.outcome == "quarantine" else "")
        rec = records.get(path.name)
        # offline landings (the fixture, tests) pass a fixed retrieved_at so the landed files,
        # and everything derived from them, are deterministic
        file_retrieved_at = (
            rec.retrieved_at
            if rec
            else (retrieved_at or dt.datetime.now(dt.UTC).isoformat(timespec="seconds"))
        )
        landed = landing.land_frame(
            frame, source=name, file_name=path.name, retrieved_at=file_retrieved_at
        )
        out = landing.write_landed(landed, sub / (path.stem + ".parquet"))
        # a file that changed outcome must not linger in the other location
        other = (landed_dir / name / (QUARANTINE_DIR if drift.outcome != "quarantine" else "")) / (
            path.stem + ".parquet"
        )
        if other.exists():
            other.unlink()
        manifest[key] = ManifestEntry(
            source=name,
            file_name=path.name,
            url=rec.url if rec else "",
            retrieved_at=file_retrieved_at,
            bytes=path.stat().st_size,
            sha256=landing.sha256_of(path),
            row_count=int(len(landed)),
            landed_path=landing.repo_relative(out),
        )
        landed_keys.append(key)
    return drifts, landed_keys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--sources", nargs="*", default=list(PROJECT.source_names))
    p.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    p.add_argument("--landed-dir", type=Path, default=LANDED_DIR)
    p.add_argument("--drift-dir", type=Path, default=ARTIFACTS_DIR / "drift")
    p.add_argument("--no-download", action="store_true", help="land what is already in --raw-dir")
    p.add_argument(
        "--refresh", action="store_true", help="re-request files with conditional headers"
    )
    p.add_argument(
        "--retrieved-at",
        default=None,
        help="ISO-8601 UTC timestamp recorded for files without a download record (offline landings)",
    )
    a = p.parse_args(argv)
    rid = run_id()
    manifest = landing.read_manifest(a.landed_dir)
    all_drifts: list[FileDrift] = []
    summary: dict[str, Any] = {}
    for name in a.sources:
        drifts, landed = land_source(
            name,
            a.raw_dir,
            a.landed_dir,
            manifest,
            download=not a.no_download,
            refresh=a.refresh,
            retrieved_at=a.retrieved_at,
        )
        all_drifts += drifts
        summary[name] = {
            "files_seen": len(drifts),
            "files_landed": len(landed),
            "quarantined": [d.file_name for d in drifts if d.outcome == "quarantine"],
        }
        print(
            f"{name}: {len(drifts)} file(s) seen, {len(landed)} landed, {len(summary[name]['quarantined'])} quarantined"
        )
    landing.write_manifest(a.landed_dir, manifest)
    art = drift_artifact(rid, git_commit(), all_drifts)
    art["ingest"] = {
        "sources": summary,
        "raw_dir": str(a.raw_dir),
        "landed_dir": str(a.landed_dir),
        "download": not a.no_download,
    }
    a.drift_dir.mkdir(parents=True, exist_ok=True)
    (a.drift_dir / f"{rid}.json").write_text(json.dumps(art, indent=2, sort_keys=True) + "\n")
    (a.drift_dir / "latest.json").write_text(
        json.dumps({"run_id": rid, "path": f"{rid}.json"}) + "\n"
    )
    print(f"drift artifact: {a.drift_dir / (rid + '.json')} ({art['summary']['by_outcome']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
