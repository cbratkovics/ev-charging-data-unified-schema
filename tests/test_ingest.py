"""The loaders read the fixture files as strings, and ingest lands them idempotently
(docs/BRIEF.md § 5: re-running with unchanged files is a no-op)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from ev_charging_data_unified_schema import ingest
from ev_charging_data_unified_schema.config import META_COLUMNS, PROJECT
from ev_charging_data_unified_schema.data import loader as landing
from ev_charging_data_unified_schema.data.contracts import CONTRACTS
from ev_charging_data_unified_schema.sources import LOADERS

RAW = Path(__file__).parent / "fixtures" / "raw"


@pytest.mark.parametrize("name", PROJECT.source_names)
def test_loader_reads_fixture_files_as_strings_with_published_headers(name) -> None:
    loader_ = LOADERS[name]
    files = sorted((RAW / name).glob("*.csv"))
    assert files, name
    for path in files:
        frame = loader_.read_raw(path)
        assert all(str(d) == "string" for d in frame.dtypes), path.name
        fam = CONTRACTS[name].family_for(path.name)
        assert fam is not None, path.name
        # required columns present (after aliasing) and nothing lost
        renamed = frame.rename(columns=fam.aliases)
        assert fam.required_names() <= set(renamed.columns), path.name


def test_cary_and_boulder_boms_are_stripped_and_na_tokens_kept_raw() -> None:
    cary = LOADERS["cary"].read_raw(RAW / "cary" / "electric-vehicle-charging-stations.csv")
    assert cary.columns[0] == "start_date"
    dft = LOADERS["dft_2017"].read_raw(RAW / "dft_2017" / "dft_2017_public_sector_fasts_raw.csv")
    assert dft.columns[0] == "publisher_row_index" and (dft["ChargingEvent"] == "NA").any()


def _run(tmp_path: Path, landed: Path) -> dict:
    drift_dir = tmp_path / "drift"
    assert (
        ingest.main(
            [
                "--no-download",
                "--raw-dir",
                str(RAW),
                "--landed-dir",
                str(landed),
                "--drift-dir",
                str(drift_dir),
            ]
        )
        == 0
    )
    latest = json.loads((drift_dir / "latest.json").read_text())
    return json.loads((drift_dir / latest["path"]).read_text())


def test_ingest_lands_every_fixture_file_and_is_a_noop_on_rerun(tmp_path) -> None:
    landed = tmp_path / "landed"
    art = _run(tmp_path, landed)
    assert art["summary"]["by_outcome"]["quarantine"] == 0, art["summary"]
    manifest = landing.read_manifest(landed)
    assert len(manifest) == sum(len(list((RAW / n).glob("*.csv"))) for n in PROJECT.source_names)
    parquet = sorted(p for p in landed.rglob("*.parquet"))
    assert len(parquet) == len(manifest)
    stamps = {p: p.stat().st_mtime_ns for p in parquet}
    manifest_text = (landed / "manifest.json").read_text()
    art2 = _run(tmp_path, landed)
    assert {p: p.stat().st_mtime_ns for p in parquet} == stamps, "re-run rewrote a landed file"
    assert (landed / "manifest.json").read_text() == manifest_text
    assert art2["ingest"]["sources"]["boulder"]["files_landed"] == 0
    for entry in manifest.values():
        frame = pd.read_parquet(
            landed.parent.parent / entry.landed_path
            if not Path(entry.landed_path).is_absolute()
            else entry.landed_path
        )
        assert set(META_COLUMNS) <= set(frame.columns) and len(frame) == entry.row_count


def test_changed_file_is_relanded_and_a_broken_file_is_quarantined(tmp_path) -> None:
    raw = tmp_path / "raw"
    for name in PROJECT.source_names:
        (raw / name).mkdir(parents=True)
        for p in (RAW / name).glob("*.csv"):
            (raw / name / p.name).write_bytes(p.read_bytes())
    landed = tmp_path / "landed"
    drift_dir = tmp_path / "drift"
    ingest.main(
        [
            "--no-download",
            "--raw-dir",
            str(raw),
            "--landed-dir",
            str(landed),
            "--drift-dir",
            str(drift_dir),
        ]
    )
    before = landing.read_manifest(landed)["cary/electric-vehicle-charging-stations.csv"].sha256
    target = raw / "cary" / "electric-vehicle-charging-stations.csv"
    # append a row: sha changes, contract still satisfied -> re-landed
    target.write_bytes(
        target.read_bytes()
        + b"2023-01-01T00:00:00+00:00,TOWN OF CARY / FIXTURE A,00:05:00,0.4,1 Fixture St,,Cary,North Carolina,27511\n"
    )
    ingest.main(
        [
            "--no-download",
            "--raw-dir",
            str(raw),
            "--landed-dir",
            str(landed),
            "--drift-dir",
            str(drift_dir),
        ]
    )
    after = landing.read_manifest(landed)["cary/electric-vehicle-charging-stations.csv"]
    assert after.sha256 != before and after.row_count == 7
    # drop a required column: quarantined, landed aside, run continues, other sources untouched
    text = target.read_text(encoding="utf-8-sig").splitlines()
    text[0] = text[0].replace("energy_kwh", "energy_kwh_renamed")
    target.write_text("\n".join(text) + "\n", encoding="utf-8")
    ingest.main(
        [
            "--no-download",
            "--raw-dir",
            str(raw),
            "--landed-dir",
            str(landed),
            "--drift-dir",
            str(drift_dir),
        ]
    )
    latest = json.loads((drift_dir / "latest.json").read_text())
    art = json.loads((drift_dir / latest["path"]).read_text())
    assert art["summary"]["quarantined_files"] == ["cary/electric-vehicle-charging-stations.csv"]
    entry = landing.read_manifest(landed)["cary/electric-vehicle-charging-stations.csv"]
    assert "_quarantined" in entry.landed_path
    assert not (landed / "cary" / "electric-vehicle-charging-stations.parquet").exists()
    assert (landed / "boulder").glob("*.parquet")
    cary_file = next(f for f in art["files"] if f["source"] == "cary")
    assert cary_file["reason_codes"] == ["missing_required"]
    assert any(
        x["code"] == "unknown_column" and x["column"] == "energy_kwh_renamed"
        for x in cary_file["findings"]
    )


# --- the refresh path against a restored cache, offline (ADR-0015, amendment of 2026-09-20) ---


def _restored_cache(tmp_path: Path) -> tuple[Path, Path, Path]:
    """What the runner has after actions/cache: raw files with download records carrying
    validators, and a landed directory with a manifest. Returns (raw, landed, drift_dir)."""
    from ev_charging_data_unified_schema import acquire

    raw = tmp_path / "raw"
    for name in PROJECT.source_names:
        (raw / name).mkdir(parents=True)
        records = {}
        for p in (RAW / name).glob("*.csv"):
            dest = raw / name / p.name
            dest.write_bytes(p.read_bytes())
            records[p.name] = acquire.DownloadRecord(
                p.name,
                f"https://example.invalid/{name}/{p.name}",
                "2026-01-01T00:00:00+00:00",
                dest.stat().st_size,
                acquire.sha256_of(dest),
                200,
                f'"{p.stem}"',
                "Mon, 01 Jan 2024 00:00:00 GMT",
                "text/csv",
            )
        acquire.write_records(raw / name, records)
    landed, drift_dir = tmp_path / "landed", tmp_path / "drift"
    _ingest(raw, landed, drift_dir, "--no-download")
    return raw, landed, drift_dir


def _ingest(raw: Path, landed: Path, drift_dir: Path, *extra: str) -> dict:
    args = ["--raw-dir", str(raw), "--landed-dir", str(landed), "--drift-dir", str(drift_dir)]
    assert ingest.main([*args, *extra]) == 0
    latest = json.loads((drift_dir / "latest.json").read_text())
    return json.loads((drift_dir / latest["path"]).read_text())


def _snapshot(landed: Path) -> tuple[dict, str]:
    parquet = sorted(landed.rglob("*.parquet"))
    return {p: p.stat().st_mtime_ns for p in parquet}, (landed / "manifest.json").read_text()


def _drift_for(art: dict, source: str, file_name: str) -> dict:
    return next(f for f in art["files"] if f["source"] == source and f["file_name"] == file_name)


@pytest.fixture(autouse=True)
def _no_pause(monkeypatch):
    from ev_charging_data_unified_schema import acquire

    monkeypatch.setattr(acquire.time, "sleep", lambda s: None)
    acquire.reset_outcomes()


def test_refresh_with_304_is_a_noop_that_the_drift_artifact_explains(tmp_path, stub_http) -> None:
    raw, landed, drift_dir = _restored_cache(tmp_path)
    before = _snapshot(landed)
    sess = stub_http(304)
    art = _ingest(raw, landed, drift_dir, "--refresh")
    assert len(sess.calls) == sum(len(list((RAW / n).glob("*.csv"))) for n in PROJECT.source_names)
    assert all("If-None-Match" in c["headers"] for c in sess.calls)
    assert _snapshot(landed) == before, "a 304 must not touch the landed files or the manifest"
    assert art["summary"]["by_outcome"]["quarantine"] == 0
    assert all(f["files_landed"] == 0 for f in art["ingest"]["sources"].values())
    cary = _drift_for(art, "cary", "electric-vehicle-charging-stations.csv")
    assert any(
        x["code"] == "refresh_kept_cached" and "304" in x["detail"] for x in cary["findings"]
    )


@pytest.mark.parametrize(
    "status, body",
    [(200, b""), (200, b"a,b\n"), (202, b'{"status":"Pending","itemId":"x"}'), (503, b"<html>")],
    ids=["empty-body", "header-only", "202-json", "503"],
)
def test_refresh_with_an_unusable_response_keeps_every_good_file(
    tmp_path, stub_http, status, body
) -> None:
    raw, landed, drift_dir = _restored_cache(tmp_path)
    before = _snapshot(landed)
    raw_before = {p: p.read_bytes() for p in raw.rglob("*.csv")}
    stub_http(status, body, {"Content-Type": "text/csv"})
    art = _ingest(raw, landed, drift_dir, "--refresh")
    assert {p: p.read_bytes() for p in raw.rglob("*.csv")} == raw_before, "raw file replaced"
    assert _snapshot(landed) == before
    assert art["summary"]["by_outcome"]["quarantine"] == 0
    boulder = _drift_for(art, "boulder", "Electric_Vehicle_Charging_Station_Data.csv")
    assert boulder["outcome"] == "info"
    assert any(x["code"] == "refresh_kept_cached" for x in boulder["findings"])


def test_a_header_only_raw_file_is_quarantined_and_the_last_good_landed_file_is_kept(
    tmp_path,
) -> None:
    """The landing layer on its own: the raw file on disk has a header and no rows (the shape
    that crashed full-build #3). The file is quarantined as empty_file, the previous landed
    parquet and its manifest entry stay, the other sources land, and the run continues."""
    raw, landed, drift_dir = _restored_cache(tmp_path)
    before = _snapshot(landed)
    target = raw / "cary" / "electric-vehicle-charging-stations.csv"
    header = target.read_text(encoding="utf-8-sig").splitlines()[0]
    target.write_text(header + "\n", encoding="utf-8")
    art = _ingest(raw, landed, drift_dir, "--no-download")
    assert _snapshot(landed) == before, "the last good landed file must be kept"
    assert art["summary"]["quarantined_files"] == ["cary/electric-vehicle-charging-stations.csv"]
    cary = _drift_for(art, "cary", "electric-vehicle-charging-stations.csv")
    assert cary["reason_codes"] == ["empty_file"] and cary["rows"] == 0
    assert any(x["code"] == "last_good_kept" for x in cary["findings"])
    assert not (landed / "cary" / "_quarantined").exists()
    entry = landing.read_manifest(landed)["cary/electric-vehicle-charging-stations.csv"]
    assert entry.row_count == 6 and "_quarantined" not in entry.landed_path
    # the good file comes back: re-landed in place, no quarantine left behind
    target.write_bytes((RAW / "cary" / target.name).read_bytes())
    art = _ingest(raw, landed, drift_dir, "--no-download")
    assert art["summary"]["by_outcome"]["quarantine"] == 0
    assert art["ingest"]["sources"]["cary"]["files_landed"] == 0, "same bytes as landed: a no-op"


def test_an_unreadable_raw_file_is_quarantined_and_the_last_good_landed_file_is_kept(
    tmp_path,
) -> None:
    raw, landed, drift_dir = _restored_cache(tmp_path)
    before = _snapshot(landed)
    target = raw / "boulder" / "Electric_Vehicle_Charging_Station_Data.csv"
    target.write_bytes(b"")
    art = _ingest(raw, landed, drift_dir, "--no-download")
    assert _snapshot(landed) == before
    boulder = _drift_for(art, "boulder", target.name)
    assert boulder["outcome"] == "quarantine" and boulder["reason_codes"] == ["unreadable_file"]
    assert any("last good landed file kept" in x["detail"] for x in boulder["findings"])
    assert art["ingest"]["sources"]["dft_2017"]["files_seen"] == 4, "the run continued"


def test_an_empty_first_delivery_lands_aside_and_an_unreadable_one_lands_nothing(
    tmp_path,
) -> None:
    """No good landed file to keep: an empty file lands its zero rows under _quarantined/ (the
    empty-frame hash path), an unreadable one lands nothing and gets no manifest entry."""
    raw = tmp_path / "raw"
    for name in PROJECT.source_names:
        (raw / name).mkdir(parents=True)
        for p in (RAW / name).glob("*.csv"):
            (raw / name / p.name).write_bytes(p.read_bytes())
    cary = raw / "cary" / "electric-vehicle-charging-stations.csv"
    cary.write_text(cary.read_text(encoding="utf-8-sig").splitlines()[0] + "\n", encoding="utf-8")
    (raw / "boulder" / "Electric_Vehicle_Charging_Station_Data.csv").write_bytes(b"")
    landed, drift_dir = tmp_path / "landed", tmp_path / "drift"
    art = _ingest(raw, landed, drift_dir, "--no-download")
    assert sorted(art["summary"]["quarantined_files"]) == [
        "boulder/Electric_Vehicle_Charging_Station_Data.csv",
        "cary/electric-vehicle-charging-stations.csv",
    ]
    manifest = landing.read_manifest(landed)
    assert "boulder/Electric_Vehicle_Charging_Station_Data.csv" not in manifest
    entry = manifest["cary/electric-vehicle-charging-stations.csv"]
    assert entry.row_count == 0 and "_quarantined" in entry.landed_path
    aside = pd.read_parquet(
        landed / "cary" / "_quarantined" / "electric-vehicle-charging-stations.parquet"
    )
    assert len(aside) == 0 and set(META_COLUMNS) <= set(aside.columns)
    assert len(list((landed / "dft_2017").glob("*.parquet"))) == 4


def test_a_landing_failure_names_the_file(tmp_path, monkeypatch) -> None:
    raw, landed, drift_dir = _restored_cache(tmp_path)
    (raw / "cary" / "electric-vehicle-charging-stations.csv").write_bytes(b"x,y\n1,2\n")

    def boom(*a, **k):
        raise RuntimeError("simulated")

    monkeypatch.setattr(ingest.landing, "write_landed", boom)
    with pytest.raises(RuntimeError) as info:
        _ingest(raw, landed, drift_dir, "--no-download", "--sources", "cary")
    assert any("cary/electric-vehicle-charging-stations.csv" in n for n in info.value.__notes__)
