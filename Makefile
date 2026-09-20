.PHONY: help install test lint format fixture fixture-landed silver-summary sensitivity findings render-docs check-numbers prune-artifacts export compare profile render-profile check-profile render-contracts check-contracts release dbt-deps dbt-parse dbt-dev dbt-fixture dbt-state dbt-slim dbt-docs dbt-lint check-docs check-numbers ingest

PY ?= .venv/bin/python
PKG = ev_charging_data_unified_schema
DBT ?= .venv/bin/dbt
DBT_FLAGS = --project-dir dbt --profiles-dir dbt
# Reproducible warehouse builds: DuckDB's parallel aggregation order is not deterministic, so
# exports differ at the 1e-15 level between builds; set EV_CHARGING_DATA_UNIFIED_SCHEMA_DUCKDB_THREADS=1 when
# comparing exports (docs/REPRODUCIBILITY.md).

help:
	@echo "install       - create .venv and install the package + dev dependencies (pinned toolchain)"
	@echo "test          - pytest (offline; runs on the fixture under tests/fixtures/)"
	@echo "lint          - ruff + black --check"
	@echo "ingest        - download the real sources into data/raw/, land them as parquet, write the drift artifact (network)"
	@echo "fixture       - land the hand-built fixture CSVs into tests/fixtures/landed/ (offline; dbt builds read them)"
	@echo "fixture-landed - copy the landed fixture into data/landed so a dbt build with the default vars reads it (what ci.yml runs)"
	@echo "profile       - profile data/raw/ into artifacts/profile/<run_id>.json, then render the docs"
	@echo "check-profile - docs/PROFILE.md and the DATA_SOURCES inventory match the newest profile artifact"
	@echo "check-contracts - docs/CONTRACTS.md matches the contract definitions"
	@echo "release       - regenerate every published artifact in one run at one commit (network; clean tree required)"
	@echo "silver-summary - write artifacts/silver/<run_id>.json from the built dev warehouse"
	@echo "sensitivity   - write artifacts/sensitivity/<run_id>.json (denominator sensitivity) from the built dev warehouse"
	@echo "findings      - write artifacts/findings/<run_id>.json and render docs/FINDINGS.md"
	@echo "render-docs   - render the generated blocks of README.md and docs/CARD.md from the artifacts"
	@echo "prune-artifacts - keep only the latest artifact per kind plus those cited by an ADR"
	@echo "dbt-parse     - dbt deps + parse (no warehouse needed)"
	@echo "dbt-dev       - dbt deps + build the warehouse locally (.duckdb/dev.duckdb)"
	@echo "dbt-state     - save the last dev build as slim-build state in .dbt-state/"
	@echo "dbt-slim      - build only state:modified+ against .dbt-state, deferring the rest"
	@echo "export        - write exports/ (parquet, json for small relations, manifest with hashes, SCHEMA.md) from the built dev warehouse"
	@echo "compare       - compare fresh artifacts in FRESH_DIR with the committed latest ones (exit 0 ok, 2 upstream changed, 3 regression)"
	@echo "dbt-docs      - generate the static dbt docs site into dbt/target"
	@echo "dbt-lint      - sqlfluff over the dbt project"
	@echo "check-docs    - every dbt model, column, source and exposure has a description"
	@echo "check-numbers - every number in README / docs resolves to an artifact key"

install:
	uv venv --python 3.12 .venv
	uv pip install --python $(PY) -c constraints.txt -e ".[dev]"

test:
	$(PY) -m pytest tests

lint:
	$(PY) -m ruff check $(PKG) tests scripts
	$(PY) -m black --check $(PKG) tests scripts

format:
	$(PY) -m black $(PKG) tests scripts
	$(PY) -m ruff check --fix $(PKG) tests scripts

ingest:
	$(PY) -m $(PKG).ingest

fixture:
	$(PY) -m $(PKG).ingest --no-download --raw-dir tests/fixtures/raw --landed-dir tests/fixtures/landed --drift-dir .dbt-state/fixture-drift --retrieved-at 2026-01-01T00:00:00+00:00

