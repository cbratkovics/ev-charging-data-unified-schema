#!/usr/bin/env bash
# End-to-end offline smoke test from a clean checkout. Exits non-zero on the first failure and
# prints the wall time of every step. Runs from the project root; needs uv.
set -euo pipefail
t0=$(date +%s)
step() { local s=$(date +%s); echo "== $1"; shift; "$@"; echo "   ($(( $(date +%s) - s ))s)"; }
step "install"   make install
step "pytest"    make test
step "lint"      make lint
step "dbt parse" make dbt-parse
step "sqlfluff"  make dbt-lint
echo "SMOKE OK in $(( $(date +%s) - t0 ))s"
