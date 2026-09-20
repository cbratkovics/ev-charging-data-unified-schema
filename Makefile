.PHONY: help install test lint format fixture profile render-profile check-profile dbt-deps dbt-parse dbt-dev dbt-fixture dbt-state dbt-slim dbt-export dbt-docs dbt-lint check-docs check-numbers ingest

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
	@echo "profile       - profile data/raw/ into artifacts/profile/<run_id>.json, then render the docs"
	@echo "check-profile - docs/PROFILE.md and the DATA_SOURCES inventory match the newest profile artifact"
	@echo "dbt-parse     - dbt deps + parse (no warehouse needed)"
	@echo "dbt-dev       - dbt deps + build the warehouse locally (.duckdb/dev.duckdb)"
	@echo "dbt-state     - save the last dev build as slim-build state in .dbt-state/"
	@echo "dbt-slim      - build only state:modified+ against .dbt-state, deferring the rest"
	@echo "dbt-export    - export gold models to exports/ (parquet + json)"
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
	$(PY) -m $(PKG).ingest --no-download --raw-dir tests/fixtures/raw --landed-dir tests/fixtures/landed --drift-dir .dbt-state/fixture-drift

profile:
	$(PY) scripts/profile_sources.py
	$(PY) scripts/render_profile.py

render-profile:
	$(PY) scripts/render_profile.py

check-profile:
	$(PY) scripts/render_profile.py --check

dbt-deps:
	$(DBT) deps $(DBT_FLAGS)
	@find dbt/dbt_packages -maxdepth 1 -type d -empty -delete

dbt-parse: dbt-deps
	$(DBT) parse $(DBT_FLAGS)

dbt-dev: dbt-deps
	mkdir -p .duckdb
	$(DBT) build $(DBT_FLAGS) --target dev

# the offline warehouse build CI runs: fixture landed files, scratch DuckDB
dbt-fixture: dbt-deps fixture
	mkdir -p .duckdb
	EV_CHARGING_DATA_UNIFIED_SCHEMA_DUCKDB_PATH=.duckdb/fixture.duckdb $(DBT) build $(DBT_FLAGS) --target dev --vars '{landed_dir: tests/fixtures/landed}'

dbt-state:
	mkdir -p .dbt-state
	cp dbt/target/manifest.json .dbt-state/manifest.json
	cp .duckdb/dev.duckdb .dbt-state/dev.duckdb
	git rev-parse HEAD > .dbt-state/commit

dbt-slim: dbt-deps
	@test -f .dbt-state/manifest.json || (echo "no .dbt-state; run make dbt-dev && make dbt-state first" && exit 1)
	$(DBT) build $(DBT_FLAGS) --target dev --select state:modified+ --defer --state $(CURDIR)/.dbt-state

dbt-export:
	mkdir -p exports
	GITHUB_SHA=$${GITHUB_SHA:-$$(git rev-parse HEAD 2>/dev/null || echo '')} $(DBT) run-operation export_gold $(DBT_FLAGS) --target dev

dbt-docs: dbt-deps
	$(DBT) docs generate $(DBT_FLAGS) --target dev --static

dbt-lint:
	.venv/bin/sqlfluff lint dbt/models dbt/tests dbt/macros dbt/snapshots

check-docs:
	$(PY) scripts/check_dbt_descriptions.py

check-numbers:
	$(PY) scripts/check_doc_numbers.py
