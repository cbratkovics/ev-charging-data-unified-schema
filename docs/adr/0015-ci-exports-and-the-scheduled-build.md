# ADR-0015 — CI, the exports read contract, and a scheduled build that never commits (2026-09-20)

**Context.** Brief § 7 asked for an offline CI workflow, a scheduled full build over the real
sources, slim CI on pull requests, and an `exports/` read contract. The owner amended the plan
with five points before Phase 7.

**Decision.**

1. **The scheduled full build never commits.** `full-build.yml` runs monthly and on demand.
   It refreshes the sources with conditional requests (`ingest --refresh` sends
   `If-None-Match` / `If-Modified-Since` where the publisher gave them, so an unchanged file
   costs one 304 and a changed one is actually detected), builds the warehouse, regenerates
   the silver summary, sensitivity and profile artifacts into a scratch directory, compares
   them with the committed latest ones, uploads the fresh artifacts, publishes the dbt docs
   site (with `manifest.json`) to GitHub Pages, and opens an issue when something needs the
   owner. Releases are owner-run: `make release`, review, commit.
2. **Two kinds of drift.** `scripts/compare_artifacts.py` (pure logic in `compare.py`, tested
   per branch) classifies a run from the input hashes recorded in the silver summary
   artifacts: (a) `upstream_changed`: the input hashes differ from the committed ones, so
   upstream data changed; the workflow opens an informational issue "New source data
   available" listing each changed file and its row-count delta, and output differences are
   not judged; (b) `regression`: the input hashes are identical but an output differs beyond
   tolerance (counts exact; kWh, utilization and shares within 1e-6 relative), or the fresh
   reconciliation status is blocking; the workflow opens a "Full build regression" issue with
   the differing keys and fails. Labels are created with `--force` before `gh issue create`
   so the step never depends on repository setup.
3. **The source cache key comes from a committed file.** The landing manifest is
   git-ignored, so `scripts/source_cache_key.py` hashes the input sha256s recorded in the
   committed latest silver artifact; `actions/cache` restores `data/raw` and `data/landed`
   under that key, with a prefix fallback, before the conditional refresh.
4. **Slim CI without deferral.** On pull requests `ci.yml` downloads `manifest.json` from the
   published docs site and, when it is there, runs `dbt build --select +state:modified+
   --state .dbt-state` on the fixture target with a full refresh: the models whose definition
   changed against production, plus their ancestors, are built and tested. There is no
   `--defer`: deferral rewrites unmodified refs to relations in the state's warehouse, which
   needs a warehouse shared between the state and the build; a local DuckDB file built from
   the fixture has no such warehouse, so deferral does not apply. When the manifest is not
   reachable (no Pages yet, or the site is down) the job falls back to the full fixture build
   it always ran. One empirical rule: the comparison must run with the same vars the state
   manifest was built with. Against an identical manifest, passing the fixture's `landed_dir`
   var flagged three silver models as modified with no code change (none of dbt's
   `state:modified.*` sub-selectors explained it); with the default vars nothing was flagged.
   So CI copies the fixture's landed files into `data/landed` and builds with the default
   vars, which is also what the production manifest describes. <!-- scratch -->
5. **`exports/` holds aggregates only.** `scripts/export.py` writes every gold relation whose
   dbt meta says `export: true`: `fct_station_day`, `mart_monthly` (source × operator × month),
   `dim_station`, `dim_operator`, `dim_date`. Session-grain relations (`fct_charging_session`,
   `meta_landed_files`, `int_station_gaps`) carry `export: false` and the exporter refuses any
   relation outside its grain table. Parquet (zstd, rows sorted by the grain key) for every
   relation; JSON only where `export_json: true` (the dims and the monthly mart). The exporter
   is Python rather than a dbt macro so the output is deterministic (a test asserts two
   exports of the same warehouse are byte-identical) and the manifest can carry sha256 per
   file. `exports/manifest.json` records run id, code commit, rows, bytes and sha256;
   `exports/SCHEMA.md` documents every column from the dbt manifest and carries the OGL
   attribution statement and the per-source licence table (ADR-0002).
6. **Size ceiling: 5 MB per file.** The largest relation, `fct_station_day`, is 1.7 MB as
   zstd Parquet with 306,091 rows; the ceiling leaves about three times that for growth and
   keeps the repository light. <!-- scratch -->
   `tests/test_exports.py` fails on any file over the ceiling, on a session-grain relation,
   on a manifest hash that does not match the file, and on JSON for a large relation.
7. **CI stays offline.** `ci.yml` adds nothing that needs the network except the optional
   manifest download; the exports test runs on the fixture warehouse.

**Owner TODO** (docs/OWNER_TODO.md): create the GitHub remote and push; make the repository
public (GitHub Pages on a free plan needs a public repository); enable Pages with source
"GitHub Actions"; run `full-build.yml` once by hand; expect the two issue labels
`new-source-data` and `full-build-regression` to be created by the first run that needs
them. No secrets are required.

**Consequences.** The template's `export_gold` macro and `make dbt-export` are removed. The
brief's § 7 wording (weekly schedule, `--defer`) is replaced by this ADR. `exports/` is committed
and regenerated by `make release`.

**Amendment (2026-09-19): the first CI run on a fresh runner failed, and the local smoke test
had not caught it.** The "dbt build on the fixture" step ran an inline
`cp -r tests/fixtures/landed data/landed`, and `cp` could not create `data/landed` because
`data/` does not exist on a fresh checkout: it is git-ignored and had only ever existed on the
owner's machine, where `make ingest` had created it. `scripts/smoke.sh` ran from the owner's
working tree with only `.venv` deleted, so every ignored directory the workflow needed was
already in place and the gap was invisible locally.

Decision. (a) The copy moves into the Makefile as `make fixture-landed`, which creates `data/`
first; `ci.yml` calls that target instead of an inline `cp`. Every other target that writes into
a git-ignored directory creates it first: `dbt-dev`, `dbt-fixture`, `dbt-slim` and `dbt-docs`
create `.duckdb/` (DuckDB creates the database file but not its parent directory), `dbt-state`
creates `.dbt-state/`, and the Python entry points create their own output directories
(`ingest` for `data/raw/`, `data/landed/` and the drift artifacts; the artifact scripts for
`artifacts/<kind>/` and any `--out` scratch directory; the exporter for `exports/`;
`compare_artifacts.py` now creates the parent of `--report` and `--issue-body`). The scheduled
workflow already created its `fresh/` and `site/` scratch directories. (b) Local smoke tests
start from a clean clone. `scripts/smoke.sh` clones the repository at HEAD into a temporary
directory, overlays uncommitted changes to tracked files and untracked non-ignored files so the
next commit is what gets tested, then runs install, the fixture landing into `data/landed`, the
fixture build both as `make dbt-fixture` and in the shape `ci.yml` runs it, the tests and the
lints there. Nothing git-ignored can reach the clone, so a step that depends on a directory that
exists only on one machine fails locally before it fails in CI. The rule for the owner's routine:
a smoke run in the working tree proves nothing about CI; run `scripts/smoke.sh` before pushing
workflow or Makefile changes.
