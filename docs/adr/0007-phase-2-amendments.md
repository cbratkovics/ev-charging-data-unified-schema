# ADR-0007 — Phase 2 amendments: natural key, publisher rule, non-trivial sessions, port precedence, DfT ceilings (2026-09-19)

**Context.** The owner approved the amended Phase 1 checkpoint and answered its open questions
with five changes before Phase 2. Numbers below are from
`artifacts/profile/profile-20260919T235137Z.json` (code commit b6841cd) unless a scratch
computation is named.

**Decision.**

1. **DfT natural key, null-safe.** The session key for the DfT files is (`CPID`, `Connector`,
   start minute, end minute, energy). `Connector` is null on 153,609 of 272,297 rows and `CPID` on 6,136. <!-- cite: artifacts/profile/profile-20260919T235137Z.json#sources.dft_2017.answers.port.rows_with_null_port_id; artifacts/profile/profile-20260919T235137Z.json#sources.dft_2017.answers.implausible.rows; artifacts/profile/profile-20260919T235137Z.json#sources.dft_2017.answers.stations.null_ids -->
   So key comparison treats null as a value equal to itself
   (DuckDB `IS NOT DISTINCT FROM`; in Python, a sentinel token in the hashed key). Rows with a
   null `CPID` get the station key `unknown/<Name>`; they are excluded from capacity and
   utilization, kept in session and energy totals, and their share of sessions and energy is
   reported per run in the reconciliation artifact under `station_keys.dft_2017.unknown`.
2. **Publisher rule as a quality flag.** The DfT "incomplete or anomalous" files are landed
   like the raw files. Silver sets `publisher_excluded_rule` on any DfT row with zero energy or
   a plug-in duration of 3 minutes or less (the rule the reports state), in every family. <!-- param --> It
   is a flag, not a quarantine reason, because zero-energy rows are kept for the other sources.
   The reconciliation artifact reports the confusion between the flag and the publisher's own
   split (raw versus anomalies file) so the reproduction is checked, not assumed.
3. **One non-trivial session rule at gold.** `is_non_trivial` = energy_kwh > 0 and the
   available duration (connected minutes where the source has them, else charging minutes)
   > 3 minutes. <!-- param -->
   Applied to every source in `fct_charging_session`; utilization measures and
   findings use non-trivial sessions only, and every count says so. The threshold is the
   publisher's; it is not calibrated against the other sources and the sensitivity artifact
   shows utilization with and without the rule.
4. **Port-count precedence.** `ports_inferred` = distinct connector ids where the station has
   any (DfT: 31 ids with 1 connector id, 127 with 2, 111 with 3); else the robust max of
   observed concurrency at N = 5 (ADR-0006), floored at 1. <!-- cite: artifacts/profile/profile-20260919T235137Z.json#sources.dft_2017.answers.port.ports_per_station_id.1; artifacts/profile/profile-20260919T235137Z.json#sources.dft_2017.answers.port.ports_per_station_id.2; artifacts/profile/profile-20260919T235137Z.json#sources.dft_2017.answers.port.ports_per_station_id.3 -->
   `ports_source` records which. Stations with fewer than 5 distinct active days carry
   `low_evidence = true`: Boulder 5 of 50 names, DfT 45 of 838 ids at N = 5. <!-- cite: artifacts/profile/profile-20260919T235137Z.json#sources.boulder.answers.observed_concurrency.days_at_level.robust_max_histogram_by_n.5.0; artifacts/profile/profile-20260919T235137Z.json#sources.boulder.answers.observed_concurrency.by_station_key.keys; artifacts/profile/profile-20260919T235137Z.json#sources.dft_2017.answers.observed_concurrency.days_at_level.robust_max_histogram_by_n.5.0; artifacts/profile/profile-20260919T235137Z.json#sources.dft_2017.answers.observed_concurrency.by_station_key.keys --> Registry port counts (Phase 5) are a
   separate column and a separate sensitivity row, never blended into `ports_inferred`.
5. **DfT implied-power ceilings per family.** Computed on sessions of at least 5 minutes with
   energy above zero, implied kW = kWh / plug-in hours (scratch computation on the raw files,
   reproduced in the Phase 3 quarantine tests):
   - Rapids: the distribution has a hard edge at 50 kW (4,414 rows between 43 and 50 kW, 9
     between 50 and 55, none between 55 and 60; p99.99 = 49.9). <!-- scratch -->
     Rapid units are rated 43 or 50 kW. Ceiling **55 kW** (rated 50 plus a 10% allowance for
     minute-rounded timestamps). <!-- param -->
     Flags 1 raw row and 27 anomalies rows. <!-- scratch -->
   - Fasts: rated 7 to 22 kW (report p2) with a long tail and no edge (p99 = 22.7, p99.5 =
     27.5, p99.9 = 42.2 kW); the reports say some bodies round times to the nearest half hour,
     which inflates implied power on short sessions. <!-- scratch -->
     Ceiling **30 kW** (rated 22 plus an allowance for half-hour rounding). <!-- param -->
     Flags 388 raw rows (0.38%) and 10 anomalies rows. <!-- scratch -->
   - The single 60 kW ceiling is retired. Cary and Boulder keep 20 kW (Level 2). <!-- param -->
     Observed p99.9 is 7.209 kW for Boulder and 7.379 kW for Cary at p99; the 43 Cary rows above
     20 kW are the known outliers. <!-- cite: artifacts/profile/profile-20260919T235137Z.json#sources.boulder.answers.implausible.implied_kw_quantiles["0.999"]; artifacts/profile/profile-20260919T235137Z.json#sources.cary.answers.implausible.implied_kw_quantiles["0.99"]; artifacts/profile/profile-20260919T235137Z.json#sources.cary.answers.implausible.implied_kw_over_ceiling.rows -->

**Consequences.** The silver DfT model carries `source_family` and `publisher_excluded_rule`;
the reconciliation artifact gains `station_keys`, `publisher_rule` and `dedup` sections; the
sensitivity artifact gains a with / without non-trivial row. `docs/BRIEF.md` is the amended
brief and is re-read at the start of every phase.
