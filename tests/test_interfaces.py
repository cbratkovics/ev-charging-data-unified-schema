"""The seams are satisfied by this project's implementations, and every committed artifact
validates against its JSON Schema under artifacts/schemas/."""

from __future__ import annotations

import json

import jsonschema
import numpy as np
import pandas as pd
import pytest

from ev_charging_data_unified_schema import interfaces, target
from ev_charging_data_unified_schema.config import ARTIFACTS_DIR, PROJECT, SCHEMAS_DIR
from ev_charging_data_unified_schema.data import loader
from ev_charging_data_unified_schema.eval import drift
from ev_charging_data_unified_schema.features import asof

SCHEMAS = {p.stem.removesuffix(".schema"): p for p in SCHEMAS_DIR.glob("*.schema.json")}


def _schema(name: str) -> dict:
    return json.loads(SCHEMAS[name].read_text(encoding="utf-8"))


def test_every_schema_is_itself_valid() -> None:
    assert set(SCHEMAS) == {
        "eval_artifact",
        "manifest",
        "model_metadata",
        "predictions_file",
        "drift_report",
    }
    for name in SCHEMAS:
        jsonschema.Draft202012Validator.check_schema(_schema(name))


def test_loader_satisfies_source_loader() -> None:
    assert isinstance(loader.LOADER, interfaces.SourceLoader)
    assert PROJECT.entity_key in loader.ID_COLUMNS and PROJECT.target_column in loader.STAT_COLUMNS


def test_target_spec_derives_and_reconciles(rows: pd.DataFrame) -> None:
    spec = target.TARGET_SPEC
    assert isinstance(spec, interfaces.TargetSpec)
    np.testing.assert_allclose(
        spec.derive(rows).to_numpy(), rows[spec.column].to_numpy(), atol=0.01
    )
    assert spec.reconcile(rows).empty


def test_asof_satisfies_feature_module() -> None:
    assert isinstance(asof, interfaces.FeatureModule)
    assert tuple(asof.KEY_COLUMNS) == PROJECT.grain


@pytest.mark.parametrize("path", sorted((ARTIFACTS_DIR / "eval").glob("eval-*.json")))
def test_committed_eval_artifacts_validate(path) -> None:
    jsonschema.validate(json.loads(path.read_text(encoding="utf-8")), _schema("eval_artifact"))


def test_committed_manifest_validates() -> None:
    p = ARTIFACTS_DIR / "manifest.json"
    if not p.exists():
        pytest.skip("no manifest yet")
    jsonschema.validate(json.loads(p.read_text()), _schema("manifest"))


@pytest.mark.parametrize("path", sorted((ARTIFACTS_DIR / "models").glob("*/metadata.json")))
def test_committed_model_metadata_validates(path) -> None:
    jsonschema.validate(json.loads(path.read_text(encoding="utf-8")), _schema("model_metadata"))


@pytest.mark.parametrize("path", sorted((ARTIFACTS_DIR / "predictions").glob("*/period_*.json")))
def test_committed_prediction_files_validate(path) -> None:
    jsonschema.validate(json.loads(path.read_text(encoding="utf-8")), _schema("predictions_file"))


def test_drift_run_report_matches_its_schema() -> None:
    rng = np.random.default_rng(0)
    ref = {"f1": [float(x) for x in np.quantile(rng.normal(size=500), np.linspace(0, 1, 11))]}
    report = drift.drift_report(pd.DataFrame({"f1": rng.normal(size=200)}), ref, ["f1"])
    schema = _schema("drift_report")
    jsonschema.validate(report, {"$ref": "#/$defs/cohort_report", "$defs": schema["$defs"]})
    run = drift.run_report(
        run_id="run-20260101T000000Z",
        at_utc="2026-01-01T00:00:00+00:00",
        season=2026,
        period=2,
        model_version="m",
        status=report["status"],
        positions={PROJECT.cohorts[0]: report},
    )
    jsonschema.validate(run, schema)


@pytest.mark.parametrize("path", sorted((ARTIFACTS_DIR / "drift").glob("run-*.json")))
def test_committed_drift_reports_validate(path) -> None:
    jsonschema.validate(json.loads(path.read_text(encoding="utf-8")), _schema("drift_report"))
