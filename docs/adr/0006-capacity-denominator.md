# ADR-0006 — Capacity denominator: robust max, active window, sensitivity (2026-09-19)

**Context.** No source publishes port counts. The Phase 1 proposal (a trailing-90-day maximum
concurrency with a "modal plus one" cap) was replaced by the owner's amendments (f–i). The
profile artifact now carries, per station key, the number of distinct local days on which each
concurrency level is reached (`answers.observed_concurrency.days_at_level`) and the distribution
of gaps between consecutive sessions (`answers.observed_concurrency.inter_session_gaps`).

**Decision.**

- **(f) Robust max.** `ports_inferred = max{k : concurrency k was reached on >= N distinct days}`
  over the station's active life, floored at 1. **N = 5.** <!-- param -->
  Evidence (`robust_max_histogram_by_n`, sessions of at least 5 minutes after dedup): <!-- param -->
  - Boulder: at N = 1 six station names reach 3 and 32 reach 2; at N = 5 one name reaches 3 and
    35 reach 2; at N = 10 the picture is the same (one at 3, 33 at 2). <!-- cite: artifacts/profile/profile-20260919T235137Z.json#sources.boulder.answers.observed_concurrency.days_at_level.robust_max_histogram_by_n.1.3; artifacts/profile/profile-20260919T235137Z.json#sources.boulder.answers.observed_concurrency.days_at_level.robust_max_histogram_by_n.1.2; artifacts/profile/profile-20260919T235137Z.json#sources.boulder.answers.observed_concurrency.days_at_level.robust_max_histogram_by_n.5.3; artifacts/profile/profile-20260919T235137Z.json#sources.boulder.answers.observed_concurrency.days_at_level.robust_max_histogram_by_n.5.2; artifacts/profile/profile-20260919T235137Z.json#sources.boulder.answers.observed_concurrency.days_at_level.robust_max_histogram_by_n.10.3; artifacts/profile/profile-20260919T235137Z.json#sources.boulder.answers.observed_concurrency.days_at_level.robust_max_histogram_by_n.10.2 -->
    Level 3 is reached on a median of 0 and a 90th-percentile of 1 day, level 2 on a median of 78 days. <!-- cite: artifacts/profile/profile-20260919T235137Z.json#sources.boulder.answers.observed_concurrency.days_at_level.days_at_level_quantiles["3"]["0.5"]; artifacts/profile/profile-20260919T235137Z.json#sources.boulder.answers.observed_concurrency.days_at_level.days_at_level_quantiles["3"]["0.9"]; artifacts/profile/profile-20260919T235137Z.json#sources.boulder.answers.observed_concurrency.days_at_level.days_at_level_quantiles["2"]["0.5"] -->
    N = 5 removes the one-day level-3 blips and keeps every dual-port unit.
  - DfT: at N = 1, 466 charge-point ids reach 2 and 25 reach 3; at N = 5, 330 reach 2 and 5 reach 3;
    at N = 10, 262 reach 2. <!-- cite: artifacts/profile/profile-20260919T235137Z.json#sources.dft_2017.answers.observed_concurrency.days_at_level.robust_max_histogram_by_n.1.2; artifacts/profile/profile-20260919T235137Z.json#sources.dft_2017.answers.observed_concurrency.days_at_level.robust_max_histogram_by_n.1.3; artifacts/profile/profile-20260919T235137Z.json#sources.dft_2017.answers.observed_concurrency.days_at_level.robust_max_histogram_by_n.5.2; artifacts/profile/profile-20260919T235137Z.json#sources.dft_2017.answers.observed_concurrency.days_at_level.robust_max_histogram_by_n.5.3; artifacts/profile/profile-20260919T235137Z.json#sources.dft_2017.answers.observed_concurrency.days_at_level.robust_max_histogram_by_n.10.2 -->
    Level 2 is reached on a median of only 2 days, so the inferred count for DfT is sensitive to N
    between 2 and 10. <!-- cite: artifacts/profile/profile-20260919T235137Z.json#sources.dft_2017.answers.observed_concurrency.days_at_level.days_at_level_quantiles["2"]["0.5"] -->
    That sensitivity is the reason for (h), and for DfT the `Connector` id gives a direct port
    count where present: 153,609 of 272,297 rows have none (`answers.port`); it was used in
    preference where present (superseded by ADR-0012: the larger of the two bounds). <!-- cite: artifacts/profile/profile-20260919T235137Z.json#sources.dft_2017.answers.port.rows_with_null_port_id; artifacts/profile/profile-20260919T235137Z.json#sources.dft_2017.answers.implausible.rows -->
  - Stations whose robust max is 0 (fewer than N distinct active days) get one port and the flag
    `ports_inferred_floor`.
