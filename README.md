# EV charging data, unified schema

Public EV-charging session data from several operators, each published in a different shape and
each under an explicit open licence, consolidated into one tested, documented dbt schema on DuckDB,
and used to produce a small set of evidence-backed findings.

**Status: Phase 6 of 8 (reconciliation and findings).** The sources are downloaded, profiled
(`docs/PROFILE.md`), landed as string parquet, checked against their contracts
(`docs/CONTRACTS.md`, `artifacts/drift/`), copied into bronze, conformed in silver to one session
contract with a quarantine that keeps every failing reason, and built into gold: a session fact
with source-level incremental replace, a station dimension with inferred ports and active
windows, an SCD2 snapshot, and a station-day fact on a full spine with the midnight split.
Utilization is a ratio of sums; its sensitivity to the capacity denominator is a committed
artifact (`artifacts/sensitivity/`). Two reconciliation identities are checked per source and
month in the silver summary artifact (`artifacts/silver/`), and the findings
(`docs/FINDINGS.md`) are rendered from their own artifact. Exports, CI workflows and the
portfolio card are described in `docs/OWNER_TODO.md`; the exports read contract is `exports/SCHEMA.md`.

## Sources

| Source | Operator data | Period | Licence |
|---|---|---|---|
| Boulder, CO | city charging transactions | 2018-01 to 2023-11 | CC0 (item metadata) |
| Cary, NC | town-owned station sessions | 2012-04 to 2023-01 | CC0 1.0 (dataset metadata) |
| UK Department for Transport, 2017 | funded local-authority rapid and public-sector fast chargepoints | 2017 | Open Government Licence v3.0 |

`docs/DATA_SOURCES.md` records the exact URL, licence text, retrieval time, row count and
SHA-256 per source once downloaded.

## Results

<!-- generated:results start -->
_Rendered by `scripts/render_docs.py` from `artifacts/silver/silver-20260920T022854Z.json` and `artifacts/sensitivity/sensitivity-20260920T022855Z.json` and `artifacts/findings/findings-20260920T022915Z.json`._

| Source | Raw rows | Sessions in the fact | Quarantined | Non-trivial sessions | Stations with capacity | Utilization (production port count) |
|---|---|---|---|---|---|---|
| boulder | 148,136 | 77,826 | 70,310 | 68,297 | see below | charging 6.2%, connected 11.4% |
| cary | 20,142 | 20,097 | 45 | 17,733 | see below | charging 7.1% |
| dft_2017 | 272,297 | 259,683 | 12,614 | 228,439 | see below | connected 8.7% |

Stations with inferred capacity: 908 (1 ports: 409, 2 ports: 394, 3 ports: 105); binding bound: connector_ids 262, floor 46, observed_concurrency 600. Excluded days: 28,861 of 306,091 station-window days.

Reconciliation status: **non_blocking** (both identities per source and month; ADR-0013).
<!-- generated:results end -->

Findings, each within one source with its period, artifact keys, sensitivity range and what the
data cannot show: [docs/FINDINGS.md](docs/FINDINGS.md).

## Run locally

```bash
make install      # uv venv + pinned toolchain (constraints.txt)
make test         # pytest, offline, on the hand-built fixture under tests/fixtures/
make dbt-fixture  # land the fixture and build the warehouse from it (offline)
make ingest       # download the real sources, land them, write the drift artifact (network)
make dbt-dev      # build the warehouse from the real landed data
make silver-summary sensitivity   # write the silver (with reconciliation) and sensitivity artifacts
make findings     # write the findings artifact and render docs/FINDINGS.md
make export       # write exports/ (aggregates only) from the built warehouse
make release      # everything above in one run at one commit (network; clean tree required)
make check-numbers # every measured number in README, FINDINGS, CARD and the ADRs resolves to an artifact key
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
- Utilization figures are not clipped at 100%; station-days above 100% are reported per denominator definition as a diagnostic of undercounted ports (ADR-0010 f). <!-- param -->
- Energy and charging minutes of a session crossing midnight are allocated over a charging window assumed to begin at session start (ADR-0011 item 5); the sources do not publish when charging actually happened.
- Raw rows are not committed for any source (ADR-0002); reproducing the aggregates needs the live portals.
- Port counts are inferred from observed concurrency, not from an inventory; availability is assumed 24 hours a day within a station's active window. <!-- param --> The inference undercounts ports that exist but were never used concurrently (biasing utilization upward) and overcounts where overlapping records are data errors (biasing it downward). Both directions are known and neither is measured (ADR-0006).
- The sources cover different years and countries (Cary 2012 to 2023, Boulder 2018 to 2023, UK DfT 2017); findings are within-operator unless the period mismatch is stated.
- Charging time and plug-in time are not both available from every source (ADR-0005); no figure imputes one from the other.

## Attribution

Contains public sector information licensed under the Open Government Licence v3.0.

## Independence

This is an independent project on public open data. It contains no employer code, data,
schemas, vendor names, thresholds or business rules; all logic is derived from the public
sources named above and the reasoning recorded in this repository.
