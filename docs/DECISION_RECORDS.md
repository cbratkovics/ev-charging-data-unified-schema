# Decision records

The first EV Charging Decision Lab contract is one retrospective case, not a general-purpose
decision system. It asks whether historical Boulder post-charge idle observations support an
operational intervention. The supported conclusion is narrower: investigate the possible
constraint and verify physical inventory and queue evidence before choosing an intervention.

## Contract and grain

`schema_version` **1.0.0** has one parent record per decision case, evidence identity, and policy
version. <!-- param --> `record_version` is a deterministic digest of the analytical payload. Capacity
definitions are identified child `observations`; they are not additional decisions and must not
be summed. `created_at_utc` is the real record creation time and is excluded from the analytical
identity. Rebuilding an existing version preserves its original creation time and content.

The digest includes every substantive field: the question and population, pinned evidence
identity, contract/metric/policy versions, observations and assumptions, recommendation and
reviewed alternatives, analytical conclusion, and action/outcome representation. It excludes only
`record_version` itself, `created_at_utc`, and the builder execution's
`repository_base_commit`. Validation recomputes this same projection before checking the pinned
artifact hashes and run identities.

The committed canonical record is under `artifacts/decisions/`; an identical compact public copy
is under `exports/decision_lab/`. Each directory has a mutable `latest.json` convenience pointer,
but the record itself stores resolved immutable evidence paths and SHA-256 hashes. Run
`make decision-records` to build and `make check-numbers` to validate the committed record. These
offline checks validate a committed real-data snapshot; they do **not** rerun the live-source
analysis.

## Metric and provenance path

The path is: public Boulder source and landing contract → dbt `fct_charging_session` plus
`dim_station` → external Python `full_occupancy_idle` interval sweep → pinned findings artifact →
reviewed recommendation → separate action and outcome statuses. `fct_station_day` does not
calculate full-occupancy idle, and dbt does not execute the Python step. The exposure names the two
actual dbt parents rather than implying a path through the monthly mart.

Every observation carries aggregate connected, idle, and full-occupancy idle minutes; explicit
units and population scope; component evidence keys; and three ratios. Ratios are calculated from
summed components with a null result for a zero denominator, never by averaging percentages. The
production capacity rule and only the supported robust-max alternatives are present. The
production-only single/multi-port split is intentionally absent from alternative observations.

The variation across capacity definitions is model-choice sensitivity, not a confidence interval
or a probability of constrained demand. Inferred single-port stations remain a visible limitation:
all of their idle minutes count as full-occupancy idle by definition. No session rows, station
picker, user identifiers, contact details, or row-level drill-through are published.

## Recommendation, action, and outcome

The recommendation is reviewed deterministic text, not LLM output. No supported capacity choice
observes a queue, so changing the assumption does not turn the recommendation into an idle-fee
claim. Policy alternatives are interpretations reviewed against evidence, not actions somebody is
claimed to have taken.

`action.status` is `not_observed`; `outcome.status` is `not_measured`. Their value fields are null,
not zero or “pending.” A later evidence-backed version may append an observed action or outcome,
but it must create a new immutable record rather than overwrite the original evidence and
recommendation.
