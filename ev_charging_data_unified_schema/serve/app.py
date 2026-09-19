"""FastAPI application serving committed artifacts and exported gold marts.

Startup reads ``artifacts/manifest.json`` and loads the champion pipelines per cohort, every
predictions file, and every registered evaluation artifact; it fails fast with a clear error
when the manifest is missing. No database, cache, auth, or model in the request path.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from ev_charging_data_unified_schema import __version__
from ev_charging_data_unified_schema.config import ARTIFACTS_DIR, ENV_PREFIX, PROJECT, cors_origins
from ev_charging_data_unified_schema.models import registry
from ev_charging_data_unified_schema.serve import marts, schemas

log = logging.getLogger("ev_charging_data_unified_schema.serve")
DEFAULT_ORIGINS = cors_origins()
MART_SOURCE = "gold marts exported by the scheduled build"


class State:
    manifest: dict[str, Any]
    model_version: str
    candidate: str | dict[str, str]
    metadata: dict[str, Any]
    pipelines: dict[str, Any]
    evaluations: dict[str, dict[str, Any]]
    predictions: dict[tuple[int, int], dict[str, Any]]
    marts: marts.MartStore | None
    loaded_at_utc: str


def load_state(artifacts: Path = ARTIFACTS_DIR) -> State:
    manifest = registry.read_manifest(artifacts / "manifest.json")
    s = State()
    s.manifest = manifest
    s.model_version, s.candidate = registry.slot(manifest, "champion")
    s.metadata = registry.read_model_metadata(s.model_version, artifacts)
    s.pipelines = registry.load_pipelines(s.model_version, s.candidate, artifacts)
    s.evaluations = {}
    for entry in registry.evaluations(manifest):
        p = artifacts / entry["path"]
        if p.exists():
            art = json.loads(p.read_text(encoding="utf-8"))
            art.setdefault("kind", entry.get("kind", "frozen_test"))
            art.setdefault("season", entry.get("season"))
            s.evaluations[entry["eval_id"]] = art
    s.predictions = {}
    pdir = artifacts / "predictions"
    if pdir.exists():
        for f in sorted(pdir.glob("*/period_*.json")):
            payload = json.loads(f.read_text(encoding="utf-8"))
            s.predictions[(int(payload["season"]), int(payload["period"]))] = payload
    s.marts = marts.load_marts(artifacts / "marts")
    s.loaded_at_utc = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    return s


@asynccontextmanager
async def lifespan(app: FastAPI):
    artifacts = Path(os.environ.get(ENV_PREFIX + "ARTIFACTS_DIR", ARTIFACTS_DIR))
    try:
        app.state.s = load_state(artifacts)
    except FileNotFoundError as exc:
        raise RuntimeError(f"cannot start: {exc}") from exc
    st: State = app.state.s
    log.info(
        "loaded model %s evaluations=%s predictions=%d marts=%s",
        st.model_version,
        list(st.evaluations),
        len(st.predictions),
        bool(st.marts),
    )
    yield


app = FastAPI(
    title="Ev Charging Data Unified Schema API",
    version=__version__,
    description="Consolidates five messy partner feeds into one tested dbt schema on DuckDB. Every response names its model and feature version.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get(ENV_PREFIX + "CORS_ORIGINS", ",".join(DEFAULT_ORIGINS)).split(","),
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _state() -> State:
    return app.state.s


@app.get("/", response_model=schemas.Root)
def root() -> schemas.Root:
    return schemas.Root(
        name="Ev Charging Data Unified Schema API",
        version=__version__,
        docs="/docs",
        health="/health",
        performance="/performance",
        manifest="/manifest",
        marts="/marts/fct_period_eval" if _state().marts else None,
    )


@app.get("/health", response_model=schemas.Health)
def health() -> schemas.Health:
    s = _state()
    return schemas.Health(
        status="ok",
        model_version=s.model_version,
        feature_version=s.metadata["feature_version"],
        eval_id=s.manifest.get("eval_id"),
        evaluations=list(s.evaluations),
        data_through=s.manifest.get("data_through", s.metadata["data_through"]),
        loaded_at_utc=s.loaded_at_utc,
        cohorts_loaded=sorted(s.pipelines),
        marts_exported_at_utc=s.marts.export["exported_at_utc"] if s.marts else None,
    )


@app.get("/manifest", response_model=schemas.ManifestResponse)
def manifest() -> schemas.ManifestResponse:
    return schemas.ManifestResponse(manifest=_state().manifest)


@app.get("/predictions/{season}/{period}", response_model=schemas.PredictionsResponse)
def predictions(
    season: int, period: int, cohort: Annotated[str | None, Query()] = None
) -> schemas.PredictionsResponse:
    s = _state()
    payload = s.predictions.get((season, period))
    if payload is None:
        raise HTTPException(
            404,
            f"no predictions for {season} {PROJECT.period_name} {period}; available: {sorted(s.predictions)}",
        )
    if cohort is not None and cohort not in PROJECT.cohorts:
        raise HTTPException(422, f"{PROJECT.cohort_name} must be one of {PROJECT.cohorts}")
    out = [
        schemas.PredictionRecord(
            entity_id=r[PROJECT.entity_key],
            name=r.get("name"),
            team=r.get("team"),
            cohort=r[PROJECT.cohort_name],
            prediction=r["prediction"],
            floor=r["floor"],
            ceiling=r["ceiling"],
            model_version=payload["model_version"],
            candidate=r["candidate"],
            actual=r.get("actual"),
        )
        for r in payload["predictions"]
        if cohort is None or r[PROJECT.cohort_name] == cohort
    ]
    return schemas.PredictionsResponse(
        season=season,
        period=period,
        interval_method=payload["interval_method"],
        model_version=payload["model_version"],
        feature_version=payload["feature_version"],
        generated_at_utc=payload["generated_at_utc"],
        data_through=payload["data_through"],
        n=len(out),
        predictions=out,
    )


@app.get("/performance", response_model=schemas.EvaluationsResponse)
def performance() -> schemas.EvaluationsResponse:
    """Every registered evaluation artifact, verbatim."""
    s = _state()
    if not s.evaluations:
        raise HTTPException(404, "no evaluation artifact in manifest")
    return schemas.EvaluationsResponse(
        model_version=s.model_version,
        feature_version=s.metadata["feature_version"],
        evaluations=list(s.evaluations.values()),
    )


@app.get("/performance/{eval_id}")
def performance_one(eval_id: str) -> dict[str, Any]:
    art = _state().evaluations.get(eval_id)
    if art is None:
        raise HTTPException(
            404, f"unknown eval_id {eval_id!r}; known: {list(_state().evaluations)}"
        )
    return art


@app.get("/marts/{mart}", response_model=schemas.MartResponse)
def mart(
    mart: str, request: Request, limit: Annotated[int, Query(ge=1, le=20000)] = 5000
) -> schemas.MartResponse:
    """Rows of one exported gold mart, with equality filters on the columns marts.SERVABLE allows
    (e.g. /marts/fct_period_eval?cohort=ALL&season=2023). Versioned marts are read at the pinned version.
    """
    m = _state().marts
    if m is None:
        raise HTTPException(
            404,
            "no gold marts exported (artifacts/marts/); run the scheduled build or make dbt-export",
        )
    filters = {k: v for k, v in request.query_params.items() if k != "limit"}
    try:
        rows = m.query(mart, filters, limit=limit)
    except KeyError as exc:
        raise HTTPException(422, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return schemas.MartResponse(
        source=MART_SOURCE,
        mart=mart,
        version=marts.DECISIONS_MART_VERSION if mart in marts.MART_VERSIONS else None,
        export=schemas.MartExport(**m.export),
        n=len(rows),
        rows=rows,
    )
