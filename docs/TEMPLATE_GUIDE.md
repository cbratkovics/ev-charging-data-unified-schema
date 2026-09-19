# Template guide

This project was generated from `ds-dbt-stack-template` with copier. Answers are in
`.copier-answers.yml`; never edit generated values by hand where a variable exists — change the
answer and re-run `copier update`.

## 1. First run (no real data yet)

```bash
make install && make bootstrap && make test && make dbt-dev
```

`bootstrap` trains, evaluates and scores one period on the **stub loader** (a deterministic
synthetic world), which is enough to prove the whole path: artifacts, model card, warehouse,
API. Nothing produced this way is a claim; the README says so until you replace the loader.

## 2. Replacing the stub loader

`ev_charging_data_unified_schema/data/loader.py` must keep the `SourceLoader` contract (`ev_charging_data_unified_schema/interfaces.py`):

1. `ID_COLUMNS` starts with `station_id`, `station_name`, `channel`,
   `day`, `day`, `team`; `STAT_COLUMNS` are the raw numeric columns and
   end with the published target `utilization`.
2. `load_period_rows(seasons)` returns one row per grain, sorted, stat columns float64, cached as
   dated parquet under `data/cache/period_rows_<first>-<last>_<date>.parquet` (dbt reads that file).
3. `current_period()` comes from the source's calendar, not the clock.
4. Rewrite `target.py` (`derive`, `REQUIRED_COLUMNS`) from the source's documented rules and the
   SQL twin `dbt/macros/target_rules.sql` (`stat_columns()` too). Both are reconciled row for row
   against the published target by tests; a non-empty disagreement is a stop.
5. Update `features/asof.py` if some stats are meaningless for some cohorts
   (`features_for_cohort`); bump `FEATURE_VERSION`.
6. Set the split seasons and `periods_per_season` in `config.py`; regenerate the mirrors
   (`python -m ev_charging_data_unified_schema.config --frontend > frontend/src/lib/project.config.json`) and update
   the `min_season` / `periods_per_season` vars in `dbt/dbt_project.yml`.
7. Update `dbt/models/bronze/_sources.yml` and `_bronze.yml` for your stat columns, and the
   `expect_table_columns_to_contain_set` list in `_silver.yml`.
8. Write `docs/DATA_SOURCES.md`, delete the "stub" notes in the README, and only then run
   `make bootstrap` again to produce the first real artifacts. Commit them.

Delete `artifacts/` from the synthetic run before the first real training; the manifest is
rebuilt by `scripts/evaluate.py`.

## 2b. The period grain (read this for a nightly / game-date pipeline)

Everything downstream orders time by `(season, period)` where **period is an ordinal 1..N within
the season**: the scheduled job scores period `p` and evaluates period `p - 1`, the incremental
lookback counts distinct periods, `period_key = season * period_key_base + period` is the
monotonic integer the warehouse windows over, and files are `period_<zero-padded>.json`.
`period_key_base` is the next power of ten above `periods_per_season` (the copier answer, also in
`config.py` and `dbt/dbt_project.yml`), so a 200-game-day season gets base 1000 and never collides.

For a date-grained source (one row per entity per game date): in the loader, map each calendar
date to its day-of-season ordinal (1 = the season's first game day) as the period column, keep
the calendar date as a context column, set `periods_per_season` to the maximum number of game
days a season can have, and make `current_period()` return the next ordinal from the source's
schedule. Nothing else changes. Do not put `YYYYMMDD` in the period column: `p - 1` must be the
previous scoring period.

## 3. Calibrating the drift rule

The reference is hybrid: the training-time period-of-season bucket while the window sits inside
one season, and the training seasons' rows at the window's own period positions when the window
crosses a season boundary (`eval/drift.py::reference_for_window`; `MATCH_ACROSS_BOUNDARY`,
`MIN_REFERENCE_ROWS`). Every run writes `artifacts/drift/<run_id>.json` with the per-feature PSI
and the reference it used, so a hold can be diagnosed from the repository, not from a log.

`ev_charging_data_unified_schema/eval/drift.py` ships with `CALIBRATED = False`; the scheduled job downgrades a
drift HOLD to WARN until you flip it. Follow the recipe in the module docstring: backtest the rule
over every `WINDOW_PERIODS`-period window of the training seasons, count how many *normal*
windows it would hold, set the thresholds so that number is zero (or a documented handful),
confirm it fires on a synthetic shift, write the counts as an ADR, flip the flag. Until then the
run log, the manifest's `last_run.reasons`, the model card's limitations and
`scripts/check_model_card.py` all say NOT CALIBRATED on every run, on purpose.

## 4. Deployment (all free tiers)

- **MotherDuck**: create the database `ev_charging_data_unified_schema`; add `MOTHERDUCK_TOKEN` as a repository secret.
- **Hugging Face Space** `/ev-charging-data-unified-schema` (Docker SDK, port 7860); add `HF_TOKEN` (write) as a secret; run `ci.yml` with `deploy_space=true` once.
- **GitHub Pages**: Settings → Pages → Source: GitHub Actions; the dbt docs publish on every push to `main`.
- Trigger `scheduled.yml` once by hand (dry run first).

## 5. `copier update`

```bash
uvx copier update --trust          # pulls template changes, replays your answers, 3-way merges
```

Conflicts land as `.rej` files next to the affected file; resolve, run `make test && make dbt-dev`,
commit. Files you have replaced wholesale (the loader, `target.py`, `DATA_SOURCES.md`) will
conflict on every template change to them; keep your version and delete the `.rej`.

## 6. Reproducibility proofs

`docs/REPRODUCIBILITY.md`: DuckDB thread count and key-sorted content hashes, not file bytes.
