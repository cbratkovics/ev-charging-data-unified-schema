# Architecture

One Python package (`ev_charging_data_unified_schema/`), one dbt project (`dbt/`), one set of committed artifacts
(`artifacts/`), one FastAPI server that reads those artifacts, one scheduled GitHub Actions job
that refreshes them. The only
hosted service is MotherDuck's free tier, which holds the analytics warehouse; serving never
touches it.

## Modules

| Module | Responsibility | Key invariant |
|---|---|---|
| `config.py` | `PROJECT`: the one project configuration | dbt vars, the frontend config JSON and the workflow cron are mirrors checked by `tests/test_project_config.py` |
| `interfaces.py` | `SourceLoader`, `TargetSpec`, `FeatureModule` | satisfied by `data.loader.LOADER`, `target.TARGET_SPEC`, `features.asof` (`tests/test_interfaces.py`) |
| `data/loader.py` | the only data source; dated parquet cache | one row per grain; **stub** until replaced |
| `data/contracts.py` | runs `dbt build --select +tag:silver`, maps run results to the contract report | the checks are dbt tests; HOLD on any failure |
| `target.py` | target by explicit rules; reconcile against the published value | row-for-row reconciliation is a test |
| `features/asof.py` | **the** feature builder | every feature of row *t* uses rows strictly earlier within the entity |
| `models/train.py` | RF champion + GBM challenger per cohort, season split, intervals, drift reference | pipelines carry `feature_names_in_`; metadata records input sha256 + commit |
| `models/registry.py` | manifest I/O, slots, `should_promote` | deterministic promotion rule, unit-tested |
| `eval/evaluator.py` | forward holdout, causal baseline, rolling-origin folds, artifact 2.1 | every metric on the same rows; artifact carries hashes, commit, definitions |
| `eval/drift.py` | PSI per feature vs the training reference (bucket inside a season, matched across the boundary); `artifacts/drift/<run_id>.json` every run | thresholds uncalibrated by default; recipe in the module |
| `pipeline/scheduled.py` | the autonomous job | policy is pure Python (`tests/test_policy.py`) |
| `serve/app.py` | FastAPI reading `artifacts/manifest.json` | fails fast without a manifest; GET only |
| `serve/marts.py` | in-process DuckDB over `artifacts/marts/*.parquet` | versioned marts read at an explicit version |
| `dbt/` | bronze → silver → gold over the repo's own files | gold reconciles to `artifacts/eval/*.json` or the build fails |

## Artifact contract

| Path | Schema | Written by | Read by |
|---|---|---|---|
| `artifacts/manifest.json` | `schemas/manifest.schema.json` | evaluate, scheduled job | API, scheduled job |
| `artifacts/models/<v>/*.pkl`, `metadata.json`, `test_predictions.csv` | `schemas/model_metadata.schema.json` | `scripts/train.py` | evaluator, API, job |
| `artifacts/eval/<eval_id>.json` | `schemas/eval_artifact.schema.json` | `scripts/evaluate.py` | API `/performance`, model card, dbt |
| `artifacts/eval/rolling_<season>.json` | — | scheduled job | promotion rule, dbt |
| `artifacts/predictions/<season>/period_<pp>.json` | `schemas/predictions_file.schema.json` | scheduled job | API, dbt |
| `artifacts/drift/<run_id>.json` | `schemas/drift_report.schema.json` | scheduled job (every run with passing contracts) | anyone diagnosing a hold |
| `artifacts/marts/*.parquet`, `_export_manifest.json` | — | `dbt run-operation export_gold` (prod) | API `/marts/{mart}` |

## Analytics warehouse (dbt)

* Targets: `dev` = `.duckdb/dev.duckdb`; `prod` = MotherDuck `md:ev_charging_data_unified_schema`
  (`MOTHERDUCK_TOKEN`). Schemas are exactly `bronze`, `silver`, `gold`, `snapshots`.
* `slv_period_rows` is incremental (delete+insert, `rows_lookback_periods` restatement lookback,
  documented full-refresh policy; equivalence proven by `tests/test_dbt_incremental.py`).
* `snp_entity` (SCD2) feeds `dim_entity_current` / `dim_entity_asof` (`is_exact_asof`).
* `fct_decision_policy` is versioned: v1 served under the plain relation name, v2 additive with a
  reconciliation test for its artifact-shaped metric; the API pins `DECISIONS_MART_VERSION`.
* CI builds `dev` (full on `main`, `state:modified+ --defer` against the cached `main` build
  elsewhere); prod builds happen only in `scheduled.yml`. Toolchain pinned in `constraints.txt`.
* Reproducibility of exports: `docs/REPRODUCIBILITY.md`.

## What is intentionally absent

Redis, Celery, auth, payments, any language model, WebSockets, scraping, any paid API, and any
database on the serving path.
