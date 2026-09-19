# EV charging data, unified schema

Public EV-charging session data from four operators, each published in a different shape,
consolidated into one tested, documented dbt schema on DuckDB, and used to produce a small set of
evidence-backed findings.

**Status: Phase 1 of 8 (sources acquired and profiled).** Three of the four session sources are
downloaded and profiled (`docs/PROFILE.md`, rendered from `artifacts/profile/`); Palo Alto's
portal was unreachable. No warehouse model exists yet. Every number that appears later will be
read from a committed artifact under `artifacts/` that records the run id, code commit, input
file hashes and metric definitions.

## Sources

| Source | Operator data | Period | Licence |
|---|---|---|---|
| Palo Alto, CA | city charging sessions | not yet downloaded (portal 502) | unstated at dataset level; city use terms |
| Boulder, CO | city charging transactions | 2018-01 to 2023-11 | CC0 (item metadata) |
| Cary, NC | town-owned station sessions | 2012-04 to 2023-01 | CC0 1.0 (dataset metadata) |
| Dundee, UK | council charging sessions, annual files | 2021-07 to 2025-08 | unstated |
| Station registry | US / Canada reference dimension | n/a | "may be used for any purpose whatsoever" |

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
was deleted beyond the build brief. `ADR-0002` records what is committed per source, by licence.
`ADR-0003` records that user-level fields never reach silver, gold or exports.

## Limitations

- No warehouse model exists yet; this section is rewritten as each phase lands.
- Raw rows are not committed for any source (ADR-0002); reproducing the aggregates needs the live portals.
- Palo Alto could not be downloaded in Phase 1; its schema is unverified.

## Independence

This is an independent project on public open data. It contains no employer code, data,
schemas, vendor names, thresholds or business rules; all logic is derived from the public
sources named above and the reasoning recorded in this repository.
