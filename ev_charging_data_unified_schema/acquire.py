"""Polite, cached HTTP acquisition of raw source files.

One request per file, no parallelism, a descriptive User-Agent, and a per-directory record
(``_downloads.json``) of URL, retrieval time, bytes, sha256 and the response headers that matter
for freshness. A file already on disk is not re-downloaded unless ``refresh`` is set; with
``refresh`` the request sends ``If-None-Match`` / ``If-Modified-Since`` when the previous
response supplied them, so an unchanged file costs one 304.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import requests

USER_AGENT = (
    "ev-charging-data-unified-schema/0.1 (+https://github.com/cbratkovics/"
    "ev-charging-data-unified-schema; open-data research; contact via repository)"
)
TIMEOUT_S = 600
CHUNK = 1 << 20
RECORD_NAME = "_downloads.json"
PAUSE_BETWEEN_REQUESTS_S = 1.0


@dataclass(frozen=True)
class DownloadRecord:
    file_name: str
    url: str
    retrieved_at: str
    bytes: int
    sha256: str
    status: int
    etag: str | None
    last_modified: str | None
    content_type: str | None


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def read_records(directory: Path) -> dict[str, DownloadRecord]:
    p = directory / RECORD_NAME
    if not p.exists():
        return {}
    return {k: DownloadRecord(**v) for k, v in json.loads(p.read_text()).items()}


def write_records(directory: Path, records: dict[str, DownloadRecord]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / RECORD_NAME).write_text(
        json.dumps({k: asdict(v) for k, v in sorted(records.items())}, indent=2) + "\n"
    )


def fetch(
    url: str,
    dest: Path,
    *,
    refresh: bool = False,
    session: requests.Session | None = None,
    pause_s: float = PAUSE_BETWEEN_REQUESTS_S,
) -> DownloadRecord:
    """Download ``url`` to ``dest`` unless it is already there. Returns the record (existing or
    new). Raises on any HTTP error."""
    records = read_records(dest.parent)
    prior = records.get(dest.name)
    if dest.exists() and prior is not None and not refresh:
        return prior
    sess = session or requests.Session()
    headers = {"User-Agent": USER_AGENT}
    if refresh and prior is not None and dest.exists():
        if prior.etag:
            headers["If-None-Match"] = prior.etag
        if prior.last_modified:
            headers["If-Modified-Since"] = prior.last_modified
    time.sleep(pause_s)
    with sess.get(url, headers=headers, stream=True, timeout=TIMEOUT_S) as r:
        if r.status_code == 304 and prior is not None:
            return prior
        r.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        with tmp.open("wb") as f:
            for chunk in r.iter_content(CHUNK):
                f.write(chunk)
        tmp.replace(dest)
        rec = DownloadRecord(
            file_name=dest.name,
            url=url,
            retrieved_at=_now(),
            bytes=dest.stat().st_size,
            sha256=sha256_of(dest),
            status=r.status_code,
            etag=r.headers.get("ETag"),
            last_modified=r.headers.get("Last-Modified"),
            content_type=r.headers.get("Content-Type"),
        )
    records[dest.name] = rec
    write_records(dest.parent, records)
    return rec
