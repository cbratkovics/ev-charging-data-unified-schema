# Build brief: ev-charging-data-unified-schema

The owner's build brief, as amended at each phase checkpoint. This is the working contract for
the project; every phase starts by re-reading it. The original brief was given on 2026-09-19;
amendments are logged at the bottom with their ADR ids. Where an amendment changed a section,
the section reads as amended and the log records what changed.

Environment: `~/Desktop/portfolio_projects/ev-charging-data-unified-schema`, Intel Mac, zsh,
VS Code, `uv`, Python 3.12. The `evidence-first-ml-pipeline` skill's working rules, claim
discipline and $0 cost rule apply; its modeling phases do not (there is no ML model).

## 1. What this repo is

A public portfolio project that consolidates **real, public EV-charging session data from
several operators, each published in a different shape and each under an explicit open
licence**, into one tested, documented dbt schema on DuckDB, and then uses that schema to
produce a small set of evidence-backed findings.

The point is engineering judgment under real mess: cleaning, standardizing, conforming grain,
controlling denominators, reconciling, and proving the result. It is not a tool showcase.

**Non-goals for v1:** no ML, no LLM, no API, no frontend, no Docker, no orchestrator, no cloud
warehouse, no synthetic data sources. Ideas outside this brief go in `docs/ROADMAP.md`.

## 2. Repository origin

Rendered from the private copier template `ds-dbt-stack-template` v0.2.3 and stripped; not
copier-tracked (ADR-0001). Conventions kept: bronze / silver / gold with `brz_`, `slv_`, `fct_`,
`dim_` prefixes; descriptions on every model and column (enforced by
`scripts/check_dbt_descriptions.py`); ADRs in `docs/adr/`; conventional commits.

## 3. Hard rules

1. **$0 runtime.** DuckDB + dbt-core (`dbt-duckdb`) locally and in GitHub Actions. No paid
   service, no managed database. The MotherDuck target was removed.
2. **Real data only.** The approved sources in section 4. The only non-real data allowed is a
   tiny hand-built **test fixture** under `tests/fixtures/`, used for unit and offline CI tests
   and labelled as such.
3. **Claim discipline.** No number appears in the README, docs, findings, or card copy unless it
   is read from a committed artifact under `artifacts/` that records run id, code commit, input
   file hashes, and metric definitions. This applies to `docs/PROFILE.md`, which is rendered
   from `artifacts/profile/<run_id>.json`. Living documents cite `latest.json` paths and ADRs
   cite point-in-time artifacts; number blocks are rendered between markers and prose numbers
   carry their key in an HTML comment; `scripts/check_doc_numbers.py` fails CI on an uncited,
   mismatched or dangling number in README, FINDINGS, CARD or the ADRs (ADR-0013).
4. **Licensing.** For every source, record the licence exactly as published, the URL where it
   was found, retrieval timestamp, row count, and SHA-256 in `docs/DATA_SOURCES.md`. Only commit
   raw or sampled rows from a source whose licence clearly permits redistribution; the current
   decision is to commit no rows from any source, only manifests and aggregates (ADR-0002).
5. **Source policy.** Only sources with an explicit, verbatim open licence are used. If a
   portal states no licence, record "unstated" and do not use the source; do not infer a
   licence from sibling datasets or a portal-wide assumption without citing the page that says
   so. Sources that fail this rule are removed entirely (ADR-0004).
6. **Independence guardrail.** This is an independent project. Nothing in the repository
   (code, names, comments, docs, commit messages) may contain employer-derived code, data,
   names, schemas, vendor names, thresholds or business rules of any kind. All logic derives
   from the public data and the reasoning documented here.
7. **No secrets in the tree.** The project reads no secret; `.env.example` says so and
   `.env*` is git-ignored.
8. **Personal data.** User-level fields (user ids, driver postal codes, vehicle details) are
   landed in bronze and never selected by silver, so they cannot reach gold or exports
   (ADR-0003). None of the approved sources carries any.
9. **Polite acquisition.** No parallel hammering of a portal, respect rate limits, cache
   downloads, never re-download an unchanged file.
10. **Phases with checkpoints.** One phase = one or more conventional commits, local only.
    **Never push**; the owner pushes. After each phase, stop and print a checkpoint (section
    9). Wait for the owner's go-ahead before the next phase. Before writing code in any phase,
    state the plan for that phase in a few lines and wait for the go-ahead.
