"""Pydantic v2 response models. Every payload carries model/feature versions and timestamps."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

EvalKind = Literal["frozen_test", "out_of_sample_season"]


class Root(BaseModel):
    name: str
    version: str
    docs: str
    health: str
    performance: str
    manifest: str
    marts: str | None = Field(default=None, description="gold marts index, when exported")


class Health(BaseModel):
    status: Literal["ok"]
    model_version: str
    feature_version: str
    eval_id: str | None
    evaluations: list[str] = Field(default_factory=list)
    data_through: dict[str, int]
    loaded_at_utc: str
    cohorts_loaded: list[str]
    marts_exported_at_utc: str | None = None


class PredictionRecord(BaseModel):
    entity_id: str
    name: str | None
    team: str | None
    cohort: str
    prediction: float
    floor: float
    ceiling: float
    model_version: str
    candidate: str
    actual: float | None = None


class PredictionsResponse(BaseModel):
    season: int
    period: int
    interval_method: str
    model_version: str
    feature_version: str
    generated_at_utc: str
    data_through: dict[str, int]
    n: int
    predictions: list[PredictionRecord]


class ManifestResponse(BaseModel):
    manifest: dict[str, Any]


class EvaluationsResponse(BaseModel):
    model_version: str
    feature_version: str
    evaluations: list[dict[str, Any]]


class MartExport(BaseModel):
    exported_at_utc: str | None
    target: str | None
    invocation_id: str | None
    code_commit: str | None
    row_counts: dict[str, int]


class MartResponse(BaseModel):
    source: Literal["gold marts exported by the scheduled build"]
    mart: str
    version: int | None = Field(default=None, description="mart version when the mart is versioned")
    export: MartExport
    n: int
    rows: list[dict[str, Any]]
