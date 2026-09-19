#!/usr/bin/env bash
# End-to-end smoke test of a freshly generated project. Exits non-zero on the first failure and
# prints the wall time of every step. Runs from the project root; needs uv, and node when the
# frontend is present.
set -euo pipefail
t0=$(date +%s)
step() { local s=$(date +%s); echo "== $1"; shift; "$@"; echo "   ($(( $(date +%s) - s ))s)"; }
step "install"            make install
step "incremental dbt tests with no dbt_packages present (the fixture installs them)" bash -c "test ! -d dbt/dbt_packages && .venv/bin/python -m pytest tests/test_dbt_incremental.py -q"
step "bootstrap (train + evaluate + score on the stub loader)" make bootstrap
step "pytest"             make test
step "lint"               make lint
step "dbt deps + build (dev)" make dbt-dev
step "dbt docs + description coverage + model-card lint" bash -c "make dbt-docs >/dev/null && make check-docs"
step "sqlfluff"           make dbt-lint
step "export gold marts (dev) + API contract tests over them" bash -c "make dbt-export DBT_TARGET=dev >/dev/null && .venv/bin/python -m pytest tests/test_api.py -q"
if [ -d frontend ]; then
  step "frontend npm ci"  bash -c "cd frontend && npm ci --silent"
  step "frontend lint + build" bash -c "cd frontend && npm run lint && NEXT_PUBLIC_API_URL=http://localhost:7860 npm run build"
fi
echo "SMOKE OK in $(( $(date +%s) - t0 ))s"
