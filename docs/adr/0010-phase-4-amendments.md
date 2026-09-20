# ADR-0010 — Pre-Phase-4 items and Phase 4 amendments (2026-09-20)

**Context.** The owner approved Phase 3 with three items to close before Phase 4 (a–c) and
four amendments to the gold design (d–g). Numbers cite `artifacts/silver/<run_id>.json`
(the run id is in `artifacts/silver/latest.json`).

**Decision.**

- **(a) Tolerance from timestamp precision.** `charging_exceeds_connected` allows the row's
  own `timestamp_precision_seconds`: 60 on Boulder rows published as `M/D/YYYY H:MM`, 1 on
  rows published with seconds (Boulder ISO rows, Cary, DfT). A charging time that exceeds the
  computed connected time by no more than that is kept and flagged
  `charging_exceeds_connected_within_precision`; `idle_minutes` is clamped at zero. The
  global 2-minute tolerance of ADR-0009 item 7 is retired. Effect on the real data:
  `by_source.boulder.flags.charging_exceeds_connected_within_precision` rows flagged,
  `by_source.boulder.by_primary_reason.charging_exceeds_connected` quarantined.
- **(b) Silver summary artifact.** `scripts/silver_summary.py` writes
  `artifacts/silver/<run_id>.json` from the built warehouse: bronze, accepted, non-trivial,
  quarantined by primary reason, all reasons, flags and DST-ambiguous starts per source and
  per file; the unknown-station share; the publisher-rule counts; run id, code commit and the
  sha256 of every landed input. It is part of `make release`. Phase 6 adds reconciliation
  sections to this artifact rather than creating a competing one. ADR-0009's numbers now
  point at its keys.
- **(c) Decomposition of anomalies rows not meeting the publisher rule.** Recorded under
  `publisher_rule.anomalies_not_meeting_rule.<family>`: rows quarantined here for another
  reason (by reason), rows whose natural key also appears in a raw file (for
  `rapids_anomalies`, the fast-charger events the revision moved to the fasts publication),
  and rows accepted with no explanation.
- **(d) Delivery-driven incremental.** `fct_charging_session` is incremental on
  `session_sk` with a `merge` strategy, and the rows to (re)process are selected by delivery
  metadata: sessions from any landed file whose sha256 differs from the one recorded at the
  previous build (kept in a small `meta_landed_files` model built from the landing manifest),
  plus a short event-time lookback for safety. A re-delivered file of old sessions is
  therefore fully reprocessed; an event-time lookback alone would miss it. The fixture
  idempotency test lands a late re-delivery of old sessions and asserts the incremental
  result equals a full refresh.
- **(e) Available minutes in station-local time.** `available_port_minutes` for a
  station-day is `ports_inferred` times the number of minutes in that local date: 1,440 on
  ordinary days, 1,380 on the spring-forward day and 1,500 on the fall-back day, computed
  from the UTC instants of local midnight to the next local midnight. A dbt unit test covers
  both transition days.
- **(f) Utilization is not clipped.** Ratios above 100% are kept; the sensitivity artifact
  counts station-days above 100% under every denominator definition as a diagnostic of
  undercounted ports.
- **(g) Null, never zero.** Where a source lacks a duration type the measure is null;
  rollups use `sum` (which ignores nulls) and expose the count of contributing rows so a
  null-heavy rollup is visible; no `coalesce(..., 0)` on a measure.

**Consequences.** The silver contract gains `timestamp_precision_seconds`. Gold gains
`meta_landed_files`. `docs/BRIEF.md` § 5 and § 5a are amended accordingly.
