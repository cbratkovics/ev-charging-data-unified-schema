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
