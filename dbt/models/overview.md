{% docs __overview__ %}

# ev_charging_data_unified_schema_dbt

Consolidates public EV-charging session data from several operators, each published in a different
shape and each under an explicit open licence, into one tested, documented schema on DuckDB. Every source is a file the repository's own
loaders landed; there is no managed database and no paid service.

## Layers

**Bronze** (`brz_*`) — one model per source, reading the landed parquet as-is: every column a
string plus `_source`, `_file_name`, `_retrieved_at`, `_row_hash`. No cleaning beyond
column-name normalisation.

**Silver** (`slv_*`) — per-source conforming (types, timestamps in UTC and station-local time,
kWh and minutes), a documented natural-key dedup, row-level quality flags, then one unified
session contract (`slv_sessions_unioned`) and the rejected rows with reason codes
(`slv_sessions_quarantined`). Accepted + quarantined = bronze, enforced by a test.

**Snapshot** (`snp_station`) — SCD2 history of station attributes.

**Gold** — contracted facts and dimensions: `fct_charging_session` (one row per session,
incremental with a lookback), `fct_station_day` (station × station-local date, sessions crossing
midnight split across days), `dim_station`, `dim_operator`, `dim_date`. Utilisation is a ratio of
summed numerator and denominator at the requested rollup, never an average of daily percentages.

## How trust is established

- **Row conservation**: bronze rows = silver accepted + quarantined, per source.
- **Reconciliation artifact**: `artifacts/reconciliation/<run_id>.json` records row counts per
  layer and kWh / session totals raw versus gold, with each variance classified
  release-blocking or non-blocking. A blocking variance fails the build.
- **Contracts** on every gold model; **unit tests** on duration parsing, timezone / DST
  conversion, day-first dates, the midnight split, dedup and the utilisation rollup.

- Repository: https://github.com/cbratkovics/ev-charging-data-unified-schema

{% enddocs %}