11. **Depart loudly.** If this brief is wrong on the data, implement the better approach, write
    an ADR, and say so in the checkpoint. Silent deviation is the failure mode.
12. **No superlatives or unsupported claims** in any doc. Include an honest, specific
    Limitations section.
13. **Re-read this brief** at the start of every phase.

## 4. Data sources

Approved (ADR-0004). Endpoints, verbatim licences and retrieval records are in
`docs/DATA_SOURCES.md`; profiles in `docs/PROFILE.md`. Station-registry matching was cut
(ADR-0012; design in `docs/ROADMAP.md`).

| # | Source | Licence (verbatim source) | Period | Notes |
|---|---|---|---|---|
| 1 | Boulder, CO charging transactions (ArcGIS Hub item) | "CC0 License" linked to CC0 1.0, in the item metadata | 2018-01 to 2023-11 | One CSV holding two concatenated deliveries; wall-clock local timestamps in two formats; charging and total (plug-in) durations |
| 2 | Cary, NC town-owned station sessions (Opendatasoft) | `"license": "CC0 1.0 Universal"` in the dataset metadata | 2012-04 to 2023-01 | True UTC timestamps; charging duration only, no end time; station names only |
| 3 | UK Department for Transport, Electric Chargepoint Analysis 2017: Local Authority Rapids (revised) and Public Sector Fasts raw data, plus the two published incomplete-or-anomalous files | "All content is available under the Open Government Licence v3.0, except where otherwise stated" on both publication pages | 2017 | Four files with differing headers, date formats and duration units; plug-in duration only; connector ids on 44% of rows; wall-clock local timestamps |

Removed after Phase 1 (ADR-0004): Palo Alto, CA (no dataset-level licence; portal unreachable)
and Dundee, UK (licence unstated on every item). Deferred to `docs/ROADMAP.md`: Perth & Kinross,
Paris, Caltech ACN-Data.

## 5. Target design

### Ingestion (Python, in the package)

- One loader per source implementing the `SourceLoader` interface.
- Download to `data/raw/<source>/` (git-ignored) through the polite cached downloader.
- Write a manifest entry for each file: URL, retrieved_at, bytes, sha256, row count.
- Land as Parquet with **all columns as strings** plus `_source`, `_file_name`,
  `_retrieved_at`, `_row_hash`.
- Re-running with unchanged files is a no-op.

### Bronze

- One `brz_` model per source (or per file family), reading the landed Parquet as-is.
- No cleaning beyond column-name normalization.

### Source contracts and schema drift

- A declared expected schema per source (and per file family where files differ), rendered
  into `docs/CONTRACTS.md` with a cross-family diff table and a `--check` in CI (ADR-0009).
- On each run, compare actual columns and types per file against the contract and write
  `artifacts/drift/<run_id>.json`.
- Policy: a new unknown column produces a warning; a missing or retyped required column
  quarantines that file's batch with a reason code and the pipeline continues; a renamed
  column is handled through an explicit alias map recorded in the contract.
- Real drift to demonstrate: the four DfT headers differ, `PluginDuration` changes unit
  between files, dates change format, `Connector` gains text variants, and Boulder mixes two
  timestamp formats in one column.

### Silver

- `slv_sessions__<source>`: types, timestamp parsing, and timezone handling. Keep both UTC and
  station-local timestamps. Boulder and DfT are wall-clock local (proven on DST transition
  dates); Cary is true UTC (proven by the seasonal raw-hour shift). Fall-back ambiguity resolves
  to the second occurrence (standard time), which is what DuckDB's ICU conversion does, and is
  flagged `is_dst_ambiguous`; a nonexistent spring-forward time is a quarantine reason
  (ADR-0009).
- **All durations are computed from UTC after conversion.** Where a source publishes a
  duration, keep it as `*_reported`, record the disagreement, flag above a 2-minute tolerance
  (ADR-0005 a).
- **Duration availability is declared per source and never imputed** (ADR-0005 e): Cary
  `charging_only`, Boulder `both`, DfT `plug_in_only`.
- Units: energy in kWh, durations in minutes. Parse `HH:MM:SS` strings and numeric durations
  with their declared unit per file.
