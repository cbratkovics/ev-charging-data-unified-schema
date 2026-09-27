# EV Charging Decision Lab

The Decision Lab is a static retrospective evidence interface planned for the repository's
`/lab/` route. It is not forecasting software and it does not report a measured intervention
effect. One Boulder population and period remain fixed while visitors select among capacity
definitions already present in the approved decision record.

## Read and trust boundaries

The browser loads `lab/data/latest.json`, then its local immutable record file, and checks the
schema/type, supported observation set, numeric and null-state contracts, pointer identity, and
SHA-256 in `lab/build-info.json`. This proves packaging consistency, not scientific correctness.
Python remains responsible for analytical identity and pinned-evidence validation; JavaScript does
not reproduce the interval algorithm or digest serializer.

`scripts/build_lab.py` requires canonical/public byte equality and copies only the app, pointer,
and selected immutable export. It replaces only `<output>/lab`; existing dbt documentation at the
output root is unchanged. Scheduled `fresh/` artifacts are never inputs. Build metadata separates
the site source commit (and dirty preview state) from each pinned analysis revision.

The UI shows stored ratios and exact components, capacity assumptions, concrete evidence keys,
lineage, the stable recommendation, and explicit **Not observed** action and **Not measured**
outcome. Downloads retain the original published bytes and filename. Loading, parsing, integrity,
contract, and null-state failures replace the presentation with an error and retry action.

## Local operation

```bash
make lab-build                         # validate and stage committed evidence in site/lab
make lab-serve                         # loopback-only preview of generated site/
node --test tests/lab-contract.test.js # pure guards and formatters; no browser download
npm ci
npx playwright install chromium
make lab-test                          # unit + staged-site Chromium desktop/mobile checks
```

For a combined fixture-docs preview, build the complete fixture warehouse and dbt docs, copy
`dbt/target/static_index.html` and `manifest.json` to `site/`, then run `make lab-build`. CI does
this before browser tests. The preview server exposes only generated `site/`, not the repository.

## Limitations

The selector chooses an existing observation; it neither reruns a model nor records an operator
action. Capacity is inferred. No queue, arrival, or turned-away-driver data exists, and charging
is assumed to begin at session start. Sensitivity is not a confidence interval. Current-lineage
links and pinned historical analysis links are labeled separately. Deployment, owner review, and
a live smoke check remain owner actions after merge.
