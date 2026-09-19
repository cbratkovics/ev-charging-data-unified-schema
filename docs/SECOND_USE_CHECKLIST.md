# Second-use checklist — applying this template to a repository that already has code

Written for `nba-ai-ml`, the template's second use; valid for any repo with existing modelling
code. The template's first use was extracted from `fantasy-football-ai`, so the section at the
end lists where the two deliberately differ.

## A. Audit first (read-only, half a day)

1. Run the read-only audit from the `evidence-first-ml-pipeline` skill and commit it as `AUDIT.md`:
   canonical runtime path, every training script and what it writes, every data source and its
   licence, every published number and its origin, features and leakage, tests and CI, secrets.
2. Classify every module, model, workflow, page and doc as **Generic / Parameterizable / Domain**
   (the boundary-audit checklist in the skill). Anything Domain needs one of the three interfaces:
   `SourceLoader`, `TargetSpec`, `FeatureModule`.
3. Decide the vocabulary before generating: `entity_name`/`entity_key` (player / `player_id`),
   `period_name`, `season_name`, `cohort_name` and `cohorts` (position groups), `target_column`
   and units, the two tolerance bands, and `periods_per_season`.
   **Period grain for a nightly pipeline (nba-ai-ml):** the period must be an ordinal 1..N inside
   the season, not a date. Map game dates to day-of-season ordinals in the loader and keep the
   date as a context column; set `periods_per_season` to the largest number of game days a season
   can have (the key base becomes 1000). TEMPLATE_GUIDE.md § 2b has the details.
4. Grep for credentials before anything else. Remove from the tree; never rotate them yourself.

## B. Generate next to the old code, then move in

1. `copier copy <template> <repo>/` into the existing repository (answers as decided above);
   commit the generated tree on a branch before touching it.
2. Rescue the one real asset from the old code (usually a feature scheme or a scoring rule) into
   `<package>/data/loader.py`, `<package>/target.py`, `<package>/features/asof.py`. Everything
   else in the old tree is deleted, not migrated: a second feature module *will* drift.
3. Delete: old servers, notebooks with outputs, fixture metrics, scaffolding that does not
   produce or serve a prediction (auth, queues, vector stores), any README number.
4. Map old artifacts to the new schemas under `artifacts/schemas/`, or regenerate them; nothing
   old is served until it validates.
5. **Calibrate the drift thresholds** (`<package>/eval/drift.py`, recipe in the module docstring;
   TEMPLATE_GUIDE.md § 3): backtest the rule over **every** target period of the training seasons,
   including the first periods of a season where the window crosses the boundary, set the
   thresholds so normal windows do not hold, confirm it fires on a synthetic shift, write the
   counts as an ADR, flip `CALIBRATED`. Until you do, every scheduled run, the manifest, the model
   card and `check_model_card.py` say NOT CALIBRATED and the job cannot HOLD on drift.

## C. Before the first real claim

- [ ] `TargetSpec.reconcile` returns zero rows on the real source.
- [ ] `tests/test_features_no_leakage.py` passes on real rows.
- [ ] Split seasons are whole and forward in time; the test season is frozen.
- [ ] `make bootstrap` produced artifacts; the model card regenerates; `check_model_card.py` passes.
- [ ] `make dbt-dev` passes, including the artifact reconciliation.
- [ ] Drift thresholds calibrated (ADR, step B.5), or the README says the job cannot HOLD on drift.
- [ ] Secrets exist only as repository secrets; `.env.example` has placeholders.
- [ ] The out-of-sample season evaluation is scheduled for the first complete unseen season.

## D. Things the template names differently from fantasy-football-ai, and why

fantasy-football-ai was refactored behaviour-preservingly, so it kept every name its API,
contracts and artifacts already used; the template chose generic names. When you compare the two
repositories, these are deliberate, not drift:

| fantasy-football-ai | template | why |
|---|---|---|
| `within_3_rate` / `within_5_rate`, `within_3` / `within_5` | `within_band1_rate` / `within_band2_rate`, `within_band1` / `within_band2` with the band values in `PROJECT.within_k` | the band width is a variable; renaming in ffai would change API responses and contracts |
| `player_id`, `player_display_name`, `position` | `station_id`, `station_name`, `channel` (copier answers) | vocabulary is a variable |
| `season`, `week`, `week_%02d.json`, `weekly` source family, `period_key = season * 100 + week` | `day`, `day`, `period_<padded>.json`, `periodic`, `period_key = season * period_key_base + period` | period naming is a variable; the key base is the next power of ten above `periods_per_season`, so long seasons (game days) do not collide |
| `slv_player_stats`, `fct_player_week`, `fct_weekly_eval`, `fct_player_decisions` + `fct_decision_policy` | `slv_period_rows`, `fct_entity_period`, `fct_period_eval`, `fct_decision_policy` (decisions computed inside the policy mart) | model names are parameterised by role, not sport; the separate per-row decisions mart was a ffai product need |
| `positions` block in `metadata.json` | `cohorts` block | historical key kept in ffai |
| `xgb` challenger (XGBoost) | `gbm` challenger (scikit-learn HistGradientBoosting) | one fewer native dependency and no libomp quirk; swap back if you need XGBoost |
| scoring formats standard / half / PPR, `receptions_estimate`, `prediction_half` | none | domain: fantasy scoring rules; a second domain adds its own derived formats behind `TargetSpec` |
| dbt YAML `accepted_values` literals | rendered from the `cohorts` answer at copy time | ffai keeps literals guarded by the config-mirror test |
| `/marts/weekly_eval`, `/marts/player_week/{id}`, `/marts/decisions` | one generic `/marts/{mart}` with allowed equality filters | the template does not know which marts a product needs |
| `FFAI_*` env vars, `ffai_dev.duckdb` | `EV_CHARGING_DATA_UNIFIED_SCHEMA_*`, `dev.duckdb` | package name is a variable |
| ADR-0001…0021 inline in `docs/DECISIONS.md` | one file per ADR under `docs/adr/` from the start | ffai kept its history in place |
| drift thresholds 0.10 / 0.25 / 0.50, calibrated on nflverse backtests (ADR-0010) | same numbers as placeholders with `CALIBRATED = False` | thresholds are calibration output, never copied as fact |

## E. What to write about it

Only facts with evidence: the leakage test on real rows, the reconciliation of target rules to
the source, the artifact reconciliation in dbt, the incremental equivalence test with a restated
period, the reproducibility finding (thread count), the out-of-sample season. Each with the
commit and the `eval_id`.
