"""The fetcher never replaces a good cached raw file with anything that cannot be landed
(ADR-0015, amendment of 2026-09-20). Everything here is offline: the HTTP session is a stub."""

from __future__ import annotations

from pathlib import Path

import pytest
import requests

from ev_charging_data_unified_schema import acquire

GOOD = b"a,b\n1,2\n"
URL = "https://example.invalid/f.csv"


def _restored_cache(tmp_path: Path) -> tuple[Path, acquire.DownloadRecord]:
    """A raw directory as actions/cache restores it: the file and its download record with
    the validators the publisher gave."""
    d = tmp_path / "raw" / "src"
    d.mkdir(parents=True)
    dest = d / "f.csv"
    dest.write_bytes(GOOD)
    rec = acquire.DownloadRecord(
        "f.csv",
        URL,
        "2026-01-01T00:00:00+00:00",
        len(GOOD),
        acquire.sha256_of(dest),
        200,
        '"etag1"',
        "Mon, 01 Jan 2024 00:00:00 GMT",
        "text/csv",
    )
    acquire.write_records(d, {"f.csv": rec})
    return dest, rec


@pytest.fixture(autouse=True)
def _no_pause(monkeypatch):
    monkeypatch.setattr(acquire.time, "sleep", lambda s: None)
    acquire.reset_outcomes()


def test_304_keeps_the_cached_file_and_sends_the_validators(tmp_path, stub_http) -> None:
    dest, rec = _restored_cache(tmp_path)
    sess = stub_http(304)
    out = acquire.fetch(URL, dest, refresh=True, session=sess)
    assert out.status == "not_modified" and out.record == rec
    assert dest.read_bytes() == GOOD and acquire.read_records(dest.parent)["f.csv"] == rec
    sent = sess.calls[0]["headers"]
    assert sent["If-None-Match"] == '"etag1"' and "If-Modified-Since" in sent


@pytest.mark.parametrize(
    "status, body, headers",
    [
        (200, b"", {"Content-Type": "text/csv"}),
        (200, b"   \n\n", {"Content-Type": "text/csv"}),
        (200, b"a,b\n", {"Content-Type": "text/csv"}),
        (200, b'{"status":"Pending","itemId":"x"}', {"Content-Type": "application/json"}),
        (200, b"<html><body>503</body></html>", {"Content-Type": "text/html"}),
        (202, b'{"status":"Pending"}', {"Content-Type": "application/json"}),
        (204, b"", {}),
        (429, b"slow down", {}),
        (503, b"<html>error</html>", {}),
    ],
)
def test_unusable_responses_never_replace_a_good_cached_file(
    tmp_path, stub_http, status, body, headers
) -> None:
    dest, rec = _restored_cache(tmp_path)
    out = acquire.fetch(URL, dest, refresh=True, session=stub_http(status, body, headers))
    assert out.status == "kept_cached", out
    assert out.record == rec and dest.read_bytes() == GOOD
    assert acquire.read_records(dest.parent)["f.csv"] == rec
    assert not list(dest.parent.glob("*.part")), "a partial download was left behind"
    assert acquire.outcome_for(dest) == out


def test_a_good_body_replaces_the_cached_file_and_records_it(tmp_path, stub_http) -> None:
    dest, rec = _restored_cache(tmp_path)
    new = b"\xef\xbb\xbfa,b\n1,2\n3,4\n"
    out = acquire.fetch(
        URL,
        dest,
        refresh=True,
        session=stub_http(
            200, new, {"ETag": '"etag2"', "Content-Type": "application/octet-stream"}
        ),
    )
    assert out.status == "downloaded" and dest.read_bytes() == new
    after = acquire.read_records(dest.parent)["f.csv"]
    assert after.etag == '"etag2"' and after.bytes == len(new) and after.body_problem is None
    assert after.sha256 != rec.sha256


def test_without_refresh_a_cached_file_costs_no_request(tmp_path, stub_http) -> None:
    dest, rec = _restored_cache(tmp_path)
    sess = stub_http(200, b"x,y\n1,2\n")
    out = acquire.fetch(URL, dest, refresh=False, session=sess)
    assert out.status == "cached" and out.record == rec and not sess.calls


def test_error_status_without_a_cached_file_raises(tmp_path, stub_http) -> None:
    dest = tmp_path / "raw" / "src" / "f.csv"
    with pytest.raises(requests.HTTPError):
        acquire.fetch(URL, dest, refresh=True, session=stub_http(503, b"err"))
    assert (
        not dest.exists() and not list(dest.parent.glob("*.part")) if dest.parent.exists() else True
    )


def test_a_bad_body_with_no_cached_file_is_written_and_flagged(tmp_path, stub_http) -> None:
    """Nothing good to keep: the body is written so the landing step can quarantine it, the
    record says why, and the next refresh sends no validators that could pin it with a 304."""
    dest = tmp_path / "raw" / "src" / "f.csv"
    out = acquire.fetch(URL, dest, refresh=True, session=stub_http(200, b"a,b\n", {"ETag": '"e"'}))
    assert out.status == "downloaded_suspect" and dest.read_bytes() == b"a,b\n"
    rec = acquire.read_records(dest.parent)["f.csv"]
    assert rec.body_problem and rec.body_problem.startswith("header_only_body")
    sess = stub_http(200, GOOD, {"ETag": '"e2"'})
    out2 = acquire.fetch(URL, dest, refresh=False, session=sess)
    assert "If-None-Match" not in sess.calls[0]["headers"], "a suspect file must not be pinned"
    assert out2.status == "downloaded" and dest.read_bytes() == GOOD
    assert acquire.read_records(dest.parent)["f.csv"].body_problem is None


def test_body_problem_judges_the_sample_not_the_content_type(tmp_path) -> None:
    p = tmp_path / "b.csv"
    p.write_bytes(b"")
    assert acquire.body_problem(p).startswith("empty_body")
    p.write_bytes(b"\xef\xbb\xbfh1,h2\n")
    assert acquire.body_problem(p).startswith("header_only_body")
    p.write_bytes(b'  [{"a": 1}]')
    assert acquire.body_problem(p).startswith("non_csv_body")
    p.write_bytes(b"<!DOCTYPE html><html></html>")
    assert acquire.body_problem(p).startswith("non_csv_body")
    p.write_bytes(b"h1,h2\n1,2\n")
    assert acquire.body_problem(p) is None
    # a large file whose header alone exceeds the sample is still accepted
    p.write_bytes(b"h1,h2\n" + b"1,2\n" * 40_000)
    assert acquire.body_problem(p) is None


def test_old_download_records_without_body_problem_still_load(tmp_path) -> None:
    d = tmp_path / "src"
    d.mkdir()
    (d / acquire.RECORD_NAME).write_text(
        '{"f.csv": {"file_name": "f.csv", "url": "u", "retrieved_at": "t", "bytes": 1, '
        '"sha256": "s", "status": 200, "etag": null, "last_modified": null, "content_type": null}}'
    )
    assert acquire.read_records(d)["f.csv"].body_problem is None
