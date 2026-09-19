"""Artifact manifest: what the API serves and what the scheduled job promotes.

``artifacts/manifest.json`` (schema: ``artifacts/schemas/manifest.schema.json``) is the single
source of truth for the served configuration: champion / challenger slots, registered
evaluations, data-through period, latest predictions file, last run. Model artifacts live in
``artifacts/models/<model_version>/`` with ``<cohort>_<candidate>.pkl`` pipelines and one
``metadata.json``. Paths inside the manifest are relative to ``artifacts/``.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import joblib

from ev_charging_data_unified_schema.config import ARTIFACTS_DIR, MANIFEST_PATH, PROJECT

MANIFEST_VERSION = "1.0"
ACTIONS = ("PUBLISH", "HOLD", "PROMOTE")


def utc_now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def read_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"manifest not found at {path}; run scripts/train.py and scripts/evaluate.py first"
        )
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def write_manifest(manifest: dict[str, Any], path: Path = MANIFEST_PATH) -> None:
    manifest = dict(manifest)
    manifest["manifest_version"] = MANIFEST_VERSION
    manifest["updated_at_utc"] = utc_now_iso()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def model_dir(model_version: str, artifacts: Path = ARTIFACTS_DIR) -> Path:
    return artifacts / "models" / model_version


def read_model_metadata(model_version: str, artifacts: Path = ARTIFACTS_DIR) -> dict[str, Any]:
    with (model_dir(model_version, artifacts) / "metadata.json").open(encoding="utf-8") as fh:
        return json.load(fh)


def candidate_for(candidate: str | dict[str, str], cohort: str) -> str:
    return candidate if isinstance(candidate, str) else candidate[cohort]


def load_pipelines(
    model_version: str, candidate: str | dict[str, str], artifacts: Path = ARTIFACTS_DIR
) -> dict[str, Any]:
    d = model_dir(model_version, artifacts)
    out = {}
    for cohort in PROJECT.cohorts:
        p = d / f"{cohort}_{candidate_for(candidate, cohort)}.pkl"
        if not p.exists():
            raise FileNotFoundError(f"missing model artifact {p}")
        out[cohort] = joblib.load(p)
    return out


def evaluations(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    evs = list(manifest.get("evaluations") or [])
    if not evs and manifest.get("eval_id"):
        evs = [
            {
                "eval_id": manifest["eval_id"],
                "kind": "frozen_test",
                "season": None,
                "path": f"eval/{manifest['eval_id']}.json",
            }
        ]
    return evs


def register_evaluation(manifest: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    evs = [e for e in evaluations(manifest) if e["eval_id"] != entry["eval_id"]]
    evs.append(entry)
    evs.sort(key=lambda e: (e.get("season") or 0, e["eval_id"]))
    manifest["evaluations"] = evs
    if entry.get("kind") == "frozen_test":
        manifest["eval_id"] = entry["eval_id"]
    return manifest


def slot(manifest: dict[str, Any], name: str) -> tuple[str, str | dict[str, str]]:
    s = manifest.get(name)
    if not s:
        raise KeyError(f"manifest has no {name!r} slot")
    return s["model_version"], s["candidate"]


def should_promote(
    champion_recent_mae: list[float],
    challenger_recent_mae: list[float],
    champion_frozen_test_mae: float,
    challenger_frozen_test_mae: float,
    *,
    min_periods: int = 4,
) -> tuple[bool, str]:
    """Promote when the challenger beats the champion on rolling MAE in each of the last
    ``min_periods`` scored periods and on the frozen test set. Deterministic; unit-tested."""
    if len(champion_recent_mae) < min_periods or len(challenger_recent_mae) < min_periods:
        return False, f"fewer than {min_periods} scored periods available"
    recent_c = champion_recent_mae[-min_periods:]
    recent_x = challenger_recent_mae[-min_periods:]
    wins = sum(x < c for c, x in zip(recent_c, recent_x, strict=True))
    if wins < min_periods:
        return (
            False,
            f"challenger won {wins}/{min_periods} recent periods (needs {min_periods}/{min_periods})",
        )
    if not challenger_frozen_test_mae < champion_frozen_test_mae:
        return (
            False,
            f"challenger frozen-test MAE {challenger_frozen_test_mae:.3f} not below champion {champion_frozen_test_mae:.3f}",
        )
    return (
        True,
        f"challenger won all {min_periods} recent periods and frozen test ({challenger_frozen_test_mae:.3f} < {champion_frozen_test_mae:.3f})",
    )