- **(g) Active window.** A station is available from its first to its last observed session,
  minus any gap between consecutive sessions longer than the source's threshold. Threshold =
  the source's 99.9th percentile of inter-session gaps, rounded to the nearest 10 days:
  Boulder 30 days, DfT 90 days. <!-- param -->
  Boulder: p99.9 is 31.988 days; 66 gaps exceed the threshold; 25 station names have such a gap. <!-- cite: artifacts/profile/profile-20260919T235137Z.json#sources.boulder.answers.observed_concurrency.inter_session_gaps.quantiles_days["0.999"]; artifacts/profile/profile-20260919T235137Z.json#sources.boulder.answers.observed_concurrency.inter_session_gaps.gaps_over_days.30; artifacts/profile/profile-20260919T235137Z.json#sources.boulder.answers.observed_concurrency.inter_session_gaps.keys_with_a_gap_over_30d -->
  DfT: p99.9 is 91.837 days; 634 gaps exceed a month and 237 the threshold; 366 ids have a gap over a month. <!-- cite: artifacts/profile/profile-20260919T235137Z.json#sources.dft_2017.answers.observed_concurrency.inter_session_gaps.quantiles_days["0.999"]; artifacts/profile/profile-20260919T235137Z.json#sources.dft_2017.answers.observed_concurrency.inter_session_gaps.gaps_over_days.30; artifacts/profile/profile-20260919T235137Z.json#sources.dft_2017.answers.observed_concurrency.inter_session_gaps.gaps_over_days.90; artifacts/profile/profile-20260919T235137Z.json#sources.dft_2017.answers.observed_concurrency.inter_session_gaps.keys_with_a_gap_over_30d --> Cary has no end
  timestamps, so its gaps use start-to-next-start and the same rule. Excluded days are counted
  per station and per source in the reconciliation artifact and shown next to every utilization
  figure.
- **(h) Sensitivity artifact.** `artifacts/sensitivity/<run_id>.json` reports utilization per
  source (and per station where the finding is station-level) under: robust max at
  N in {1, 2, 3, 5, 10}; the original trailing-90-day max; DfT connector-id counts; and, once
  Phase 5 matches US stations, registry port counts for matched stations. Every finding states
  the range of its headline figure across these denominators, and a finding whose direction
  changes across them is not published.
- **(i) Stated limitations.** Model docs, the dbt overview and the README limitations say, in
  these words: port counts are inferred from observed concurrency, not from an inventory;
  availability is assumed 24 hours a day within the active window; <!-- param --> the inference undercounts
  ports that exist but were never used concurrently (biasing utilization upward) and overcounts
  where overlapping records are data errors (biasing it downward); both directions are known
  and neither is measured.

**Consequences.** `dim_station` gains `ports_inferred`, `ports_inferred_n`, `ports_source`
(`observed_concurrency` | `connector_ids` | `registry`), `active_from`, `active_to`,
`excluded_days`, and `capacity_grain` (ADR-0005 d). `fct_station_day.available_port_minutes` is
`ports_inferred * 1440` on active days and 0 on excluded days. <!-- param --> Phase 4 builds the sensitivity
artifact alongside the reconciliation artifact; Phase 6 findings cite both.
