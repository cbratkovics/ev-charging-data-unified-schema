#!/usr/bin/env python
"""Evaluate a frozen model artifact, write the evaluation artifact, register it in the manifest,
and regenerate docs/MODEL_CARD.md.

    python scripts/evaluate.py [--model-version V] [--kind out_of_sample_season --season S]

Frozen test: reads models/<version>/test_predictions.csv (written at training time).
Out-of-sample season: scores every played row of a later season with the persisted pipelines.
Every number in the model card traces to artifacts/eval/<eval_id>.json or the model metadata.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run without installing

import argparse
import json

import numpy as np
import pandas as pd

from ev_charging_data_unified_schema.config import ARTIFACTS_DIR, PROJECT, REPO_ROOT
from ev_charging_data_unified_schema.data import loader
from ev_charging_data_unified_schema.eval import evaluator, model_card
from ev_charging_data_unified_schema.features import asof
from ev_charging_data_unified_schema.models import registry, train

_ENTITY, _SEASON, _PERIOD, _COHORT = (
    PROJECT.entity_key,
    PROJECT.season_name,
    PROJECT.period_name,
    PROJECT.cohort_name,
)


def _latest_model_version() -> str:
    versions = sorted(
        p.name for p in (ARTIFACTS_DIR / "models").glob("*") if (p / "metadata.json").exists()
    )
    if not versions:
        raise SystemExit("no trained model under artifacts/models; run scripts/train.py first")
    return versions[-1]


def _champion_rows(df: pd.DataFrame, meta: dict) -> pd.DataFrame:
    champ = {c: m["champion"] for c, m in meta["cohorts"].items()}
    return df[df.apply(lambda r: r["candidate"] == champ[r[_COHORT]], axis=1)].reset_index(
        drop=True
    )


def score_out_of_sample(rows: pd.DataFrame, season: int, model_version: str) -> pd.DataFrame:
    meta = registry.read_model_metadata(model_version)
    if season <= max(meta["seasons"]["train"] + [meta["seasons"]["val"], meta["seasons"]["test"]]):
        raise SystemExit(f"season {season} was used to train, validate or test {model_version}")
    feats = asof.training_frame(asof.build_features(rows))
    sub = feats[feats[_SEASON] == season]
    out = []
    for cohort in PROJECT.cohorts:
        cr = sub[sub[_COHORT] == cohort]
        if cr.empty:
            continue
        cols = asof.features_for_cohort(cohort)
        for cand in meta["candidates"]:
            pipe = registry.load_pipelines(model_version, cand)[cohort]
            pred = pipe.predict(cr[cols])
            q10, q90 = meta["cohorts"][cohort]["candidates"][cand]["residual_quantiles"]["values"]
            frame = cr[
                list(asof.KEY_COLUMNS) + [_COHORT, PROJECT.entity_display_column, "team"]
            ].copy()
            frame["candidate"] = cand
            frame["prediction"] = np.round(pred, 3)
            frame["prediction_floor"] = np.round(np.clip(pred + q10, 0, None), 3)
            frame["prediction_ceiling"] = np.round(pred + q90, 3)
            frame["actual"] = cr["target"].to_numpy()
            out.append(frame)
    return (
        pd.concat(out, ignore_index=True)
        .sort_values(["candidate", _COHORT, _SEASON, _PERIOD, _ENTITY])
        .reset_index(drop=True)
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model-version", default=None)
    p.add_argument("--kind", choices=evaluator.EVAL_KINDS, default="frozen_test")
    p.add_argument("--season", type=int, default=None, help="season for out_of_sample_season")
    p.add_argument(
        "--no-rolling", action="store_true", help="skip the rolling-origin refits (faster)"
    )
    p.add_argument(
        "--rolling-max-folds",
        type=int,
        default=12,
        help="refit at most this many evenly spaced periods of the season (long seasons)",
    )
    a = p.parse_args()
    model_version = a.model_version or _latest_model_version()
    meta = registry.read_model_metadata(model_version)
    mdir = registry.model_dir(model_version)

    if a.kind == "frozen_test":
        season = meta["seasons"]["test"]
        input_path = mdir / meta["test_predictions_path"]
        preds = pd.read_csv(input_path)
        rows = loader.load_period_rows(range(PROJECT.min_season, season + 1))
        suffix = ""
    else:
        if a.season is None:
            raise SystemExit("--season is required for out_of_sample_season")
        season = a.season
        rows = loader.load_period_rows(range(PROJECT.min_season, season + 1))
        preds = score_out_of_sample(rows, season, model_version)
        input_path = mdir / f"oos_predictions_{season}.csv"
        preds.to_csv(input_path, index=False)
        suffix = f"-oos{season}"

    champ = _champion_rows(preds, meta)
    history = rows[rows[_SEASON] < season][
        [_ENTITY, _SEASON, _PERIOD, _COHORT, PROJECT.target_column]
    ].rename(columns={PROJECT.target_column: "actual"})
    report = evaluator.evaluate_frame(
        champ[[_ENTITY, _SEASON, _PERIOD, _COHORT, "prediction", "actual"]],
        (season, 1),
        history=history,
    )
    rolling = None
    if not a.no_rolling:
        feats = asof.training_frame(asof.build_features(rows))
        champion_name = next(iter({m["champion"] for m in meta["cohorts"].values()}))
        in_season = sorted(int(x) for x in feats[feats[_SEASON] == season][_PERIOD].unique())[1:]
        step = max(1, -(-len(in_season) // a.rolling_max_folds))
        rolling = evaluator.rolling_origin(
            feats,
            season,
            train.fit_predict_for_period,
            candidate=champion_name,
            periods=in_season[::step],
            history=history,
        )
    model = {
        "version": model_version,
        "feature_version": meta["feature_version"],
        "candidate": {c: m["champion"] for c, m in meta["cohorts"].items()},
        "challenger": {c: m["challenger"] for c, m in meta["cohorts"].items()},
        "trained_at_utc": meta["trained_at_utc"],
        "input_sha256": meta["input_sha256"],
    }
    artifact = evaluator.build_artifact(
        report,
        input_path=input_path,
        input_rows=len(preds),
        model=model,
        rolling=rolling,
        kind=a.kind,
        season=season,
        id_suffix=suffix,
    )
    path = evaluator.write_artifact(
        artifact, ARTIFACTS_DIR / "eval" / f"{artifact['eval_id']}.json"
    )

    manifest_path = ARTIFACTS_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    champion = {"model_version": model_version, "candidate": model["candidate"]}
    challenger = {"model_version": model_version, "candidate": model["challenger"]}
    manifest.setdefault("champion", champion)
    manifest.setdefault("challenger", challenger)
    manifest["feature_version"] = meta["feature_version"]
    manifest.setdefault("data_through", meta["data_through"])
    registry.register_evaluation(
        manifest,
        {
            "eval_id": artifact["eval_id"],
            "kind": a.kind,
            "season": season,
            "path": f"eval/{artifact['eval_id']}.json",
            "generated_at_utc": artifact["generated_at_utc"],
        },
    )
    registry.write_manifest(manifest, manifest_path)
    card = model_card.write_model_card(manifest, out_path=REPO_ROOT / "docs" / "MODEL_CARD.md")
    m = artifact["metrics"]
    print(
        f"{artifact['eval_id']}: n={m['n']} mae={m['mae']} baseline_mae={artifact['baseline']['mae']} -> {path}\nmodel card -> {card}"
    )


if __name__ == "__main__":
    main()
