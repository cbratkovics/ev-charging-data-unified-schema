{% docs __overview__ %}

# ev_charging_data_unified_schema_dbt

Consolidates three public EV-charging session sources (Boulder, CO; Cary, NC; the UK Department
for Transport's 2017 chargepoint analysis), each published in a different shape and each under an
explicit open licence, into one tested, documented schema on DuckDB. Every source is a file the
repository's own loaders landed; there is no managed database and no paid service.

## Layers

**Bronze** (`brz_*`) — one model per source, reading the landed parquet as-is: every column a
string plus `_source`, `_file_name`, `_retrieved_at`, `_row_hash`. No cleaning beyond
column-name normalization.

**Silver** (`slv_*`) — per-source conforming (types, timestamps in UTC and station-local time,
kWh and minutes), a documented natural-key dedup, row-level quality flags with every failing
reason kept and one primary reason by fixed precedence, then one unified session contract
(`slv_sessions_unioned`) and the rejected rows (`slv_sessions_quarantined`). Accepted +
quarantined = bronze, per source, enforced by a test.

**Snapshot** (`snp_station`) — SCD2 history of station attributes.

**Gold** — contracted facts and dimensions: `fct_charging_session` (one row per session,
incremental by source-level replace driven by the landed file hashes), `fct_station_day` (station
× station-local date on a full spine, sessions crossing midnight split across days),
`mart_monthly`, `dim_station` (ports inferred as the larger of two lower bounds, with the binding
bound recorded; site and operator by the majority of sessions, flagged when more than one value
existed), `dim_operator`, `dim_date`. Utilization is a ratio of summed numerator and
denominator at the requested rollup, never an average of daily percentages. `scripts/export.py`
writes the station-day-and-above relations to `exports/` (the read contract); session-grain rows
never leave the repository.

## How trust is established

- **Reconciliation**: the silver summary artifact (`artifacts/silver/<run_id>.json`, key
  `reconciliation`) records two identities per source and month, raw = fact + quarantined and
  fact = counted + trivial + unknown, on rows, sessions and kWh, with every residual classified
  ok, non-blocking or blocking. A blocking residual fails the release run.
- **Contracts** on every gold model; **dbt unit tests** on timestamp parsing, timezone / DST
  conversion, day-first dates and units, dedup, the midnight split and DST-day minutes;
  **pytest** on the utilization rollup, the incremental merge under re-delivery and the
  number checker.
- **Determinism**: two single-threaded builds of the same landed files are content-identical
  and export byte-identical files; no first-seen pick and no ordering without a unique final key
  exists in the project (ADR-0016).
- **Claims**: every number in the rendered docs resolves to a committed artifact key
  (`scripts/check_doc_numbers.py`, run in CI); the findings are rendered from their own
  artifact.

- Repository: https://github.com/cbratkovics/ev-charging-data-unified-schema

{% enddocs %}
