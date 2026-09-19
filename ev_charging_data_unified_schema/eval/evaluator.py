"""Create an auditable evaluation artifact from point-in-time predictions.

Inputs: rows with the grain keys, the cohort column, ``prediction`` and ``actual``; an optional
``history`` frame (grain keys, cohort, ``actual``) seeds the causal baseline before the window.

Metrics, all on the same rows: ``mae``, ``median_ae``, ``rmse``, ``within_band1_rate`` and
``within_band2_rate`` (|error| <= the two tolerance bands of ``PROJECT.within_k``).

Baseline: *causal trailing mean* — for each row, the mean of the entity's realised outcomes from
strictly earlier periods, falling back to the cohort's earlier outcomes, falling back to the
row's own prediction. Outcomes of a period are appended only after every row of that period has
been scored.

Artifact: ``artifacts/schemas/eval_artifact.schema.json``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import subprocess
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from statistics import mean, median
from typing import Any

import pandas as pd

from ev_charging_data_unified_schema.config import PROJECT, REPO_ROOT

ARTIFACT_VERSION = "2.1"
BASELINE_NAME = "causal_trailing_mean"
EVAL_KINDS = ("frozen_test", "out_of_sample_season")
_ENTITY, _SEASON, _PERIOD, _COHORT = (
    PROJECT.entity_key,
    PROJECT.season_name,
    PROJECT.period_name,
    PROJECT.cohort_name,
)
REQUIRED_COLUMNS = {_ENTITY, _SEASON, _PERIOD, _COHORT, "prediction", "actual"}
BAND1, BAND2 = PROJECT.within_k


def _finite(value: Any, name: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _metrics(rows: Sequence[Mapping[str, Any]], prediction_key: str) -> dict[str, Any]:
    if not rows:
        return {
            "n": 0,
            "mae": None,
            "median_ae": None,
            "rmse": None,
            "within_band1_rate": None,
            "within_band2_rate": None,
        }
    errors = [
        abs(_finite(r[prediction_key], prediction_key) - _finite(r["actual"], "actual"))
        for r in rows
    ]
    return {
        "n": len(rows),
        "mae": round(mean(errors), 4),
        "median_ae": round(median(errors), 4),
        "rmse": round(math.sqrt(mean(e * e for e in errors)), 4),
        "within_band1_rate": round(mean(e <= BAND1 for e in errors), 4),
        "within_band2_rate": round(mean(e <= BAND2 for e in errors), 4),
    }


def _period(row: Mapping[str, Any]) -> tuple[int, int]:
    return int(row[_SEASON]), int(row[_PERIOD])


def add_causal_baseline(
    rows: Sequence[Mapping[str, Any]], history: Sequence[Mapping[str, Any]] = ()
) -> list[dict[str, Any]]:
    entity_history: dict[str, list[float]] = defaultdict(list)
    cohort_history: dict[str, list[float]] = defaultdict(list)
    if rows:
        first_period = min(_period(r) for r in rows)
        for h in sorted(history, key=_period):
            if _period(h) < first_period:
                actual = _finite(h["actual"], "actual")
                entity_history[str(h[_ENTITY])].append(actual)
                cohort_history[str(h[_COHORT])].append(actual)
    ordered = sorted(rows, key=lambda r: (_period(r), str(r[_ENTITY])))
    result: list[dict[str, Any]] = []
    by_period: dict[tuple[int, int], list[Mapping[str, Any]]] = defaultdict(list)
    for r in ordered:
        by_period[_period(r)].append(r)
    for period in sorted(by_period):
        period_rows = by_period[period]
        for source in period_rows:
            row = dict(source)
            hist = entity_history[str(row[_ENTITY])] or cohort_history[str(row[_COHORT])]
            row["trailing_mean_baseline"] = (
                mean(hist) if hist else _finite(row["prediction"], "prediction")
            )
            result.append(row)
        for row in period_rows:
            actual = _finite(row["actual"], "actual")
            entity_history[str(row[_ENTITY])].append(actual)
            cohort_history[str(row[_COHORT])].append(actual)
    return result


def evaluate_rows(
    rows: Iterable[Mapping[str, Any]],
    test_start: tuple[int, int],
    history: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    materialized = list(rows)
    if not materialized:
        raise ValueError("evaluation input is empty")
    for index, row in enumerate(materialized, start=1):
        missing = REQUIRED_COLUMNS - set(row)
        if missing:
            raise ValueError(f"row {index} missing required columns: {', '.join(sorted(missing))}")
    enriched = add_causal_baseline(materialized, list(history))
    test = [r for r in enriched if _period(r) >= tuple(test_start)]
    if not test:
        raise ValueError("test_start produces an empty test set")
    cohorts = {}
    for c in sorted({str(r[_COHORT]) for r in test}):
        sub = [r for r in test if r[_COHORT] == c]
        cohorts[c] = {
            **_metrics(sub, "prediction"),
            "baseline": _metrics(sub, "trailing_mean_baseline"),
        }
    return {
        "split": {
            "strategy": "forward_time_holdout",
            "test_start_season": int(test_start[0]),
            "test_start_period": int(test_start[1]),
        },
        "metrics": _metrics(test, "prediction"),
        "baseline": {"name": BASELINE_NAME, **_metrics(test, "trailing_mean_baseline")},
        "cohorts": cohorts,
    }


def evaluate_frame(
    predictions: pd.DataFrame, test_start: tuple[int, int], *, history: pd.DataFrame | None = None
) -> dict[str, Any]:
    return evaluate_rows(
        predictions.to_dict("records"),
        test_start,
        history=history.to_dict("records") if history is not None else (),
    )


FitPredict = Callable[[pd.DataFrame, str, int, int, str], pd.DataFrame]


def rolling_origin(
    features: pd.DataFrame,
    season: int,
    fit_predict: FitPredict,
    *,
    candidate: str = "rf",
    periods: Iterable[int] | None = None,
    history: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """For each period p of ``season`` refit every cohort's model on rows strictly before p and
    score p; per-fold MAE next to the causal baseline MAE on the same rows."""
    cohorts = sorted(features[_COHORT].unique())
    in_season = features[features[_SEASON] == season]
    if periods is None:
        periods = range(2, int(in_season[_PERIOD].max()) + 1)
    folds = []
    hist_rows = history.to_dict("records") if history is not None else ()
    for p in periods:
        fold = pd.concat(
            [fit_predict(features, c, season, p, candidate) for c in cohorts], ignore_index=True
        )
        fold = fold[fold["prediction"].notna()]
        if fold.empty:
            continue
        fold = fold.rename(columns={"target": "actual"})
        rows = fold[[_ENTITY, _SEASON, _PERIOD, _COHORT, "prediction", "actual"]].to_dict("records")
        enriched = add_causal_baseline(rows, list(hist_rows))
        folds.append(
            {
                "season": int(season),
                "period": int(p),
                "n": len(enriched),
                "mae": _metrics(enriched, "prediction")["mae"],
                "baseline_mae": _metrics(enriched, "trailing_mean_baseline")["mae"],
            }
        )
    return {
        "candidate": candidate,
        "strategy": "refit on all rows strictly before (season, period); score that period",
        "folds": folds,
        "mean_mae": round(mean(f["mae"] for f in folds), 4) if folds else None,
        "mean_baseline_mae": round(mean(f["baseline_mae"] for f in folds), 4) if folds else None,
    }


def git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL, cwd=REPO_ROOT
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def sha256_of_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repo_relative(path: Path | None) -> str | None:
    if path is None:
        return None
    path = Path(path).resolve()
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.name


def build_artifact(
    report: dict[str, Any],
    *,
    input_path: Path | None,
    input_rows: int,
    model: dict[str, Any],
    rolling: dict[str, Any] | None = None,
    eval_id: str | None = None,
    kind: str = "frozen_test",
    season: int | None = None,
    id_suffix: str = "",
) -> dict[str, Any]:
    if kind not in EVAL_KINDS:
        raise ValueError(f"kind must be one of {EVAL_KINDS}")
    now = dt.datetime.now(dt.UTC)
    cand = model.get("candidate", "")
    if isinstance(cand, dict):
        cand = cand[next(iter(cand))] if len(set(cand.values())) == 1 else "mixed"
    eval_id = eval_id or (
        f"eval-{now:%Y%m%d}-{model.get('version', 'model')}-{cand}".rstrip("-") + id_suffix
    )
    season = season if season is not None else report.get("split", {}).get("test_start_season")
    artifact = {
        "artifact_version": ARTIFACT_VERSION,
        "eval_id": eval_id,
        "kind": kind,
        "season": season,
        "generated_at_utc": now.isoformat(timespec="seconds"),
        "code_commit": git_commit(),
        "input": {
            "path": repo_relative(input_path),
            "sha256": sha256_of_file(input_path) if input_path else None,
            "n_rows": int(input_rows),
        },
        "model": model,
        "metric_definitions": {
            "mae": "mean(|actual - prediction|)",
            "median_ae": "median(|actual - prediction|)",
            "rmse": "sqrt(mean((actual - prediction)^2))",
            "within_band1_rate": f"mean(|actual - prediction| <= {BAND1}), same rows as mae",
            "within_band2_rate": f"mean(|actual - prediction| <= {BAND2}), same rows as mae",
            "baseline": (
                f"causal trailing mean of the {PROJECT.entity_name}'s earlier realised {PROJECT.target_units} "
                f"({PROJECT.cohort_name} fallback); outcomes of a {PROJECT.period_name} are added only after it is scored"
            ),
        },
        **report,
    }
    if rolling is not None:
        artifact["rolling_origin"] = rolling
    return artifact


def write_artifact(artifact: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    return path
