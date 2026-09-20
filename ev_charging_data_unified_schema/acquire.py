"""Polite, cached HTTP acquisition of raw source files.

One request per file, no parallelism, a descriptive User-Agent, and a per-directory record
(``_downloads.json``) of URL, retrieval time, bytes, sha256 and the response headers that matter
for freshness. A file already on disk is not re-downloaded unless ``refresh`` is set; with
``refresh`` the request sends ``If-None-Match`` / ``If-Modified-Since`` when the previous
response supplied them, so an unchanged file costs one 304.

A good cached file is never replaced by anything that cannot be landed (ADR-0015, amendment of
2026-09-20): a 304, any status other than 200 (a 202 "export pending" page, an error), an empty
body, a body that looks like JSON or HTML, or a body with no data rows all leave the cached file
and its record untouched and are reported through :func:`outcome_for`. Only when there is no
good cached file is such a body written at all, and then its record carries ``body_problem``
so the landing step can quarantine it and the next refresh does not pin it with conditional
headers.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import requests

log = logging.getLogger(__name__)

USER_AGENT = (
    "ev-charging-data-unified-schema/0.1 (+https://github.com/cbratkovics/"
    "ev-charging-data-unified-schema; open-data research; contact via repository)"
)
TIMEOUT_S = 600
CHUNK = 1 << 20
RECORD_NAME = "_downloads.json"
PAUSE_BETWEEN_REQUESTS_S = 1.0
BODY_SAMPLE_BYTES = 1 << 16

FetchStatus = Literal["cached", "downloaded", "not_modified", "kept_cached", "downloaded_suspect"]


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
    body_problem: str | None = None
    """Set when the body was written although it does not look landable (no good cached file
    existed to keep). Such a record never sends conditional headers."""


@dataclass(frozen=True)
class FetchOutcome:
    """What one call to :func:`fetch` did to the file on disk."""

    record: DownloadRecord
    status: FetchStatus
    detail: str


_OUTCOMES: dict[Path, FetchOutcome] = {}


def outcome_for(dest: Path) -> FetchOutcome | None:
    """The outcome of the last :func:`fetch` for ``dest`` in this process, if any."""
    return _OUTCOMES.get(dest.resolve())


def reset_outcomes() -> None:
    _OUTCOMES.clear()


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


def body_problem(path: Path) -> str | None:
    """Why the downloaded body cannot be a source file, or None when it looks like a CSV with
    at least one data row. Judged on the first 64 KiB: enough for a header and a row, and a
    one-line status page (JSON or HTML) is always shorter than that."""
    size = path.stat().st_size
    if size == 0:
        return "empty_body: zero bytes"
    with path.open("rb") as f:
        sample = f.read(BODY_SAMPLE_BYTES)
    if sample.startswith(b"\xef\xbb\xbf"):
        sample = sample[3:]
    text = sample.decode("utf-8", errors="replace")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return "empty_body: whitespace only"
    head = lines[0].lstrip()
    if head[:1] in "{[":
        return f"non_csv_body: looks like JSON ({head[:60]!r})"
    if head[:1] == "<":
        return f"non_csv_body: looks like HTML or XML ({head[:60]!r})"
    if len(lines) < 2 and size <= BODY_SAMPLE_BYTES:
        return f"header_only_body: one line and no data rows ({head[:60]!r})"
    return None


def fetch(
    url: str,
    dest: Path,
    *,
    refresh: bool = False,
    session: requests.Session | None = None,
    pause_s: float = PAUSE_BETWEEN_REQUESTS_S,
) -> FetchOutcome:
    """Download ``url`` to ``dest`` unless a good copy is already there. Returns what happened
    and the record that now describes ``dest`` (the prior one whenever it was kept). Raises on
    an HTTP error only when there is no good cached file to fall back on."""
    records = read_records(dest.parent)
    prior = records.get(dest.name)
    good_cache = prior is not None and prior.body_problem is None and dest.exists()
    label = f"{dest.parent.name}/{dest.name}"

    def kept(status: FetchStatus, detail: str) -> FetchOutcome:
        assert prior is not None
        out = FetchOutcome(prior, status, detail)
        _OUTCOMES[dest.resolve()] = out
        return out

    if good_cache and not refresh:
        return kept("cached", "already on disk; refresh not requested")
    sess = session or requests.Session()
    headers = {"User-Agent": USER_AGENT}
    if refresh and good_cache and prior is not None:
        if prior.etag:
            headers["If-None-Match"] = prior.etag
        if prior.last_modified:
            headers["If-Modified-Since"] = prior.last_modified
    time.sleep(pause_s)
    log.info("%s: GET %s%s", label, url, " (conditional)" if len(headers) > 1 else "")
    with sess.get(url, headers=headers, stream=True, timeout=TIMEOUT_S) as r:
        if r.status_code == 304 and good_cache:
            log.info("%s: 304 Not Modified; cached file kept", label)
            return kept("not_modified", "304 Not Modified")
        if r.status_code != 200:
            if good_cache:
                log.warning("%s: HTTP %s; cached file kept", label, r.status_code)
                return kept("kept_cached", f"HTTP {r.status_code}; cached file kept")
            r.raise_for_status()
            raise requests.HTTPError(
                f"{label}: HTTP {r.status_code} from {url} and no cached file to keep"
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        try:
            with tmp.open("wb") as f:
                for chunk in r.iter_content(CHUNK):
                    f.write(chunk)
            problem = body_problem(tmp)
            if problem and good_cache:
                log.warning("%s: %s; cached file kept", label, problem)
                return kept("kept_cached", f"{problem}; cached file kept")
            tmp.replace(dest)
        finally:
            tmp.unlink(missing_ok=True)
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
            body_problem=problem,
        )
    records[dest.name] = rec
    write_records(dest.parent, records)
    if problem:
        log.warning("%s: %s; no cached file to keep, written for the landing step", label, problem)
        out = FetchOutcome(rec, "downloaded_suspect", problem)
    else:
        log.info("%s: downloaded %s bytes", label, rec.bytes)
        out = FetchOutcome(rec, "downloaded", f"HTTP 200, {rec.bytes} bytes")
    _OUTCOMES[dest.resolve()] = out
    return out
