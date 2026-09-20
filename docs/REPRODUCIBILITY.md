# Reproducibility

What is proven about this project's determinism, how to prove it again, and how the committed
artifacts relate to commits.

## Artifacts and commits

Every artifact under `artifacts/` and the exports manifest record `code_commit`: the commit of
the code that produced them. A release is two commits by construction: the code is committed
first, `make release` runs at that commit and regenerates every artifact, export and rendered
document (with one DuckDB thread and a full refresh, ADR-0016), and a second commit adds only
those generated files. So an artifact's `code_commit`
is always the commit *before* the release commit that contains it, and that commit differs from
the release commit only by generated files. `make release` refuses to start on a dirty tree so
every artifact of one release records the same commit.

Living documents cite `artifacts/<kind>/latest.json`, which names the current file; ADRs cite
the point-in-time file they were written against. `make release` prunes every artifact that is
neither current nor cited by an ADR (ADR-0013).

## What is deterministic, and the tests that prove it

- **Landing.** Files land as strings with a sha256 per row and per file; an unchanged file is a
  no-op on re-run (`tests/test_ingest.py`). Offline landings (the fixture, CI) pass a fixed
  `--retrieved-at`, so nothing derived from the landed files depends on the clock.
- **Warehouse content.** Two full builds of the same landed files produce content-identical
  gold tables and an identical SCD2 snapshot, validity columns included, because the snapshot's
  `updated_at` is the data's retrieval time rather than the wall clock
  (`tests/test_dbt_gold.py`, ADR-0011). Landing the sources in a different order changes
  nothing. A late re-delivery applied incrementally equals a full refresh.
- **Station attributes.** Where a station's sessions carry more than one site, name or
  operator, `dim_station` takes the value with the most sessions, ties broken by the value
  itself, and flags the station (`multi_site_key`, `multi_operator`); no `any_value`, `first`
  or unordered `row_number` remains in the project, and every window and pick ends in a unique
  key (ADR-0016). The fixture contains such a station and the test fails on a first-seen pick.
- **Dedup.** Every survivor choice ends with `_row_hash` as the final tie-break, preceded by the
  file name where two files can land the same content (ADR-0009, ADR-0016).
- **Exports.** Rows are written sorted by the grain key; two exports of the same warehouse are
  byte-identical (`tests/test_exports.py`), and the exports of two independent single-threaded
  builds of the same inputs are byte-identical for every exported relation, dimensions and the
  monthly mart included (`tests/test_dbt_gold.py`).
- **Timezone.** The dbt profile pins DuckDB's session `TimeZone` to UTC, and the ICU extension
  is statically linked in the pinned DuckDB wheel, so conversions are the same on every machine
  and need no network (`tests/test_duckdb_timezone.py`, ADR-0009).

## What is not byte-deterministic, and how to compare

DuckDB's parallel aggregation order is not deterministic: with more than one thread, two builds
of the same input differ at the 1e-15 level in floating aggregates. The profile reads
`EV_CHARGING_DATA_UNIFIED_SCHEMA_DUCKDB_THREADS` (default 4); set it to 1 for a reproducible
build, as the idempotency tests, the scheduled workflow and a release do. Compare key-sorted
content, never Parquet bytes, unless the file came from `scripts/export.py`, which sorts. Thread
count never changes a chosen value: only float summation order (ADR-0016).

```bash
export EV_CHARGING_DATA_UNIFIED_SCHEMA_DUCKDB_THREADS=1
make dbt-dev && python scripts/export.py --out /tmp/exports_before
# ... change something ...
make dbt-dev && python scripts/export.py --out /tmp/exports_after
diff <(cd /tmp/exports_before && sha256sum *.parquet) <(cd /tmp/exports_after && sha256sum *.parquet)
```

The reconciliation identities absorb the remaining float noise: kWh residuals within 1e-6
relative are classified `non_blocking`, exact row and session counts are required (ADR-0013). <!-- param -->

## Toolchain

`constraints.txt` pins dbt-core, dbt-duckdb, DuckDB, pandas and pyarrow; CI and `make install`
apply it. A DuckDB bump must be re-verified against `tests/test_duckdb_timezone.py` before the
pin moves.
