"""Score an upcoming period with the champion (or challenger) models.

``score_period`` builds as-of features for every eligible entity as of the end of the last
completed period, predicts per cohort, and returns a JSON-serialisable record the scheduled job
writes to ``artifacts/predictions/<season>/period_<pp>.json``
(``artifacts/schemas/predictions_file.schema.json``). Eligible entities: any entity with a row in
``season`` or ``season - 1`` and at least one prior row overall.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ev_charging_data_unified_schema.config import ARTIFACTS_DIR, PROJECT
from ev_charging_data_unified_schema.features import asof
from ev_charging_data_unified_schema.models import registry

PREDICTIONS_VERSION = "1.0"
_ENTITY, _SEASON, _PERIOD, _COHORT = (
    PROJECT.entity_key,
    PROJECT.season_name,
    PROJECT.period_name,
    PROJECT.cohort_name,
)


def predictions_path(season: int, period: int, artifacts: Path = ARTIFACTS_DIR) -> Path:
    return (
        artifacts / "predictions" / str(season) / f"period_{period:0{PROJECT.period_width}d}.json"
    )


def eligible_targets(rows: pd.DataFrame, season: int, period: int) -> pd.DataFrame:
    recent = rows[rows[_SEASON].isin([season - 1, season]) & rows[_COHORT].isin(PROJECT.cohorts)]
    last = recent.sort_values([_SEASON, _PERIOD]).groupby(_ENTITY, sort=False).last()
    return pd.DataFrame(
        {
            _ENTITY: last.index,
            _SEASON: season,
            _PERIOD: period,
            _COHORT: last[_COHORT].to_numpy(),
            "team": last["team"].to_numpy(),
            PROJECT.entity_display_column: last[PROJECT.entity_display_column].to_numpy(),
        }
    )


def score_period(
    rows: pd.DataFrame,
    season: int,
    period: int,
    *,
    model_version: str,
    candidate: str | dict[str, str],
    artifacts: Path = ARTIFACTS_DIR,
    pipelines: dict[str, Any] | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    now = now or dt.datetime.now(dt.UTC)
    prior = rows[(rows[_SEASON] < season) | ((rows[_SEASON] == season) & (rows[_PERIOD] < period))]
    if prior.empty:
        raise ValueError("no rows before the requested period")
    meta = registry.read_model_metadata(model_version, artifacts)
    pipelines = pipelines or registry.load_pipelines(model_version, candidate, artifacts)
    feats = asof.build_features(prior, targets=eligible_targets(prior, season, period))
    stubs = feats[feats[asof.TARGET_FLAG] & feats[asof.HISTORY_FLAG]]
    records: list[dict[str, Any]] = []
    for cohort in PROJECT.cohorts:
        sub = stubs[stubs[_COHORT] == cohort]
        if sub.empty:
            continue
        cand = registry.candidate_for(candidate, cohort)
        pred = pipelines[cohort].predict(sub[asof.features_for_cohort(cohort)])
        q10, q90 = meta["cohorts"][cohort]["candidates"][cand]["residual_quantiles"]["values"]
        for i, r in enumerate(sub.to_dict("records")):
            p = float(pred[i])
            records.append(
                {
                    PROJECT.entity_key: r[_ENTITY],
                    "name": r[PROJECT.entity_display_column],
                    "team": r["team"],
                    PROJECT.cohort_name: cohort,
                    "prediction": round(p, 2),
                    "floor": round(max(0.0, p + q10), 2),
                    "ceiling": round(p + q90, 2),
                    "candidate": cand,
                }
            )
    records.sort(key=lambda r: (-r["prediction"], r[PROJECT.entity_key]))
    data_through = prior.sort_values([_SEASON, _PERIOD]).iloc[-1]
    return {
        "predictions_version": PREDICTIONS_VERSION,
        "season": int(season),
        "period": int(period),
        "model_version": model_version,
        "feature_version": meta["feature_version"],
        "candidate": candidate,
        "generated_at_utc": now.isoformat(timespec="seconds"),
        "data_through": {
            "season": int(data_through[_SEASON]),
            "period": int(data_through[_PERIOD]),
        },
        "interval_method": meta["interval_method"],
        "n": len(records),
        "predictions": records,
    }


def write_predictions(payload: dict[str, Any], artifacts: Path = ARTIFACTS_DIR) -> Path:
    path = predictions_path(payload["season"], payload["period"], artifacts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    return path


def attach_actuals(payload: dict[str, Any], rows: pd.DataFrame) -> tuple[dict[str, Any], int]:
    """Add ``actual`` to each record once the period has been played; entities without a row
    keep ``actual: null``."""
    wk = rows[(rows[_SEASON] == payload["season"]) & (rows[_PERIOD] == payload["period"])]
    actual = wk.set_index(_ENTITY)[PROJECT.target_column]
    n = 0
    for rec in payload["predictions"]:
        v = actual.get(rec[PROJECT.entity_key])
        if v is not None and not (isinstance(v, float) and np.isnan(v)):
            rec["actual"] = round(float(v), 2)
            n += 1
        else:
            rec.setdefault("actual", None)
    payload["actuals_attached_at_utc"] = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    return payload, n
