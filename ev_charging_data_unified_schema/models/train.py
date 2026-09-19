"""Train per-cohort champion / challenger candidates and write a versioned model artifact.

* seasons: ``PROJECT.train_seasons`` / ``val_season`` / ``test_season`` (whole seasons, forward)
* candidates per cohort: RandomForest (``rf``) and HistGradientBoosting (``gbm``), each an sklearn
  ``Pipeline(StandardScaler, model)`` fit on a DataFrame so ``feature_names_in_`` travels with it
* the candidate with the lower validation MAE is the champion for that cohort; both are persisted
* intervals: validation residual quantiles (10th / 90th) per cohort and candidate
* drift reference: decile edges of every feature on the training rows, globally and per
  period-of-season bucket, plus top-10 feature importances (``eval.drift``)

Everything the evaluator and the model card need is in ``metadata.json``
(``artifacts/schemas/model_metadata.schema.json``).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.inspection import permutation_importance
from sklearn.metrics import mean_absolute_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ev_charging_data_unified_schema import __version__ as package_version
from ev_charging_data_unified_schema.config import ARTIFACTS_DIR, PROJECT, RANDOM_STATE
from ev_charging_data_unified_schema.data import loader
from ev_charging_data_unified_schema.eval import drift
from ev_charging_data_unified_schema.eval.evaluator import git_commit
from ev_charging_data_unified_schema.features import asof

CANDIDATES: tuple[str, ...] = PROJECT.candidates
INTERVAL_QUANTILES: tuple[float, float] = (0.10, 0.90)
N_DECILES = 10
TOP_IMPORTANCE = 10
RF_PARAMS: dict[str, Any] = {
    "n_estimators": 100,
    "max_depth": 10,
    "min_samples_split": 20,
    "min_samples_leaf": 10,
    "random_state": RANDOM_STATE,
    "n_jobs": -1,
}
GBM_PARAMS: dict[str, Any] = {
    "max_iter": 200,
    "learning_rate": 0.05,
    "max_depth": 4,
    "l2_regularization": 1.0,
    "random_state": RANDOM_STATE,
}
_ENTITY, _SEASON, _PERIOD, _COHORT = (
    PROJECT.entity_key,
    PROJECT.season_name,
    PROJECT.period_name,
    PROJECT.cohort_name,
)


def input_sha256(rows: pd.DataFrame) -> str:
    """Order-independent content hash of the source frame."""
    keyed = rows.sort_values(list(asof.KEY_COLUMNS)).reset_index(drop=True)
    cols = list(asof.KEY_COLUMNS) + [c for c in loader.STAT_COLUMNS if c in keyed.columns]
    h = pd.util.hash_pandas_object(keyed[cols], index=False).to_numpy()
    return hashlib.sha256(h.tobytes()).hexdigest()


def make_candidate(name: str) -> Pipeline:
    if name == "rf":
        model = RandomForestRegressor(**RF_PARAMS)
    elif name == "gbm":
        model = HistGradientBoostingRegressor(**GBM_PARAMS)
    else:
        raise ValueError(f"unknown candidate {name!r}")
    return Pipeline([("scaler", StandardScaler()), ("model", model)])


def split_by_season(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {
        "train": frame[frame[_SEASON].isin(PROJECT.train_seasons)],
        "val": frame[frame[_SEASON] == PROJECT.val_season],
        "test": frame[frame[_SEASON] == PROJECT.test_season],
    }


def _importances(
    pipe: Pipeline, x_val: pd.DataFrame, y_val: pd.Series, features: list[str]
) -> dict[str, float]:
    model = pipe.named_steps["model"]
    imp = getattr(model, "feature_importances_", None)
    if imp is None:  # HistGradientBoosting has none; permutation importance on validation rows
        imp = permutation_importance(
            pipe, x_val, y_val, n_repeats=3, random_state=RANDOM_STATE
        ).importances_mean
    order = np.argsort(imp)[::-1][:TOP_IMPORTANCE]
    return {features[i]: float(imp[i]) for i in order}


def _deciles(frame: pd.DataFrame, features: list[str]) -> dict[str, list[float]]:
    qs = np.linspace(0, 1, N_DECILES + 1)
    return {f: [float(v) for v in np.quantile(frame[f].to_numpy(), qs)] for f in features}


def _drift_reference(frame: pd.DataFrame, features: list[str]) -> dict[str, Any]:
    buckets = {}
    b = frame[_PERIOD].astype(int).map(drift.period_bucket)
    for k in sorted(b.unique()):
        buckets[str(int(k))] = _deciles(frame[b == k], features)
    return {
        "bucket_periods": drift.BUCKET_PERIODS,
        "global": _deciles(frame, features),
        "buckets": buckets,
    }


def _model_version(feature_version: str, sha: str, now: dt.datetime) -> str:
    return f"{now:%Y%m%d}-{feature_version}-{sha[:8]}"


def fit_cohort(
    cohort: str, train: pd.DataFrame, val: pd.DataFrame, candidates: tuple[str, ...] = CANDIDATES
) -> dict[str, Any]:
    feats = asof.features_for_cohort(cohort)
    x_tr, y_tr = train[feats], train["target"]
    x_va, y_va = val[feats], val["target"]
    out: dict[str, Any] = {
        "features": feats,
        "pipelines": {},
        "val_mae": {},
        "residual_q": {},
        "importance": {},
    }
    for name in candidates:
        pipe = make_candidate(name).fit(x_tr, y_tr)
        pred_va = pipe.predict(x_va)
        resid = y_va.to_numpy() - pred_va
        out["pipelines"][name] = pipe
        out["val_mae"][name] = float(mean_absolute_error(y_va, pred_va))
        out["residual_q"][name] = [float(np.quantile(resid, q)) for q in INTERVAL_QUANTILES]
        out["importance"][name] = _importances(pipe, x_va, y_va, feats)
    return out


def train_all(
    rows: pd.DataFrame,
    *,
    artifacts: Path = ARTIFACTS_DIR,
    candidates: tuple[str, ...] = CANDIDATES,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Train every cohort, persist ``artifacts/models/<model_version>/``, return the metadata."""
    now = now or dt.datetime.now(dt.UTC)
    sha = input_sha256(rows)
    model_version = _model_version(asof.FEATURE_VERSION, sha, now)
    out_dir = artifacts / "models" / model_version
    out_dir.mkdir(parents=True, exist_ok=True)

    features = asof.training_frame(asof.build_features(rows))
    parts = split_by_season(features)
    data_through = rows.sort_values([_SEASON, _PERIOD]).iloc[-1]

    cohorts_meta: dict[str, Any] = {}
    test_predictions: list[pd.DataFrame] = []
    for cohort in PROJECT.cohorts:
        tr = parts["train"][parts["train"][_COHORT] == cohort]
        va = parts["val"][parts["val"][_COHORT] == cohort]
        te = parts["test"][parts["test"][_COHORT] == cohort]
        if tr.empty or va.empty or te.empty:
            raise ValueError(
                f"cohort {cohort}: empty train/val/test split; check the seasons in config"
            )
        fitted = fit_cohort(cohort, tr, va, candidates)
        feats = fitted["features"]
        champion = min(fitted["val_mae"], key=fitted["val_mae"].get)
        challenger = next((c for c in candidates if c != champion), None)
        baseline_mean = float(tr["target"].mean())
        cand_meta: dict[str, Any] = {}
        for name, pipe in fitted["pipelines"].items():
            joblib.dump(pipe, out_dir / f"{cohort}_{name}.pkl", compress=3)
            pred_te = pipe.predict(te[feats])
            cand_meta[name] = {
                "val_mae": fitted["val_mae"][name],
                "test_mae": float(mean_absolute_error(te["target"], pred_te)),
                "residual_quantiles": {
                    "q": list(INTERVAL_QUANTILES),
                    "values": fitted["residual_q"][name],
                },
                "top_feature_importance": fitted["importance"][name],
                "hyperparameters": RF_PARAMS if name == "rf" else GBM_PARAMS,
            }
            frame = te[
                list(asof.KEY_COLUMNS) + [_COHORT, PROJECT.entity_display_column, "team"]
            ].copy()
            frame["candidate"] = name
            frame["prediction"] = np.round(pred_te, 3)
            q10, q90 = fitted["residual_q"][name]
            frame["prediction_floor"] = np.round(np.clip(pred_te + q10, 0, None), 3)
            frame["prediction_ceiling"] = np.round(pred_te + q90, 3)
            frame["actual"] = te["target"].to_numpy()
            test_predictions.append(frame)
        cohorts_meta[cohort] = {
            "n_train": int(len(tr)),
            "n_val": int(len(va)),
            "n_test": int(len(te)),
            "n_features": len(feats),
            "features": feats,
            "champion": champion,
            "challenger": challenger,
            "baseline_cohort_mean": {
                "value": baseline_mean,
                "test_mae": float(
                    mean_absolute_error(te["target"], np.full(len(te), baseline_mean))
                ),
            },
            "candidates": cand_meta,
            "drift_reference": _drift_reference(tr, feats),
        }

    preds = pd.concat(test_predictions, ignore_index=True)
    preds.to_csv(out_dir / "test_predictions.csv", index=False)
    metadata = {
        "model_version": model_version,
        "feature_version": asof.FEATURE_VERSION,
        "package_version": package_version,
        "sklearn_version": sklearn.__version__,
        "data_library": loader.LIBRARY,
        "trained_at_utc": now.isoformat(timespec="seconds"),
        "data_through": {
            "season": int(data_through[_SEASON]),
            "period": int(data_through[_PERIOD]),
        },
        "seasons": {
            "train": list(PROJECT.train_seasons),
            "val": PROJECT.val_season,
            "test": PROJECT.test_season,
        },
        "target": f"{PROJECT.target_column} ({PROJECT.target_units}; rules in {PROJECT.package_name}.target)",
        "input_sha256": sha,
        "input_rows": int(len(rows)),
        "code_commit": git_commit(),
        "interval_method": "validation-season residual quantiles (10th/90th) per cohort and candidate, added to the point prediction; floor clipped at 0",
        "candidates": list(candidates),
        "cohorts": cohorts_meta,
        "test_predictions_path": "test_predictions.csv",
    }
    (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def fit_predict_for_period(
    features: pd.DataFrame, cohort: str, season: int, period: int, candidate: str = "rf"
) -> pd.DataFrame:
    """Rolling-origin helper: fit on rows strictly before (season, period), predict that period."""
    sub = features[features[_COHORT] == cohort]
    before = sub[(sub[_SEASON] < season) | ((sub[_SEASON] == season) & (sub[_PERIOD] < period))]
    target_rows = sub[(sub[_SEASON] == season) & (sub[_PERIOD] == period)]
    feats = asof.features_for_cohort(cohort)
    if before.empty or target_rows.empty:
        return target_rows.assign(prediction=np.nan)
    pipe = make_candidate(candidate).fit(before[feats], before["target"])
    return target_rows.assign(prediction=pipe.predict(target_rows[feats]))
