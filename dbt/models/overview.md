{% docs __overview__ %}

# ev_charging_data_unified_schema_dbt — analytics warehouse for Ev Charging Data Unified Schema

Consolidates five messy partner feeds into one tested dbt schema on DuckDB. This is the analytics layer: a bronze / silver / gold medallion built with dbt
Core and dbt-duckdb, DuckDB locally and in CI, MotherDuck in production, built by the scheduled
job after every scoring run. Every source is a file the repository already owns.

## Layers

**Bronze** (`brz_*`) — typed one-to-one copies of the source files; every row carries `source_file`.

**Silver** (`slv_*`) — conformed, deduplicated, grain-enforced; the data contracts are its tests.
`slv_period_rows` is incremental (delete+insert with a restatement lookback).

**Snapshot** (`snp_entity`) — SCD2 history of the entity dimension.

**Gold** — contracted marts the API and the site read: `dim_entity`, `dim_model_version`,
`fct_entity_period` (prediction, actual, error, causal baseline), `fct_period_eval` (metrics per
window / period / cohort), `fct_decision_policy` (versioned floor-policy sweep), plus the
snapshot-backed views `dim_entity_current` / `dim_entity_asof`.

## How trust is established

- **Artifact reconciliation.** `assert_marts_reconcile_to_eval_artifacts` recomputes n, MAE and
  the tolerance bands from `fct_period_eval` for every committed evaluation artifact and fails the
  build on any disagreement above 1e-4. The warehouse cannot publish a number the artifacts do
  not already carry.
- **Contracts** on every gold model; **unit tests** on the target rules, the prediction dedup rule
  and the metric aggregation; **versions** on the public decisions mart; **slim CI** on pull requests.

## From model to mart to API

scored-period file → `brz_predictions_periodic` → `slv_predictions` → `fct_entity_period` →
`fct_period_eval` / `fct_decision_policy` → `export_gold` → `artifacts/marts/<alias>.parquet` →
FastAPI `/marts/{mart}`. Evaluation numbers on the site come from `artifacts/eval/*.json` through
`/performance`; the reconciliation test is what lets the two paths coexist.

- Repository: https://github.com/cbratkovics/ev-charging-data-unified-schema
- API docs: https://-ev-charging-data-unified-schema.hf.space/docs

{% enddocs %}
