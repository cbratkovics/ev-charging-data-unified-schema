"""The autonomous scheduled job: sense → check → decide → act → record. No model in the loop.

1. Resolve the current season / next period from the loader's calendar (or CLI overrides).
2. Load rows through the last completed period; run the data contracts (dbt silver tests via
   ``data.contracts``); failure → HOLD.
3. Drift: PSI of the last ``WINDOW_PERIODS`` completed periods against the period-of-season
   matched training deciles (``eval.drift``). While the thresholds are uncalibrated a ``hold``
   verdict is downgraded to ``warn`` and logged.
4. Build as-of features for the upcoming period and score the champion →
   ``artifacts/predictions/<season>/period_<pp>.json``.
5. Attach last period's actuals to last period's file; append champion + challenger MAE and
   baseline MAE to ``artifacts/eval/rolling_<season>.json``.
6. PROMOTE rule (``registry.should_promote``): challenger beats champion on the last four scored
   periods and on the frozen test set → swap manifest slots and rescore.
7. Update ``manifest.json``, regenerate ``docs/MODEL_CARD.md``, write the run log to
   ``artifacts/runs/<run_id>.json``. The workflow commits and opens an Issue on HOLD.

``decide`` is a pure function over the step results so the policy is unit-testable without data.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pandas as pd

from ev_charging_data_unified_schema.config import ARTIFACTS_DIR, PROJECT, REPO_ROOT
from ev_charging_data_unified_schema.data import contracts, loader
from ev_charging_data_unified_schema.eval import drift, evaluator, model_card
from ev_charging_data_unified_schema.features import asof
from ev_charging_data_unified_schema.models import registry
from ev_charging_data_unified_schema.pipeline import score

ACTION_PUBLISH, ACTION_HOLD, ACTION_PROMOTE = "PUBLISH", "HOLD", "PROMOTE"
DRIFT_EXCLUDED_FEATURES = frozenset(asof.TEMPORAL_FEATURES)
_ENTITY, _SEASON, _PERIOD, _COHORT = (
    PROJECT.entity_key,
    PROJECT.season_name,
    PROJECT.period_name,
    PROJECT.cohort_name,
)


def decide(
    *,
    contract_ok: bool,
    drift_status: str,
    promote_ok: bool,
    promote_reason: str = "",
    contract_failures: list[str] | None = None,
    drift_features: list[str] | None = None,
) -> tuple[str, list[str]]:
    """Pure policy: map step outcomes to (action, reasons)."""
    if not contract_ok:
        return ACTION_HOLD, [f"data contract failed: {', '.join(contract_failures or ['unknown'])}"]
    if drift_status == "hold":
        return ACTION_HOLD, [f"drift PSI > hold threshold on {', '.join(drift_features or [])}"]
    reasons = []
    if drift_status == "warn":
        reasons.append(f"drift warning on {', '.join(drift_features or [])}")
    if promote_ok:
        return ACTION_PROMOTE, reasons + [f"promotion rule satisfied: {promote_reason}"]
    return ACTION_PUBLISH, reasons + [
        "contracts ok, drift within limits",
        f"no promotion: {promote_reason}".rstrip(": "),
    ]


def _describe_failure(check: dict[str, Any]) -> str:
    d = check.get("detail") or {}
    if check["name"] == "freshness":
        exp = d.get("expected_through") or ["?", "?"]
        return f"freshness: no complete rows through {_SEASON} {exp[0]} {_PERIOD} {exp[1]}"
    if d.get("status") == "error":
        return f"{check['name']}: dbt error: {str(d.get('message') or '').strip()[:200]}"
    if d.get("failures"):
        return f"{check['name']}: {d['failures']} failing row(s)"
    return check["name"]


def rolling_path(season: int, artifacts: Path) -> Path:
    return artifacts / "eval" / f"rolling_{season}.json"


def read_rolling(season: int, artifacts: Path) -> dict[str, Any]:
    p = rolling_path(season, artifacts)
    return (
        json.loads(p.read_text(encoding="utf-8"))
        if p.exists()
        else {"season": season, "periods": []}
    )


def _weighted_test_mae(meta: dict[str, Any], candidate: str | dict[str, str]) -> float:
    num = den = 0.0
    for cohort in PROJECT.cohorts:
        c = meta["cohorts"][cohort]
        num += c["candidates"][registry.candidate_for(candidate, cohort)]["test_mae"] * c["n_test"]
        den += c["n_test"]
    return num / den


def _period_metrics(payload: dict[str, Any], history: pd.DataFrame) -> dict[str, Any] | None:
    rows = [
        {
            _ENTITY: r[PROJECT.entity_key],
            _SEASON: payload["season"],
            _PERIOD: payload["period"],
            _COHORT: r[PROJECT.cohort_name],
            "prediction": r["prediction"],
            "actual": r["actual"],
        }
        for r in payload["predictions"]
        if r.get("actual") is not None
    ]
    if not rows:
        return None
    enriched = evaluator.add_causal_baseline(rows, history.to_dict("records"))
    m = evaluator._metrics(enriched, "prediction")
    b = evaluator._metrics(enriched, "trailing_mean_baseline")
    return {
        "n": m["n"],
        "mae": m["mae"],
        "within_band1_rate": m["within_band1_rate"],
        "baseline_mae": b["mae"],
    }


def run_scheduled(
    *,
    artifacts: Path = ARTIFACTS_DIR,
    season: int | None = None,
    period: int | None = None,
    today: dt.date | None = None,
    dry_run: bool = False,
    write_model_card: bool = True,
) -> dict[str, Any]:
    now = dt.datetime.now(dt.UTC)
    run_id = f"run-{now:%Y%m%dT%H%M%SZ}"
    log: dict[str, Any] = {
        "run_id": run_id,
        "at_utc": now.isoformat(timespec="seconds"),
        "dry_run": dry_run,
        "steps": [],
    }

    def step(name: str, **info: Any) -> None:
        log["steps"].append({"step": name, **info})

    manifest = registry.read_manifest(artifacts / "manifest.json")
    champ_version, champ_cand = registry.slot(manifest, "champion")
    chall_version, chall_cand = registry.slot(manifest, "challenger")
    meta = registry.read_model_metadata(champ_version, artifacts)

    if season is None or period is None:
        season, period = loader.LOADER.current_period(today)
    log["season"], log["period"] = int(season), int(period)
    step("season_period", season=season, period=period)

    loaded = loader.load_period_rows(range(PROJECT.min_season, season + 1))
    rows = loaded[
        (loaded[_SEASON] < season) | ((loaded[_SEASON] == season) & (loaded[_PERIOD] < period))
    ].reset_index(drop=True)
    expected_through = (
        (season, period - 1)
        if period > 1
        else (season - 1, loader.LOADER.periods_in_season(season - 1))
    )
    prior_rows = (manifest.get("last_run") or {}).get("rows")
    report = contracts.run_silver_contracts(
        rows_path=loader.cache_path_for(loader.CACHE_NAME, range(PROJECT.min_season, season + 1)),
        target_season=season,
        target_period=period,
        expected_through=expected_through,
        prior_row_count=prior_rows,
    )
    report["summary"].update(
        {"rows": int(len(rows)), "entities": int(rows[_ENTITY].nunique()) if len(rows) else 0}
    )
    failures = [_describe_failure(c) for c in report["checks"] if not c["ok"]]
    step("rows", loaded_rows=int(len(loaded)), rows_before_target_period=int(len(rows)))
    step("contracts", ok=report["ok"], failures=failures, summary=report["summary"])
    contract_ok = report["ok"]

    drift_status, drift_feats, promote_ok, promote_reason = "skipped", [], False, "not evaluated"
    rolling = read_rolling(season, artifacts)
    if contract_ok:
        played = asof.training_frame(asof.build_features(rows))
        periods = played[[_SEASON, _PERIOD]].drop_duplicates().sort_values([_SEASON, _PERIOD])
        recent = periods.tail(drift.WINDOW_PERIODS)
        window = played.merge(recent, on=[_SEASON, _PERIOD])
        training_rows = played[played[_SEASON].isin(meta["seasons"]["train"])]
        drift_by_cohort, drift_full, worst = {}, {}, "ok"
        for cohort in PROJECT.cohorts:
            cm = meta["cohorts"][cohort]
            cand = registry.candidate_for(champ_cand, cohort)
            monitored = [
                f
                for f in cm["candidates"][cand]["top_feature_importance"]
                if f not in DRIFT_EXCLUDED_FEATURES and not f.endswith("_season_avg")
            ]
            sub = window[window[_COHORT] == cohort]
            ref, ref_meta = drift.reference_for_window(
                sub,
                cm["drift_reference"],
                training_rows[training_rows[_COHORT] == cohort],
                monitored,
            )
            rep = drift.drift_report(sub, ref, monitored, reference=ref_meta)
            drift_full[cohort] = rep
            drift_by_cohort[cohort] = {
                k: rep[k] for k in ("status", "median_monitored", "flagged", "severe", "n")
            }
            drift_by_cohort[cohort]["reference_mode"] = ref_meta["mode"]
            drift_feats += [f"{cohort}:{f}" for f in rep["flagged"]]
            if rep["status"] == "hold" or (rep["status"] == "warn" and worst == "ok"):
                worst = rep["status"]
        drift_status = worst
        drift_artifact = drift.run_report(
            run_id=run_id,
            at_utc=log["at_utc"],
            season=season,
            period=period,
            model_version=champ_version,
            status=drift_status,
            positions=drift_full,
        )
        if not dry_run:
            drift.write_run_report(drift_artifact, artifacts)
        if drift_status == "hold" and not drift.CALIBRATED:
            drift_status = "warn"
            step(
                "drift",
                status="warn",
                note="hold downgraded to warn: thresholds are not calibrated (eval.drift.CALIBRATED = False)",
                cohorts=drift_by_cohort,
            )
        else:
            step(
                "drift",
                status=drift_status,
                calibrated=drift.CALIBRATED,
                cohorts=drift_by_cohort,
                report=f"drift/{run_id}.json",
            )

        if drift_status != "hold":
            if period > 1:
                last_path = score.predictions_path(season, period - 1, artifacts)
                history = rows[
                    (rows[_SEASON] < season)
                    | ((rows[_SEASON] == season) & (rows[_PERIOD] < period - 1))
                ][[_ENTITY, _SEASON, _PERIOD, _COHORT, PROJECT.target_column]].rename(
                    columns={PROJECT.target_column: "actual"}
                )
                if last_path.exists():
                    last_payload = json.loads(last_path.read_text(encoding="utf-8"))
                    last_payload, n_attached = score.attach_actuals(last_payload, rows)
                    if not dry_run:
                        score.write_predictions(last_payload, artifacts)
                    champ_m = _period_metrics(last_payload, history)
                else:
                    n_attached, champ_m = 0, None
                shadow = score.score_period(
                    rows,
                    season,
                    period - 1,
                    model_version=chall_version,
                    candidate=chall_cand,
                    artifacts=artifacts,
                )
                shadow, _ = score.attach_actuals(shadow, rows)
                chall_m = _period_metrics(shadow, history)
                if champ_m and chall_m:
                    rolling["periods"] = [
                        w for w in rolling["periods"] if w["period"] != period - 1
                    ]
                    rolling["periods"].append(
                        {
                            "period": period - 1,
                            "n": champ_m["n"],
                            "champion": champ_m,
                            "challenger": chall_m,
                            "scored_at_utc": now.isoformat(timespec="seconds"),
                        }
                    )
                    rolling["periods"].sort(key=lambda w: w["period"])
                step(
                    "rolling_eval",
                    period=period - 1,
                    actuals_attached=n_attached,
                    champion=champ_m,
                    challenger=chall_m,
                )
            else:
                step(
                    "rolling_eval", period=None, note="first period of the season: nothing to score"
                )
            if not dry_run:
                rolling_path(season, artifacts).parent.mkdir(parents=True, exist_ok=True)
                rolling_path(season, artifacts).write_text(
                    json.dumps(rolling, indent=2) + "\n", encoding="utf-8"
                )
            promote_ok, promote_reason = registry.should_promote(
                [w["champion"]["mae"] for w in rolling["periods"]],
                [w["challenger"]["mae"] for w in rolling["periods"]],
                _weighted_test_mae(meta, champ_cand),
                _weighted_test_mae(meta, chall_cand),
            )
            step(
                "promotion_rule",
                promote=promote_ok,
                reason=promote_reason,
                periods_scored=len(rolling["periods"]),
            )

    action, reasons = decide(
        contract_ok=contract_ok,
        drift_status=drift_status,
        promote_ok=promote_ok,
        promote_reason=promote_reason,
        contract_failures=failures,
        drift_features=drift_feats,
    )
    if action == ACTION_PROMOTE:
        manifest["champion"], manifest["challenger"] = (
            {"model_version": chall_version, "candidate": chall_cand},
            {"model_version": champ_version, "candidate": champ_cand},
        )
        champ_version, champ_cand = chall_version, chall_cand
    if action in (ACTION_PUBLISH, ACTION_PROMOTE):
        payload = score.score_period(
            rows,
            season,
            period,
            model_version=champ_version,
            candidate=champ_cand,
            artifacts=artifacts,
        )
        if not dry_run:
            path = score.write_predictions(payload, artifacts)
            manifest["predictions"] = {"latest": str(path.relative_to(artifacts))}
        step("score", period=period, n=payload["n"], model_version=champ_version)

    if not drift.CALIBRATED:
        reasons.append(
            "drift thresholds are NOT calibrated (eval.drift.CALIBRATED = False): drift can warn but "
            "cannot HOLD; follow the calibration recipe in eval/drift.py"
        )
    log["action"], log["reasons"] = action, reasons
    log["drift_calibrated"] = drift.CALIBRATED
    manifest["last_run"] = {
        "run_id": run_id,
        "at_utc": log["at_utc"],
        "season": season,
        "period": period,
        "action": action,
        "reasons": reasons,
        "rows": int(len(rows)),
    }
    manifest["data_through"] = {
        "season": int(rows[_SEASON].max()),
        "period": int(rows[rows[_SEASON] == rows[_SEASON].max()][_PERIOD].max()),
    }
    if not dry_run:
        registry.write_manifest(manifest, artifacts / "manifest.json")
        if write_model_card and registry.evaluations(manifest):
            model_card.write_model_card(
                manifest, artifacts=artifacts, out_path=REPO_ROOT / "docs" / "MODEL_CARD.md"
            )
        runs = artifacts / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        (runs / f"{run_id}.json").write_text(json.dumps(log, indent=2) + "\n", encoding="utf-8")
    return log
