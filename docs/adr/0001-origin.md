# ADR-0001 — Origin: rendered from ds-dbt-stack-template, stripped, not copier-tracked (2026-09-19)

**Context.** The repository was rendered from the private copier template `ds-dbt-stack-template`
v0.2.3, a prediction-pipeline template (frozen scikit-learn model, FastAPI on a Hugging Face
Space, dbt on DuckDB / MotherDuck). This project has no model, no server and no cloud warehouse:
it consolidates public EV-charging session data from four operators into one tested dbt schema on
DuckDB. Two commits preceded this one: the raw render and "strip prediction pipeline, keep
chassis", which deleted the model, serving, scheduling and evaluation code. What remained still
referenced the deleted pieces: `make test` and `dbt parse` failed.

**Decision.**

1. *Not copier-tracked.* `.copier-answers.yml` was deleted with the strip. The template's
   vocabulary (entity / season / period / cohort / target) does not describe this project, so a
   future `copier update` would have nothing to replay onto. The template is an origin, not an
   upstream.
2. *Kept and reworked:* `pyproject.toml`, `constraints.txt`, `Makefile`, `.sqlfluff`,
   `.gitignore`, `ci.yml`, the dbt project / profile / packages files, the macros
   `generate_schema_name`, `export_gold`, `files_exist`, the generic test
   `row_count_within_pct_of_prior_period`, `scripts/check_dbt_descriptions.py`,
   `scripts/smoke.sh`, and the package modules `config.py`, `interfaces.py`, `data/loader.py`.
   The dbt `.yml` files were reduced to empty declarations with the layer conventions in comments;
   the models come back layer by layer from Phase 2.
3. *Deleted beyond the brief:* `ev_charging_data_unified_schema/data/contracts.py` and its test.
   The brief listed it as kept. Its whole purpose was to run `dbt build --select +tag:silver` for a
   scheduled scoring job and map failing silver tests to a HOLD verdict. This project's source
   contracts are a different design: a declared expected schema per source, compared per file
   against the landed columns, producing `artifacts/drift/<run_id>.json` with a warn / quarantine
   policy (brief § 5). Adapting the old module would have kept its shape and none of its meaning;
   it is rebuilt from scratch in Phase 2.
4. *MotherDuck target removed* from `dbt/profiles.yml`. One local DuckDB target serves local
   builds, CI and the full build ($0 runtime, brief § 3.1).
5. *Dependencies trimmed* to pandas, pyarrow, duckdb, pydantic, requests, rapidfuzz, dbt-core and
   dbt-duckdb, with the dev tools in an optional group. CI installs from `pyproject.toml` under
   `constraints.txt`; there is no second dependency list to maintain. pandas and pyarrow were
   added to the pins so landed parquet is byte-stable across machines.
6. *The idempotency test scaffold* (`tests/test_dbt_incremental.py`) keeps the template's dbt
   helpers and skips its one test until `fct_charging_session` exists (Phase 4).

**Consequences.** `make install && make test && dbt parse` pass on a project with no models.
`docs/ARCHITECTURE.md`, `docs/DATA_SOURCES.md` and `docs/REPRODUCIBILITY.md` still carry template
text and are marked as such at the top; they are rewritten in Phase 8. The full-build workflow,
Pages publishing and slim CI return in Phase 7. `make check-numbers` names a script that does not
exist until Phase 6 and is not wired into CI before then.
