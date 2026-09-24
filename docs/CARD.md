# EV charging data, unified schema

Three public charging-session sources arrived with incompatible schemas, timestamp rules and
data-quality failures. Source contracts, reason-coded quarantine and bronze / silver / gold dbt
models conformed them to one session grain while conserving accepted and rejected rows.

Utilization then required a ratio of summed charging or connected time to summed available time
from *inferred* port capacity—not an average of percentages. Because that capacity is a lower bound,
the result is an upper bound whose sensitivity to alternative denominator definitions is reported.
The analysis consequently supports targeted follow-up, not a claim of observed unmet demand.

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
- Boulder, CO, 2018-01-01 to 2023-11-30: 45.1% of connected time was idle after charging, but **up to 12.4% of connected time** was idle while every inferred port was occupied. These answer different questions: post-charge plug-in time versus its overlap with inferred full occupancy. Neither observes a queue, so even the smaller figure does not prove a driver was waiting.
- Within-source utilization only (different operators, places and periods; production port count; range across denominator definitions): Boulder, CO, 2018-01-01 to 2023-11-30, charging-time 6.2% (5.8% to 6.8%); Boulder, CO, 2018-01-01 to 2023-11-30, connected-time 11.4% (10.5% to 12.4%); Cary, NC, 2012-04-11 to 2023-01-03, charging-time 7.1% (6.1% to 7.4%); UK DfT chargepoint analysis 2017, 2017-01-01 to 2017-12-31, connected-time 8.7% (8.7% to 11.4%).
- Reconciliation: every source reconciles exactly on rows and sessions; status **non_blocking**.
- Rows: 440,575 landed, 357,606 accepted sessions, 82,969 quarantined with a primary reason each.
_Keys: `artifacts/findings/findings-20260920T194023Z.json` boulder_idle.production, utilization_ranges; `artifacts/silver/silver-20260920T194003Z.json` status, by_source._
<!-- generated:card end -->

## Stack

Python 3.12, pandas, DuckDB, dbt-core with dbt-duckdb, pytest, GitHub Actions, GitHub Pages.
No paid service, no managed database, no secrets.

## Links

Repository README for the two-minute version; `docs/FINDINGS.md` for the findings;
`docs/BRIEF.md` and `docs/adr/` for how the design was decided and amended.
