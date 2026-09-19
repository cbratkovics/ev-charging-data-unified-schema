# EV charging data, unified schema

Public EV-charging session data from four operators, each published in a different shape,
consolidated into one tested, documented dbt schema on DuckDB, and used to produce a small set of
evidence-backed findings.

**Status: Phase 0 of 8 (chassis repaired).** No data has been downloaded yet, no model exists,
and no number in this repository describes real data. Every number that appears later will be
read from a committed artifact under `artifacts/` that records the run id, code commit, input
file hashes and metric definitions.

## Sources

| Source | Operator data | Period | Licence |
|---|---|---|---|
| Palo Alto, CA | city charging sessions | to be verified in Phase 1 | to be verified |
| Boulder, CO | city charging transactions | to be verified | to be verified |
| Cary, NC | town-owned station sessions | to be verified | to be verified |
| Dundee, UK | council charging sessions, annual files | to be verified | to be verified |
| Station registry | US / Canada reference dimension | n/a | to be verified |

`docs/DATA_SOURCES.md` records the exact URL, licence text, retrieval time, row count and
SHA-256 per source once downloaded.

## Run locally

```bash
make install     # uv venv + pinned toolchain (constraints.txt)
make test        # pytest, offline, on the hand-built fixture under tests/fixtures/
make dbt-parse   # dbt deps + parse
make lint        # ruff + black
```

## Design decisions

One file per decision under `docs/adr/`. `ADR-0001` records the origin of this repository
(rendered from a private prediction-pipeline template, stripped, not copier-tracked) and what
was deleted beyond the build brief.

## Limitations

- Nothing has been built past the chassis. This section is rewritten as each phase lands.

## Independence

This is an independent project on public open data. It contains no employer code, data,
schemas, vendor names, thresholds or business rules; all logic is derived from the public
sources named above and the reasoning recorded in this repository.
