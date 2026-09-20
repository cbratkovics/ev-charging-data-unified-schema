# Architecture

One Python package (`ev_charging_data_unified_schema/`), one dbt project (`dbt/`), committed
artifacts (`artifacts/`), committed exports (`exports/`), and two GitHub Actions workflows. No
hosted service: DuckDB files locally and in CI. The amended brief is `docs/BRIEF.md`; every
decision is an ADR under `docs/adr/`.

## Flow

```
publisher files ──(sources/*.py, acquire.py)──▶ data/raw/<source>/           git-ignored
   │ read as strings, contract check (data/contracts.py), drift artifact
   ▼
data/landed/<source>/*.parquet + manifest.json                                git-ignored
   │ dbt sources (external parquet)
   ▼
bronze  brz_<source>            string copy, names normalised, landing metadata
silver  slv_sessions__<source>  typed, UTC + local, durations, flags, all reasons, primary reason
        slv_sessions_unioned    accepted rows on the unified contract
        slv_sessions_quarantined
gold    meta_landed_files, fct_charging_session (incremental, source-level replace)
        int_station_gaps, dim_station, dim_operator, dim_date
        fct_station_day (spine + midnight split), mart_monthly
        snp_station (SCD2)
   │
   ├─▶ artifacts/  profile · drift · silver (with reconciliation) · sensitivity · findings
   ├─▶ exports/    station-day grain and above, Parquet (+ JSON for small relations)
   └─▶ docs/       PROFILE, CONTRACTS, FINDINGS and the README / CARD blocks, rendered
```

## Package modules

| Module | Responsibility |
|---|---|
| `config.py` | paths, the source list, the dbt vars mirror (checked by a test) |
| `interfaces.py` | the `SourceLoader` protocol and the manifest entry |
| `acquire.py` | polite cached HTTP downloads with conditional requests and a per-directory record |
| `sources/` | one loader per source: download, read raw as strings |
| `data/loader.py` | landing: string frames, row hashes, parquet, the landing manifest |
| `data/contracts.py` | per-source, per-family contracts; the drift policy; the drift artifact |
| `ingest.py` | the CLI that downloads, checks and lands, and writes `artifacts/drift/` |
| `profiling.py` | column profiling and the session helpers (hh:mm:ss, mixed timestamps, concurrency sweep, DST gaps) |
| `summaries.py` | the silver summary artifact (counts, flags, publisher rule) |
| `reconciliation.py` | the two identities and residual classification |
| `sensitivity.py` | utilization under every denominator definition |
| `findings.py` | the findings artifact (idle at full occupancy, DfT population table, ranges) |
| `exports.py` | the exports read contract |
| `compare.py` | fresh-versus-committed classification for the scheduled build |
| `citations.py` | the number checker's rules and resolver |

## Scripts, make targets, workflows

Scripts under `scripts/` are thin CLIs over the modules; `make help` lists the targets. The ones
that produce committed outputs: `profile`, `ingest` (drift), `silver-summary`, `sensitivity`,
`findings`, `export`, `render-docs`, `render-contracts`, `render-profile`; `release` runs them all
at one commit and prunes uncited artifacts. Checks: `check-numbers` (the citation checker plus
the rendered-doc checks), `check-docs` (every dbt column described), `lint`, `dbt-lint`, `test`.

`ci.yml` (push and pull request, offline): lint, description check, the fixture build (state-
selected on pull requests when the published manifest is reachable), pytest, the rendered-doc
and citation checks. `full-build.yml` (manual and monthly): real sources, full build, fresh
artifacts, comparison with the committed ones, issues, Pages; never commits (ADR-0015).

## Artifact contract

| Kind | Written by | Carries | Cited by |
|---|---|---|---|
| `artifacts/profile/` | `scripts/profile_sources.py` | per-file hashes and column profiles; the six profiling questions per source | `docs/PROFILE.md` (rendered), ADRs |
| `artifacts/drift/` | `ingest.py` | per-file contract outcome and findings | ADR-0008 |
| `artifacts/silver/` | `scripts/silver_summary.py` | accepted / quarantined by reason, flags, publisher rule, reconciliation identities and status, input hashes | README, findings, ADRs |
| `artifacts/sensitivity/` | `scripts/sensitivity.py` | utilization per denominator definition, over-100% counts | findings, ADRs |
| `artifacts/findings/` | `scripts/findings.py` | every number in `docs/FINDINGS.md` | FINDINGS, CARD, README |
| `exports/manifest.json` | `scripts/export.py` | rows, bytes, sha256 per exported file | `exports/SCHEMA.md` |

Each kind has a `latest.json`; `scripts/check_doc_numbers.py` resolves citations through it or
by run id; `scripts/prune_artifacts.py` keeps the current file and every file an ADR cites.

## dbt project

Schemas are exactly `bronze`, `silver`, `gold`, `snapshots` (macro `generate_schema_name`). Gold
contracts are enforced. Tests: unique and not-null on grain keys, relationships, accepted values,
row conservation per source and file, primary-reason completeness, ratio-of-sums versus mean of
daily ratios, spine completeness, grain mixing, measure conservation across the midnight split,
no unknown-station capacity; unit tests for parsing, DST, dedup, the midnight split and DST-day
minutes. Every model and column is described; `scripts/check_dbt_descriptions.py` enforces it.

## What is intentionally absent

An API or frontend (the exports are the read contract), a cloud warehouse, any language model in
the pipeline, any paid service, any secret. Cut scope is listed in ROADMAP.md.