- Deduplicate on a documented natural key, null-safe on every key column, with every
  preference order ending in `_row_hash` so the survivor is deterministic (ADR-0009):
  - Boulder: (station name, start minute, end minute, energy), preferring the latest delivery
    block then the highest row id; a test asserts block 0 is a subset of block 1 (ADR-0005 b).
  - Cary: (station name, start second), keeping the larger charging time; conflicts are
    counted in the reconciliation artifact (ADR-0005 c).
  - DfT: (CPID, Connector, start minute, end minute, energy), preferring the raw file over the
    anomalies file. Rows with a null CPID get the station key `unknown/<Name>`; their share of
    sessions and energy is reported in the reconciliation artifact (ADR-0007).
- Row-level quality flags, including `publisher_excluded_rule` for DfT rows that meet the
  publisher's exclusion rule (zero energy or plug-in of 3 minutes or less), with the mismatch
  against the publisher's file split reported (ADR-0007). Zero-energy and over-24-hour rows
  are kept and flagged in every source.
- `slv_sessions_unioned`: every source conformed to one unified session contract (section
  5a).
- `slv_sessions_quarantined`: rejected rows with every failing reason in `quarantine_reasons[]`
  and one `primary_reason` by the fixed precedence blank_row, unparseable_timestamp,
  nonexistent_local_time, exact_duplicate, natural_key_duplicate, end_sentinel_1970,
  end_before_start, negative_energy, energy_sentinel, charging_exceeds_connected,
  implied_kw_over_ceiling (ADR-0009), so counts by primary reason sum to the total.
- Never drop rows silently. Accepted + quarantined must equal bronze, per source and per file.

### 5a. Unified session contract

One row per session: `session_sk`, `source`, `source_family`, `source_session_id`,
`source_file`, `source_delivery_block`, `station_key`, `station_name_raw`, `site_key`,
`port_id`, `port_id_present`, `start_utc`, `end_utc`, `start_local`,
`end_local`, `start_tz`, `is_dst_ambiguous`, `energy_kwh`, `charging_minutes`,
`connected_minutes`, `connected_minutes_reported`, `duration_disagreement_minutes`,
`idle_minutes`, `duration_availability`, `is_non_trivial`, `quality_flags[]`, `_row_hash`.

Implied-power ceilings for the `implied_kw_over_ceiling` reason: Cary 20 kW, Boulder 20 kW,
DfT rapids 55 kW, DfT fasts 30 kW (ADR-0007). `charging_exceeds_connected` allows the row's
`timestamp_precision_seconds`; rows within it are flagged and `idle_minutes` is clamped at zero
(ADR-0010 a). A committed silver summary artifact (`artifacts/silver/<run_id>.json`) records
accepted, non-trivial, quarantined by primary reason, flags, the unknown-station share and the
publisher-rule decomposition per source and file (ADR-0010 b, c).

### Gold

- `fct_charging_session`: grain is one session. Surrogate key, enforced contract,
  **incremental** on `session_sk`, driven by delivery metadata (new or changed landed files)
  plus a short event-time lookback, so a re-delivered file of old sessions is reprocessed
  exactly as a full refresh would (ADR-0010 d); proven by the fixture test.
- One **non-trivial session** rule, applied consistently across all sources at gold and used
  for utilization and findings: energy above zero and connected (or, where only charging is
  available, charging) time above 3 minutes (ADR-0007). Trivial sessions stay in the fact with
  `is_non_trivial = false`.
- `fct_station_day`: grain is station × station-local date. Sessions crossing midnight are
  split across days. Measures: sessions, energy_kwh, charging_minutes, connected_minutes,
  available_port_minutes. Available minutes are computed in station-local time, so DST
  transition days are 1,380 or 1,500 minutes (ADR-0010 e). Every row carries `capacity_grain`;
  rollups never mix grains (ADR-0005 d). Where a source lacks a duration type the measure is
  null, never zero, and rollups do not treat null as zero (ADR-0010 g).
- `dim_station` (with `capacity_grain`, `ports_inferred`, `ports_source`, `low_evidence`,
  `active_from`, `active_to`, `excluded_days`), `dim_operator`, `dim_date`.
- An **SCD2 snapshot** on station attributes.
- Utilization is a **ratio recomputed from summed numerator and denominator at whatever rollup
  is requested**, never an average of daily percentages; a singular test shows the two differ.
  Two flavours where the data allows: charging-time and connected-time utilization; their
  difference is idle-after-charge time.
