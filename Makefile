.PHONY: help install bootstrap train evaluate score scheduled test lint format api build dbt-deps dbt-dev dbt-state dbt-slim dbt-prod dbt-export dbt-docs dbt-lint check-docs frontend

PY ?= .venv/bin/python
PKG = ev_charging_data_unified_schema
DBT ?= .venv/bin/dbt
DBT_FLAGS = --project-dir dbt --profiles-dir dbt
DBT_TARGET ?= dev
# Reproducible warehouse builds: DuckDB's parallel aggregation order is not deterministic, so
# exports differ at the 1e-15 level between builds; set EV_CHARGING_DATA_UNIFIED_SCHEMA_DUCKDB_THREADS=1 when
# comparing exports (docs/REPRODUCIBILITY.md).

help:
	@echo "install    - create .venv and install training + dev dependencies (pinned toolchain)"
	@echo "bootstrap  - train + evaluate + score one period on the stub loader (creates artifacts/)"
	@echo "test       - pytest (offline; the stub loader is the fixture)"
	@echo "lint       - ruff + black --check"
	@echo "scheduled  - dry-run the scheduled scoring job"
	@echo "api        - run the API locally on :7860"
	@echo "dbt-dev    - dbt deps + build the medallion warehouse locally (.duckdb/dev.duckdb)"
	@echo "dbt-state  - save the last dev build as slim-build state in .dbt-state/"
	@echo "dbt-slim   - build only state:modified+ against .dbt-state, deferring the rest"
	@echo "dbt-prod   - dbt build against MotherDuck (needs MOTHERDUCK_TOKEN)"
	@echo "dbt-export - export gold marts to artifacts/marts/*.parquet (DBT_TARGET=dev|prod)"
	@echo "dbt-docs   - generate the static dbt docs site into dbt/target"
	@echo "check-docs - description coverage + model-card placeholder lint"

install:
	uv venv --python 3.12 .venv
	uv pip install --python $(PY) -c constraints.txt -r requirements-train.txt
	uv pip install --python $(PY) -e .

bootstrap: train evaluate score

train:
	$(PY) scripts/train.py

evaluate:
	$(PY) scripts/evaluate.py

# scoring runs the silver contracts through dbt, so the packages must be installed first
score: dbt-deps
	mkdir -p .duckdb
	$(PY) scripts/run_scheduled.py

scheduled: dbt-deps
	mkdir -p .duckdb
	$(PY) scripts/run_scheduled.py --dry-run

test:
	$(PY) -m pytest tests

lint:
	$(PY) -m ruff check $(PKG) tests scripts
	$(PY) -m black --check $(PKG) tests scripts

format:
	$(PY) -m black $(PKG) tests scripts

api:
	$(PY) -m uvicorn $(PKG).serve.app:app --host 127.0.0.1 --port 7860

build:
	docker build -t $(PKG)-api .

frontend:
	cd frontend && npm run dev

dbt-deps:
	$(DBT) deps $(DBT_FLAGS)
	@find dbt/dbt_packages -maxdepth 1 -type d -empty -delete

dbt-dev: dbt-deps
	mkdir -p .duckdb
	$(DBT) build $(DBT_FLAGS) --target dev

dbt-state:
	mkdir -p .dbt-state
	cp dbt/target/manifest.json .dbt-state/manifest.json
	cp .duckdb/dev.duckdb .dbt-state/dev.duckdb
	git rev-parse HEAD > .dbt-state/commit

dbt-slim: dbt-deps
	@test -f .dbt-state/manifest.json || (echo "no .dbt-state; run make dbt-dev && make dbt-state first" && exit 1)
	$(DBT) build $(DBT_FLAGS) --target dev --select state:modified+ --defer --state $(CURDIR)/.dbt-state

dbt-prod: dbt-deps
	$(DBT) build $(DBT_FLAGS) --target prod

dbt-export:
	mkdir -p artifacts/marts
	GITHUB_SHA=$${GITHUB_SHA:-$$(git rev-parse HEAD 2>/dev/null || echo '')} $(DBT) run-operation export_gold $(DBT_FLAGS) --target $(DBT_TARGET)

dbt-docs: dbt-deps
	$(DBT) docs generate $(DBT_FLAGS) --target dev --static

dbt-lint:
	.venv/bin/sqlfluff lint dbt/models dbt/tests dbt/macros dbt/snapshots

check-docs:
	$(PY) scripts/check_dbt_descriptions.py
	$(PY) scripts/check_model_card.py
