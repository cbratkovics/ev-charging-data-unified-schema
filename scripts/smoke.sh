#!/usr/bin/env bash
# End-to-end smoke test from a fresh clone (ADR-0015, amendment of 2026-09-19).
#
# Clones this repository at HEAD into a temporary directory, overlays any uncommitted changes to
# tracked files and any untracked, non-ignored files (so the change you are about to commit is
# what gets tested), then installs, lands the fixture, builds the fixture warehouse the way
# ci.yml does, and runs the tests and lints there. Nothing git-ignored (data/, .duckdb/,
# .dbt-state/, .venv/, dbt/dbt_packages/) reaches the clone, which is the point: a step that
# depends on a directory that exists only on one machine fails here before it fails in CI.
#
# Exits non-zero on the first failure and prints the wall time of every step. Needs git and uv,
# and the network once for `dbt deps` and for uv to fetch the interpreter if it is not cached.
#
#   scripts/smoke.sh          # clone into a fresh temporary directory, removed on exit
#   KEEP=1 scripts/smoke.sh   # keep the clone for inspection (its path is printed at the end)
set -euo pipefail

src=$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel)
work=$(mktemp -d "${TMPDIR:-/tmp}/smoke.XXXXXX")
clone="$work/clone"
cleanup() {
  if [ "${KEEP:-0}" = 1 ]; then echo "clone kept at $clone"; else rm -rf "$work"; fi
}
trap cleanup EXIT

t0=$(date +%s)
step() { local s; s=$(date +%s); echo "== $1"; shift; "$@"; echo "   ($(( $(date +%s) - s ))s)"; }

echo "== clone $(git -C "$src" rev-parse --short HEAD) into $clone"
git clone --quiet "$src" "$clone"

# Uncommitted work is overlaid so the clone tests what the next commit will contain. Ignored
# files are never copied: that is what distinguishes this run from one in the working tree.
untracked=$(git -C "$src" ls-files --others --exclude-standard)
if ! git -C "$src" diff --quiet HEAD -- || [ -n "$untracked" ]; then
  echo "   working tree has uncommitted changes: overlaying them on the clone (ignored files stay behind)"
  git -C "$src" diff --binary HEAD -- | git -C "$clone" apply --allow-empty
  if [ -n "$untracked" ]; then
    (cd "$src" && printf '%s\n' "$untracked" | tar -cf - -T -) | tar -C "$clone" -xf -
  fi
fi

cd "$clone"
step "install"                                        make install
step "fixture landed into data/landed (ci.yml path)"  make fixture-landed
step "dbt build on the fixture (make dbt-fixture)"    make dbt-fixture
step "dbt build from data/landed, default vars (ci.yml)" \
  env EV_CHARGING_DATA_UNIFIED_SCHEMA_DUCKDB_PATH=.duckdb/fixture.duckdb \
  .venv/bin/dbt build --project-dir dbt --profiles-dir dbt --target dev --full-refresh
step "pytest"                                         make test
step "lint"                                           make lint
step "dbt parse"                                      make dbt-parse
step "sqlfluff"                                       make dbt-lint
echo "SMOKE OK in $(( $(date +%s) - t0 ))s (fresh clone at $clone)"
