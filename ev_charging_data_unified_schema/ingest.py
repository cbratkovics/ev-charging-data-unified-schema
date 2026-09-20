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

Nothing that arrives unusable reaches bronze or the crash path. ``acquire.fetch`` never
replaces a good cached raw file with a 304, an error status, an empty or non-CSV body. If the
raw file on disk is still unreadable or has no data rows, the file is quarantined
(``unreadable_file`` / ``empty_file``), the last good landed parquet and its manifest entry are
kept, and the run continues; the drift artifact records it and the full-build workflow opens an
issue. Every landing step logs ``<source>/<file>`` so a traceback names the file
(ADR-0015, amendment of 2026-09-20).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path
from typing import Any

from ev_charging_data_unified_schema import acquire
from ev_charging_data_unified_schema.config import (
    ARTIFACTS_DIR,
    LANDED_DIR,
    PROJECT,
    RAW_DIR,
    REPO_ROOT,
)
from ev_charging_data_unified_schema.data import loader as landing
from ev_charging_data_unified_schema.data.contracts import (
    CONTRACTS,
    ColumnFinding,
    FileDrift,
    check_file,
    drift_artifact,
    unreadable_drift,
)
from ev_charging_data_unified_schema.interfaces import ManifestEntry
from ev_charging_data_unified_schema.profiling import git_commit
from ev_charging_data_unified_schema.sources import LOADERS

QUARANTINE_DIR = "_quarantined"
KEEP_LAST_GOOD_CODES = frozenset({"empty_file", "unreadable_file"})
log = logging.getLogger(__name__)


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
    if download:
        log.info("%s: downloading into %s (refresh=%s)", name, raw_dir / name, refresh)
        paths = loader_.download(raw_dir, refresh=refresh)
    else:
        paths = sorted((raw_dir / name).glob("*.csv"))
    records = acquire.read_records(raw_dir / name)
    drifts: list[FileDrift] = []
    landed_keys: list[str] = []
    for path in paths:
        try:
            landed_key = _land_file(
                name, path, landed_dir, manifest, records, drifts, retrieved_at=retrieved_at
            )
        except Exception as e:
            log.error("%s/%s: landing failed: %s: %s", name, path.name, type(e).__name__, e)
            e.add_note(f"while landing {name}/{path.name} from {path}")
            raise
        if landed_key:
            landed_keys.append(landed_key)
    return drifts, landed_keys


def _fetch_note(path: Path) -> ColumnFinding | None:
    """An info finding when the download step kept the cached raw file instead of replacing
    it (304, an error status, an empty or non-CSV body), so the drift artifact says why the
    landed data did not move."""
    outcome = acquire.outcome_for(path)
    if outcome is None or outcome.status not in ("not_modified", "kept_cached"):
        return None
    return ColumnFinding("*", "info", "refresh_kept_cached", outcome.detail)


def _land_file(
    name: str,
    path: Path,
    landed_dir: Path,
    manifest: dict[str, ManifestEntry],
    records: dict[str, acquire.DownloadRecord],
    drifts: list[FileDrift],
    *,
    retrieved_at: str | None,
) -> str | None:
    """Check and land one raw file. Appends its drift record; returns the manifest key when the
    file was (re)landed, else None."""
    contract = CONTRACTS[name]
    key = landing.manifest_key(name, path.name)
    prior = manifest.get(key)
    log.info("%s/%s: reading %s", name, path.name, path)
    try:
        frame = LOADERS[name].read_raw(path)
    except Exception as e:  # pandas EmptyDataError / ParserError, UnicodeDecodeError, OSError
        log.warning("%s/%s: unreadable: %s: %s", name, path.name, type(e).__name__, e)
        frame, drift = None, unreadable_drift(name, path.name, e)
    else:
        frame, drift = check_file(frame, contract, path.name)
    if note := _fetch_note(path):
        drift.findings.append(note)
        if drift.outcome == "ok":
            drift.outcome = "info"
    drifts.append(drift)
    log.info(
        "%s/%s: %d row(s), outcome %s%s",
        name,
        path.name,
        drift.rows,
        drift.outcome,
        f" ({', '.join(drift.reason_codes)})" if drift.reason_codes else "",
    )
    if (
        landing.is_unchanged(prior, path)
        and prior is not None
        and ((drift.outcome == "quarantine") == (QUARANTINE_DIR in prior.landed_path))
    ):
        return None  # unchanged bytes, same outcome: a no-op
    if KEEP_LAST_GOOD_CODES & set(drift.reason_codes):
        good = prior is not None and QUARANTINE_DIR not in prior.landed_path
        if good and prior is not None and (REPO_ROOT / prior.landed_path).exists():
            detail = (
                f"last good landed file kept: {prior.landed_path} "
                f"(retrieved {prior.retrieved_at}, {prior.row_count} rows, sha256 {prior.sha256[:12]})"
            )
            log.warning("%s/%s: %s", name, path.name, detail)
            drift.findings.append(ColumnFinding("*", "info", "last_good_kept", detail))
            return None
        if frame is None:
            log.warning(
                "%s/%s: unreadable and nothing good landed before; nothing landed", name, path.name
            )
            if prior is not None and not (REPO_ROOT / prior.landed_path).exists():
                del manifest[key]  # a dangling entry would describe a file bronze cannot read
            return None
    assert frame is not None
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
    log.info("%s/%s: written %s", name, path.name, landing.repo_relative(out))
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
    return key


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
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr
    )
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