- **Capacity denominator** (ADR-0006, ADR-0007, ADR-0012): `ports_inferred` is the larger of
  the published connector-id count and the robust max of observed concurrency (the highest
  level reached on at least N = 5 distinct days over the station's active life), floored at 1;
  both are lower bounds and `ports_source` names the binding one; stations with fewer than N
  active days carry `low_evidence`. The
  active window runs from first to last observed session minus zero-session gaps longer than
  the source's threshold (Boulder 30 days, DfT 90 days, Cary 30 days), with excluded days
  reported separately. A sensitivity artifact (`artifacts/sensitivity/<run_id>.json`) reports
  utilization under robust max at N in {1, 2, 3, 5, 10}, the original trailing-90-day rule
  and connector-id counts; findings state how sensitive each conclusion is.
  Utilization is not clipped at 100%; station-days above 100% are counted per denominator as a
  diagnostic of undercounted ports (ADR-0010 f).
  Model docs and the README state that port counts are inferred, availability is assumed 24
  hours, and both bias directions are known.
- One **versioned model** only if a genuine contract change arises; otherwise skip and say so.

### Reconciliation (in the silver summary artifact)

`artifacts/silver/<run_id>.json` carries a `reconciliation` section (ADR-0010 b, ADR-0013):
per source, overall and per month of the session's local start, two identities: (i) raw = fact
+ quarantined by primary reason, for rows and kWh on parsed values, with the DfT moved events
as a breakdown inside `natural_key_duplicate`; (ii) fact = counted in station-day measures +
trivial + unknown-station, for sessions and kWh, with `midnight_spill_kwh` as the documented
per-month term. Only the residual is compared with the tolerance (rows and sessions exact, kWh
within 1e-6 relative) and classified ok, non-blocking or blocking with a one-line
interpretation. A blocking residual fails the build. The same artifact carries the dedup
counts, the unknown-station share and the publisher-rule decomposition.

### Findings

`docs/FINDINGS.md`, rendered from `artifacts/findings/<run_id>.json`. Three to five findings,
within-source only, each stating its period, its artifact keys, its sensitivity range across
denominator definitions, what would change the conclusion, and what the data cannot show (no
queue or demand data, inferred ports, single-year DfT coverage). Written as: what was found,
why it matters, what I would tell the decision-maker, what would change my mind. The period
mismatch between sources is stated once, prominently. The Boulder idle finding reports the
headline idle share and the blocking idle share (idle minutes while every inferred port was
occupied), overall and by hour, and lets the smaller number lead (ADR-0013).

### Exports for a future frontend

`export_gold` writes small Parquet and JSON files with a documented schema to `exports/`. This
is the stable read contract. No frontend or API is built.

## 6. Tests

- **dbt:** unique and not-null on every grain key; relationships and accepted values; enforced
  contracts on gold; row-conservation test (bronze = accepted + quarantined); join-fanout test;
  the ratio-of-sums singular test; a grain-mixing test; source freshness where meaningful.
- **dbt unit tests:** duration parsing, timezone and DST conversion, day-first dates, midnight
  split, dedup, utilization rollup.
- **pytest:** loaders against the fixture; contract and drift policy branches; idempotency
  (build twice and assert byte-identical exported gold; load fixture files out of order and with
  a re-delivered overlapping file and assert the same result); reconciliation classification
  branches; README-number checker; assertions on the committed profile artifact.
- Everything in the default `make test` runs offline on the fixture.

## 7. CI (GitHub Actions, $0)

- `ci.yml` on push and PR: lint (ruff, sqlfluff), description check, pytest and `dbt build` on
  the fixture, the rendered-doc checks (profile, contracts, findings, README blocks), the
  number checker. On pull requests, when the published docs site serves `manifest.json`, the
  build is state-selected against it (`+state:modified+`) with no deferral (a local DuckDB file
  has no shared warehouse to defer to; ADR-0015); otherwise the full fixture build.
- `full-build.yml`, manual and monthly, never commits: restores the sources from `actions/cache`
  keyed on the input hashes in the committed latest silver artifact, refreshes them with
  conditional requests, runs the full `dbt build`, regenerates the artifacts into a scratch
  directory, compares them with the committed ones (upstream changed: informational issue with
  the file and row-count deltas; identical inputs but outputs beyond tolerance, or blocking
  reconciliation: regression issue and a failed run), uploads the fresh artifacts, publishes
  dbt docs and `manifest.json` to GitHub Pages. Releases are owner-run (`make release`).
- `exports/`: aggregates only (station-day grain and above), Parquet for every relation, JSON
  only for small ones, a 5 MB per-file ceiling, manifest with hashes, schema document with the
  OGL and source attribution (ADR-0015).
- The owner creates the remote, makes the repository public, enables Pages and runs the first
  full build; `docs/OWNER_TODO.md` lists the steps. No secrets are required.

## 8. Phases and definitions of done

| Phase | Work | Done when |
|---|---|---|
| 0. Repair the chassis | Dependencies, Makefile, `ci.yml`, dangling references, MotherDuck removed, README stub, ADR-0001 | `make install && make test && dbt parse` pass on an empty project. **Done 2026-09-19.** |
| 1. Acquire and profile | Endpoints, licences, hashes; `docs/PROFILE.md` rendered from a committed profile artifact; the six questions per source; personal-data check; stop and present the contract, the capacity denominator, the redistribution decision, source problems | The owner approves the contract. **Done 2026-09-19 (amended and re-approved the same day).** |
| 2. Bronze, contracts, drift | Loaders, manifest, bronze models, source contracts, drift artifact and policy | The drift artifact is committed and the policy branches are tested. |
| 3. Silver | Per-source conforming, union, quarantine, dbt unit tests | The row-conservation test passes on real data. |
| 4. Gold | Facts, dims, snapshot, midnight split, capacity, utilization, sensitivity artifact, incremental model, idempotency tests | Idempotency and ratio-of-sums tests pass. |
| 5. Registry matching | **Cut** (ADR-0012); design in `docs/ROADMAP.md` | n/a |
| 6. Reconciliation and findings | Reconciliation artifact, classification, `FINDINGS.md`, number checker | Every number in the docs resolves to an artifact key. |
| 7. CI and exports | The workflows, Pages docs, `exports/` contract | Workflows pass locally where possible (the make targets they call), and the owner TODO is written. |
| 8. Documentation | README (problem, sources table, lineage, design decisions linking ADRs, results table citing artifact keys, how to run, limitations, independence statement), `ARCHITECTURE.md`, `REPRODUCIBILITY.md`, `docs/ROADMAP.md`, `docs/CARD.md` (title, two-sentence summary, four or five "what this demonstrates" bullets, the stack, no number without an artifact key) | Docs complete and the number checker passes. |

## 9. Checkpoint format

```
PHASE <n> CHECKPOINT
Commits: <hashes and messages>
What changed: <bullets>
Tests: <commands run and results>
Numbers: <value -> artifact path and key>, or "none"
Departures from the brief: <ADR ids>, or "none"
Open questions for the owner: <numbered>
Next phase proposal: <one paragraph>
```

## Amendments

| Date | Phase | Amendment | ADR |
|---|---|---|---|
| 2026-09-19 | 0 | `contracts.py` deleted although listed as kept; MotherDuck target removed; dependencies trimmed; CI installs from `pyproject.toml` under `constraints.txt`, no `requirements.txt` | ADR-0001 |
| 2026-09-19 | 1 | Claim discipline extended to `docs/PROFILE.md`: rendered from `artifacts/profile/<run_id>.json`; licences captured verbatim with URLs, "unstated" never inferred; polite acquisition; registry pull deferred without a key; per-source personal-data check with user-level fields never reaching gold or exports | ADR-0002, ADR-0003 |
| 2026-09-19 | 1 (re-approval) | **Source policy**: explicit, verbatim open licence or nothing. Dundee and Palo Alto removed entirely; UK DfT Electric Chargepoint Analysis 2017 added after a mini Phase 1 | ADR-0004 |
| 2026-09-19 | 1 (re-approval) | Contract amendments: (a) durations from UTC with reported-value disagreement flags; (b) Boulder dedup prefers the latest delivery, subset test; (c) Cary UTC corroborated by the seasonal shift, dedup rule justified, conflicts reported; (d) `capacity_grain` on the station dimension; (e) duration availability declared per source, never imputed | ADR-0005 |
| 2026-09-19 | 1 (re-approval) | Capacity denominator: (f) robust max at N = 5 from the days-at-level distribution; (g) active window excludes gaps beyond a per-source threshold from inter-session gaps; (h) sensitivity artifact; (i) stated limitations on inferred ports, 24-hour availability and both bias directions | ADR-0006 |
| 2026-09-19 | 2 | Personal data confirmed none; DfT natural key approved, null-safe, `unknown/<Name>` share reported; publisher rule reproduced as a quality flag with mismatch reported; one non-trivial session rule at gold; port-count precedence (connector ids, else robust max N = 5, floored at 1, `low_evidence` flag); DfT implied-kW ceilings per family (rapids 55 kW, fasts 30 kW) | ADR-0007 |
| 2026-09-20 | 3 | Per-family drift design kept, with a generated contract-diff document; a `make release` target that regenerates every artifact at one commit; nonexistent local times quarantined and ambiguous ones resolved to DuckDB's second occurrence, verified empirically and pinned by a test; the ICU extension verified statically linked; every failing quarantine reason kept plus one primary reason by fixed precedence; every dedup order ends in `_row_hash` | ADR-0009 |
| 2026-09-20 | 3 (re-approval) / 4 | (a) charging tolerance from per-row timestamp precision with a within-tolerance flag and idle clamped at zero; (b) committed silver summary artifact; (c) decomposition of anomalies rows not meeting the publisher rule; (d) delivery-driven incremental merge; (e) local-time available minutes on DST days; (f) unclipped utilization with over-100% diagnostics; (g) null never zero for absent durations. Fall-back resolution kept as DuckDB's; reported-duration disambiguation to `docs/ROADMAP.md` | ADR-0010 |
| 2026-09-20 | 4 | Source-level replace instead of a merge, no event-time lookback, change detection by file hashes on fact rows; only the session fact is incremental; a station x local-date spine with rows for zero-session days; allocation over the charging window where charging time exists, else the connected window; deterministic snapshot validity via data_as_of_utc | ADR-0011 |
| 2026-09-20 | 4 (re-approval) / 5 | Ports = the larger of the connector-id count and the robust max (both lower bounds), `ports_source` = the binding bound; the fact's `capacity_grain` renamed `port_id_present` so the grain has one meaning on `dim_station`; unknown-station share reported in reconciliation and README; Phase 5 registry matching cut and every trace of the feature removed, design kept in `docs/ROADMAP.md` | ADR-0012 |
| 2026-09-20 | 6 | Two reconciliation identities in the silver summary (raw = fact + quarantined; fact = counted + trivial + unknown) with the moved DfT events as a breakdown inside natural_key_duplicate; living docs cite latest.json, ADRs cite point-in-time artifacts, release prunes uncited artifacts; number blocks rendered between markers with HTML-comment citations in prose; Boulder blocking idle by hour; every finding states what the data cannot show | ADR-0013 |
| 2026-09-20 | 6 (review) | Three coherence defects fixed: second-precision session ends in the gold SQL (Cary ports), the production definition inside every sensitivity range, one summing population table for the DfT anomalies file; coherence tests on the artifacts; "blocking idle" renamed idle at full occupancy, framed as an upper bound and split by single- and multi-port stations | ADR-0014 |
| 2026-09-20 | 7 | Scheduled build never commits and opens issues (upstream changed vs regression), monthly plus manual; cache key from the committed silver artifact's input hashes; slim CI by state selection without deferral; exports aggregates only with Parquet everywhere, JSON for small relations and a 5 MB ceiling; owner TODO covers the remote, the public repository, Pages, the first run and the labels | ADR-0015 |
| 2026-09-20 | pre-public | Rule 6 reworded to a generic independence guardrail (no employer-derived code, data, names, schemas, thresholds or business rules of any kind) | none |
| 2026-09-20 | 8 | README written for a two-minute read with badge, doc links, Mermaid lineage and a results block limited to utilization with range and reconciliation status; "what this demonstrates" in transferable terms; a corrections note; one sentence on AI-assisted, phase-gated construction; CARD with a generated block; ARCHITECTURE and REPRODUCIBILITY rewritten (artifact code_commit vs release commit stated once); docs swept for stale scope; owner TODO ends with tagging v0.1.0. No history scrub (decision recorded) | none |