# ci.yml serves the fixture from data/landed with the default vars so the slim-CI state comparison
# runs with the vars the production manifest was built with (ADR-0015 item 4). data/ is
# git-ignored, so it must be created here: on a fresh checkout it does not exist.
fixture-landed: fixture
	mkdir -p data
	rm -rf data/landed
	cp -R tests/fixtures/landed data/landed

profile:
	$(PY) scripts/profile_sources.py
	$(PY) scripts/render_profile.py

render-profile:
	$(PY) scripts/render_profile.py

check-profile:
	$(PY) scripts/render_profile.py --check

silver-summary:
	$(PY) scripts/silver_summary.py

sensitivity:
	$(PY) scripts/sensitivity.py

findings:
	$(PY) scripts/findings.py

render-docs:
	$(PY) scripts/render_docs.py

prune-artifacts:
	$(PY) scripts/prune_artifacts.py

export: dbt-docs
	$(PY) scripts/export.py

FRESH_DIR ?= fresh
compare:
	$(PY) scripts/compare_artifacts.py --fresh-dir $(FRESH_DIR)

render-contracts:
	$(PY) scripts/render_contracts.py

check-contracts:
	$(PY) scripts/render_contracts.py --check

# The release run (ADR-0009 item 2): every published artifact from one commit. Steps are added
# as the phases add artifacts (reconciliation, sensitivity, exports, findings).
release:
	@test -z "$$(git status --porcelain)" || (echo "release: working tree is not clean; commit first so every artifact records one code_commit" && exit 1)
	$(MAKE) ingest
	$(MAKE) profile
	$(MAKE) render-contracts
	$(MAKE) dbt-dev
	$(PY) scripts/silver_summary.py
	$(PY) scripts/sensitivity.py
	$(PY) scripts/findings.py
	$(MAKE) export
	$(PY) scripts/render_docs.py
	$(PY) scripts/prune_artifacts.py
	$(PY) scripts/check_doc_numbers.py
	@echo "release run complete at $$(git rev-parse --short HEAD); review and commit artifacts/ and docs/"

dbt-deps:
	$(DBT) deps $(DBT_FLAGS)
	@find dbt/dbt_packages -maxdepth 1 -type d -empty -delete

dbt-parse: dbt-deps
	$(DBT) parse $(DBT_FLAGS)

dbt-dev: dbt-deps
	mkdir -p .duckdb
	$(DBT) build $(DBT_FLAGS) --target dev

# the offline warehouse build CI runs: fixture landed files, scratch DuckDB, always a full refresh
dbt-fixture: dbt-deps fixture
	mkdir -p .duckdb
	EV_CHARGING_DATA_UNIFIED_SCHEMA_DUCKDB_PATH=.duckdb/fixture.duckdb $(DBT) build $(DBT_FLAGS) --target dev --vars '{landed_dir: tests/fixtures/landed}' --full-refresh

dbt-state:
	mkdir -p .dbt-state
	cp dbt/target/manifest.json .dbt-state/manifest.json
	cp .duckdb/dev.duckdb .dbt-state/dev.duckdb
	git rev-parse HEAD > .dbt-state/commit

dbt-slim: dbt-deps
	@test -f .dbt-state/manifest.json || (echo "no .dbt-state; run make dbt-dev && make dbt-state first" && exit 1)
	mkdir -p .duckdb
	$(DBT) build $(DBT_FLAGS) --target dev --select state:modified+ --defer --state $(CURDIR)/.dbt-state


dbt-docs: dbt-deps
	mkdir -p .duckdb
	$(DBT) docs generate $(DBT_FLAGS) --target dev --static

dbt-lint:
	.venv/bin/sqlfluff lint dbt/models dbt/tests dbt/macros dbt/snapshots

check-docs:
	$(PY) scripts/check_dbt_descriptions.py

check-numbers:
	$(PY) scripts/check_doc_numbers.py
	$(PY) scripts/findings.py --check
	$(PY) scripts/render_docs.py --check
