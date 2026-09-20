# EV charging data, unified schema

Three public operators' charging-session logs, published in three incompatible shapes,
conformed into one tested dbt schema on DuckDB with every rejected row kept and every published
number traceable to a committed artifact. The capacity denominator that utilization depends on
is inferred, bounded, and reported with its sensitivity instead of as a single figure.

## What this demonstrates

- Conforming differently shaped sources to one fact grain and one declared contract, with
  schema drift handled by policy (warn, quarantine, alias) rather than by surprise.
- Non-additive ratios rebuilt from summed numerator and denominator at every rollup, with a test
  that shows the averaged version differs on this data.
- Inferred capacity with its bias stated in both directions and a committed sensitivity artifact
  across every denominator definition.
- Idempotent incremental loads under re-delivery: a late file with a changed value and a vanished
  row yields exactly what a full refresh would.
- Row and kWh reconciliation with every residual classified, and claim discipline enforced by a
  CI checker that resolves each documented number to an artifact key.

## Headline figures

<!-- generated:card start -->
- Boulder: 45.1% of connected time is idle after charging; up to 12.4% of connected time is idle while every inferred port was occupied.
- Utilization by source (production port count; range across denominator definitions): boulder charging 6.2% (5.8% to 6.8%); boulder connected 11.4% (10.5% to 12.4%); cary charging 7.1% (6.1% to 7.4%); dft_2017 connected 8.7% (8.7% to 11.4%).
- Reconciliation: every source reconciles exactly on rows and sessions; status **non_blocking**.
- Rows: 440,575 landed, 357,606 accepted sessions, 82,969 quarantined with a primary reason each.
_Keys: `artifacts/findings/findings-20260920T022915Z.json` boulder_idle.production, utilization_ranges; `artifacts/silver/silver-20260920T022854Z.json` status, by_source._
<!-- generated:card end -->

## Stack

Python 3.12, pandas, DuckDB, dbt-core with dbt-duckdb, pytest, GitHub Actions, GitHub Pages.
No paid service, no managed database, no secrets.

## Links

Repository README for the two-minute version; `docs/FINDINGS.md` for the findings;
`docs/BRIEF.md` and `docs/adr/` for how the design was decided and amended.
