"""Population Stability Index (PSI) per feature against the training reference.

Reference (hybrid): the window is the last ``WINDOW_PERIODS`` played periods. While the window
sits inside one season, the reference is the period-of-season bucket recorded at training time
(``metadata.json -> cohorts[c].drift_reference.buckets``). When the window crosses a season
boundary (the first few periods of a season, when the window still holds last season's final
periods), the reference is rebuilt from the training seasons' rows at the same period-of-season
positions the window contains, so late-season rows are compared with late-season training rows.
A boundary-crossing window compared with an early-season bucket held three of five seasons on the
source project; a single-period comparison is worse (too few rows for ten-bin PSI).
``reference_for_window`` decides and records the mode; every run writes
``artifacts/drift/<run_id>.json`` (``artifacts/schemas/drift_report.schema.json``).

THRESHOLDS ARE NOT CALIBRATED (``CALIBRATED = False``). The values below are placeholders shaped
like the ones another project calibrated on its own backtests; they are not evidence about your
data. Until you calibrate, the scheduled job reports drift but never HOLDs on it.

Calibration recipe (write the result as an ADR and flip ``CALIBRATED``):
1. Build features on the full training history with the shipped feature module.
2. For every window of ``WINDOW_PERIODS`` consecutive played periods inside the training
   seasons, compute PSI per monitored feature against the training deciles of the same
   period-of-season bucket (``metadata.json -> drift_reference``), exactly as the scheduled
   job does.
3. Count how many of those normal windows the rule would HOLD. Scan **every** target period
   the job will ever run at, including the first periods of a season where the window crosses
   the boundary; calibrating on mid-season windows only is how the source project shipped a
   monitor that held its second production period. A rule that holds normal windows is wrong
   regardless of the textbook value; single-feature PSI on a few hundred rows is noisy, which is
   why the rule uses the *median* of the monitored features and a count of severe features
   rather than any single feature.
4. Set ``WARN_PSI`` / ``HOLD_PSI`` / ``SEVERE_PSI`` so that zero (or a documented handful of)
   normal windows hold, then confirm the rule fires on a synthetic shift (e.g. scale a feature by
   1.5 in one window). Record the counts in the ADR.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ev_charging_data_unified_schema.config import PROJECT

CALIBRATED = False  # TODO(calibration): follow the recipe in the module docstring
# The window crosses a "boundary" when its rows span more than one value of this column; the
# reference is then matched to the window's period positions. Season is the natural boundary;
# a project whose periods never reset can set MATCH_ACROSS_BOUNDARY = False to keep buckets only.
BOUNDARY_COLUMN = PROJECT.season_name
MATCH_ACROSS_BOUNDARY = True
MIN_REFERENCE_ROWS = 100  # fewer matched training rows than this -> bucket reference
REPORT_VERSION = "1.1"
WARN_PSI = 0.10
HOLD_PSI = 0.25
SEVERE_PSI = 0.50
MIN_SEVERE_FEATURES = 2
MIN_MONITORED_FOR_MEDIAN = 3
N_BUCKETS = 5  # period-of-season buckets; the reference deciles are stored per bucket
BUCKET_PERIODS = max(1, -(-PROJECT.periods_per_season // N_BUCKETS))  # ceil(N / buckets)
WINDOW_PERIODS = 4
_EPS = 1e-6


def period_bucket(period: int, size: int = BUCKET_PERIODS) -> int:
    """Period-of-season bucket of `size` periods, capped at N_BUCKETS - 1."""
    return min((int(period) - 1) // size, N_BUCKETS - 1)


def drift_status(psi: dict[str, float], monitored: list[str]) -> tuple[str, list[str], list[str]]:
    vals = {
        f: psi[f] for f in monitored if f in psi and psi[f] is not None and not np.isnan(psi[f])
    }
    if not vals:
        return "ok", [], []
    med = float(np.median(list(vals.values())))
    flagged = sorted(f for f, v in vals.items() if v > HOLD_PSI)
    severe = sorted(f for f, v in vals.items() if v > SEVERE_PSI)
    broad = med > HOLD_PSI and len(vals) >= MIN_MONITORED_FOR_MEDIAN
    if broad or len(severe) >= MIN_SEVERE_FEATURES:
        return "hold", flagged, severe
    if flagged or med > WARN_PSI:
        return "warn", flagged, severe
    return "ok", flagged, severe


def psi_from_deciles(values: np.ndarray, decile_edges: list[float]) -> float:
    values = np.asarray(values, dtype="float64")
    values = values[np.isfinite(values)]
    if values.size == 0:
        return float("nan")
    edges = np.asarray(decile_edges, dtype="float64")
    uniq = np.unique(edges)
    if uniq.size < 2:
        return 0.0
    ref_counts = np.histogram(edges[:-1], bins=uniq)[0]
    ref = ref_counts / ref_counts.sum()
    inner = uniq.copy()
    inner[0], inner[-1] = -np.inf, np.inf
    cur = np.histogram(values, bins=inner)[0] / values.size
    ref = np.clip(ref, _EPS, None)
    cur = np.clip(cur, _EPS, None)
    return float(np.sum((cur - ref) * np.log(cur / ref)))


_PERIOD = PROJECT.period_name


def deciles(frame: pd.DataFrame, features: list[str]) -> dict[str, list[float]]:
    qs = np.linspace(0, 1, 11)
    return {f: [float(v) for v in np.quantile(frame[f].to_numpy(), qs)] for f in features}


def window_periods(window: pd.DataFrame) -> list[int]:
    periods = (
        window[[BOUNDARY_COLUMN, _PERIOD]].drop_duplicates().sort_values([BOUNDARY_COLUMN, _PERIOD])
    )
    return [int(p) for p in periods[_PERIOD]]


def reference_for_window(
    window: pd.DataFrame,
    bucket_reference: dict[str, Any],
    training_rows: pd.DataFrame,
    monitored: list[str],
) -> tuple[dict[str, list[float]], dict[str, Any]]:
    """The hybrid reference and a description of how it was chosen (see the module docstring)."""
    periods = window_periods(window)
    boundaries = sorted(int(v) for v in window[BOUNDARY_COLUMN].unique())
    crosses = MATCH_ACROSS_BOUNDARY and len(boundaries) > 1
    training_seasons = sorted(int(v) for v in training_rows[BOUNDARY_COLUMN].unique())
    if crosses:
        rows = training_rows[training_rows[_PERIOD].isin(periods)]
        if len(rows) >= MIN_REFERENCE_ROWS:
            return deciles(rows, monitored), {
                "mode": "matched",
                "window_seasons": boundaries,
                "window_periods": periods,
                "reference_periods": sorted(set(periods)),
                "training_seasons": training_seasons,
                "n_reference_rows": int(len(rows)),
            }
    bucket = period_bucket(periods[-1]) if periods else 0
    ref = bucket_reference["buckets"].get(str(bucket)) or bucket_reference["global"]
    return ref, {
        "mode": "bucket",
        "window_seasons": boundaries,
        "window_periods": periods,
        "reference_periods": list(
            range(bucket * BUCKET_PERIODS + 1, bucket * BUCKET_PERIODS + BUCKET_PERIODS + 1)
        ),
        "bucket": int(bucket),
        "training_seasons": training_seasons,
        "n_reference_rows": None,
        "fallback": "fewer than MIN_REFERENCE_ROWS matched rows" if crosses else None,
    }


def run_report(
    *,
    run_id: str,
    at_utc: str,
    season: int,
    period: int,
    model_version: str,
    status: str,
    positions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """The per-run monitoring artifact written to ``artifacts/drift/<run_id>.json``."""
    return {
        "drift_report_version": REPORT_VERSION,
        "run_id": run_id,
        "at_utc": at_utc,
        "season": int(season),
        "period": int(period),
        "model_version": model_version,
        "window_periods_max": WINDOW_PERIODS,
        "calibrated": CALIBRATED,
        "status": status,
        "cohorts": positions,
    }


def write_run_report(report: dict[str, Any], artifacts: Path) -> Path:
    path = artifacts / "drift" / f"{report['run_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return path


def drift_report(
    current: pd.DataFrame,
    reference_deciles: dict[str, list[float]],
    monitored: list[str],
    *,
    reference: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """``artifacts/schemas/drift_report.schema.json``. ``status`` is the rule's verdict; the
    scheduled job downgrades ``hold`` to ``warn`` while ``CALIBRATED`` is False."""
    psi: dict[str, float] = {}
    for feature, edges in reference_deciles.items():
        if feature in current.columns:
            psi[feature] = psi_from_deciles(current[feature].to_numpy(), edges)
    status, flagged, severe = drift_status(psi, monitored)
    vals = [psi[f] for f in monitored if f in psi and not np.isnan(psi[f])]
    return {
        "n": int(len(current)),
        "psi": {k: (None if np.isnan(v) else round(v, 4)) for k, v in psi.items()},
        "monitored": list(monitored),
        "median_monitored": round(float(np.median(vals)), 4) if vals else None,
        "flagged": flagged,
        "severe": severe,
        "thresholds": {
            "warn": WARN_PSI,
            "hold_median": HOLD_PSI,
            "severe": SEVERE_PSI,
            "min_severe_features": MIN_SEVERE_FEATURES,
            "calibrated": CALIBRATED,
        },
        "status": status,
        "reference": reference,
    }
