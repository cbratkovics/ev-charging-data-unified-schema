# EV charging data, unified schema

Public EV-charging session data from several operators, each published in a different shape and
each under an explicit open licence, consolidated into one tested, documented dbt schema on DuckDB,
and used to produce a small set of evidence-backed findings.

**Status: Phase 4 of 8 (gold).** The sources are downloaded, profiled (`docs/PROFILE.md`),
landed as string parquet, checked against their contracts (`docs/CONTRACTS.md`,
`artifacts/drift/`), copied into bronze, conformed in silver to one session contract with a
quarantine that keeps every failing reason (`artifacts/silver/`), and built into gold: a session
fact with source-level incremental replace, a station dimension with inferred ports and active
windows, an SCD2 snapshot, and a station-day fact on a full spine with the midnight split.
Utilization is a ratio of sums; its sensitivity to the capacity denominator is a committed
artifact (`artifacts/sensitivity/`). Reconciliation, findings and exports are not built yet; station-registry matching is not
built (ROADMAP.md). Every number that appears later will be
read from a committed artifact under `artifacts/` that records the run id, code commit, input
file hashes and metric definitions.

## Sources

| Source | Operator data | Period | Licence |
|---|---|---|---|
| Boulder, CO | city charging transactions | 2018-01 to 2023-11 | CC0 (item metadata) |
| Cary, NC | town-owned station sessions | 2012-04 to 2023-01 | CC0 1.0 (dataset metadata) |
| UK Department for Transport, 2017 | funded local-authority rapid and public-sector fast chargepoints | 2017 | Open Government Licence v3.0 |

`docs/DATA_SOURCES.md` records the exact URL, licence text, retrieval time, row count and
SHA-256 per source once downloaded.

## Run locally

```bash
make install      # uv venv + pinned toolchain (constraints.txt)
make test         # pytest, offline, on the hand-built fixture under tests/fixtures/
make dbt-fixture  # land the fixture and build the warehouse from it (offline)
make ingest       # download the real sources, land them, write the drift artifact (network)
make dbt-dev      # build the warehouse from the real landed data
make silver-summary sensitivity   # write the silver and denominator-sensitivity artifacts from it
make lint         # ruff + black
```

## Design decisions

One file per decision under `docs/adr/`. `ADR-0001` records the origin of this repository
(rendered from a private prediction-pipeline template, stripped, not copier-tracked) and what
was deleted beyond the build brief. `ADR-0002` records what is committed per source, by licence.
`ADR-0003` records that user-level fields never reach silver, gold or exports. `ADR-0004` records
the source policy: only sources with an explicit, verbatim open licence are used. `ADR-0005` to
`ADR-0007` record the session contract, the capacity denominator and the Phase 2 amendments;
`ADR-0008` the drift policy as built. `docs/BRIEF.md` is the amended build brief.

## Limitations

- Reconciliation, findings and exports do not exist yet; this section is rewritten as each phase lands.
- Port counts are lower bounds: the larger of the published connector-id count and the observed-concurrency robust max (ADR-0012); no station inventory or registry is used.
- DfT rows with no charge-point id are kept in session and energy totals under an unknown-station key but carry no capacity; their share is reported in the silver summary artifact (`unknown_station`).
- Utilization figures are not clipped at 100%; station-days above 100% are reported per denominator definition as a diagnostic of undercounted ports (ADR-0010 f).
- Energy and charging minutes of a session crossing midnight are allocated over a charging window assumed to begin at session start (ADR-0011 item 5); the sources do not publish when charging actually happened.
- Raw rows are not committed for any source (ADR-0002); reproducing the aggregates needs the live portals.
- Port counts are inferred from observed concurrency, not from an inventory; availability is assumed 24 hours a day within a station's active window. The inference undercounts ports that exist but were never used concurrently (biasing utilization upward) and overcounts where overlapping records are data errors (biasing it downward). Both directions are known and neither is measured (ADR-0006).
- The sources cover different years and countries (Cary 2012 to 2023, Boulder 2018 to 2023, UK DfT 2017); findings are within-operator unless the period mismatch is stated.
- Charging time and plug-in time are not both available from every source (ADR-0005); no figure imputes one from the other.

## Attribution

Contains public sector information licensed under the Open Government Licence v3.0.

## Independence

This is an independent project on public open data. It contains no employer code, data,
schemas, vendor names, thresholds or business rules; all logic is derived from the public
sources named above and the reasoning recorded in this repository.
