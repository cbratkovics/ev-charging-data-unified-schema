> **Template text.** This file still describes the prediction-pipeline template this repository was rendered from (docs/adr/0001-origin.md). It is rewritten in Phase 8; nothing in it describes the current project.

# Reproducibility of the warehouse exports

Three facts, learned the hard way on the source project, that decide how you prove "our numbers
match":

1. **DuckDB's parallel aggregation order is not deterministic.** With the default thread count,
   two builds of the *same* code over the *same* input differ at the 1e-15 .. 1e-13 level in every
   plain floating aggregate (`avg`, `sum`) and in the fsum-based causal baseline, which is enough
   to flip the sign of an error that is exactly on a tolerance band and to reorder a tie in a rank.
   dbt's own `--threads 1` does not help: it only bounds model concurrency.
2. **The fix is DuckDB's `threads` setting.** The dev profile reads it from
   `EV_CHARGING_DATA_UNIFIED_SCHEMA_DUCKDB_THREADS` (default 4). With `EV_CHARGING_DATA_UNIFIED_SCHEMA_DUCKDB_THREADS=1`
   two builds of the same code produce identical tables.
3. **Parquet bytes still differ between builds** (row order), so compare key-sorted content, not
   files.

## The proof recipe (behaviour-preserving refactors, template updates)

```bash
export EV_CHARGING_DATA_UNIFIED_SCHEMA_DUCKDB_THREADS=1
# before
git stash -u; make dbt-dev; dbt run-operation export_gold --project-dir dbt --profiles-dir dbt --args '{out_dir: /tmp/marts_before}'; git stash pop
# after
make dbt-dev; dbt run-operation export_gold --project-dir dbt --profiles-dir dbt --args '{out_dir: /tmp/marts_after}'
# compare key-sorted content
python - <<'PY'
import pandas as pd, hashlib, glob, os
def h(df, keys):
    d = df.sort_values(keys).reset_index(drop=True)[sorted(df.columns)]
    return hashlib.sha256(pd.util.hash_pandas_object(d, index=False).to_numpy().tobytes()).hexdigest()[:16]
for f in sorted(glob.glob("/tmp/marts_before/*.parquet")):
    n = os.path.basename(f); a = pd.read_parquet(f); b = pd.read_parquet(f"/tmp/marts_after/{n}")
    keys = [c for c in a.columns if c in ("station_id", "day", "day", "model_version", "candidate", "cohort", "min_floor", "eval_window")]
    print(n, "IDENTICAL" if h(a, keys) == h(b, keys) else "DIFFERENT")
PY
```

Also diff the compiled SQL (`dbt compile --target-path /tmp/compiled_before` / `_after`).

## What the reconciliation tests absorb

The artifact reconciliation tests compare to 1e-4 and allow "three rows" of disagreement on
exact-band ties for the baseline, which already covers the float noise of a normal parallel build.
Do not tighten those tolerances below the noise floor without setting the thread count.
