# ADR-0009 — Phase 3 amendments: contract-diff docs, release run, DST edge cases, quarantine precedence, deterministic dedup (2026-09-20)

**Context.** The owner approved Phase 2 with six changes for Phase 3. Two of them required
an empirical check of DuckDB's timezone behaviour before any silver SQL was written.

**Empirical findings (DuckDB 1.5.5, pinned in `constraints.txt`; `tests/test_duckdb_timezone.py`
pins them so a version bump that changes them fails loudly).** <!-- param -->

- The `icu` extension is statically linked into the `duckdb` Python wheel
  (`duckdb_extensions()` reports `install_mode = STATICALLY_LINKED`) and `LOAD icu` succeeds
  with `autoinstall_known_extensions` and `autoload_known_extensions` both off. CI needs no
  network install. dbt-duckdb 1.11.0 uses the same library. <!-- param -->
- `timezone(zone, naive_ts)` interprets the naive timestamp as wall-clock local time in
  `zone` and returns the UTC instant. An **ambiguous fall-back time resolves to the second
  occurrence (standard time)**: `2023-11-05 01:30` in `America/Denver` becomes
  `08:30 UTC` (MST), and `2023-10-29 01:30` in `Europe/London` becomes `01:30 UTC` (GMT). The
  brief assumed the first occurrence; DuckDB's choice is adopted and documented instead of
  being overridden, because overriding it would need a second conversion whose correctness
  would itself need proving.
- A **nonexistent spring-forward time is shifted forward one hour**: `2023-03-12 02:30` in
  Denver becomes `09:30 UTC`, which converts back to `03:30` local, so the round trip
  `timezone(zone, timezone(zone, L)) != L` detects it.
- Detection rules used in silver, derived from the above and verified in the same test:
  `nonexistent_local_time` iff the round trip differs;
  `is_dst_ambiguous` iff the round trip is equal and `timezone(zone, L) - timezone(zone,
  L - 1 hour) = 2 hours` (the hour before an ambiguous hour maps two hours earlier in UTC
  under second-occurrence resolution). <!-- param -->
  The naive `+ 1 hour` variant is wrong under this resolution: it flags the hour *before* the
  ambiguous one. <!-- param -->

**Decision.**

1. **Contract-diff documentation.** `scripts/render_contracts.py` renders `docs/CONTRACTS.md`
   from `data/contracts.py`: per source and family, every declared column with its logical
   type, required flag and description, the alias map, the null tokens and the duration unit,
   plus a cross-family diff table for DfT. `--check` runs in CI and a test asserts the
   committed document matches the code. Per-family contracts stay (Phase 2 open question 1).
2. **Release run.** `make release` regenerates every published artifact in one run at one
   commit: ingest (drift), profile and its docs, the dbt build, the contract docs, and, as
   the phases add them, reconciliation, sensitivity, exports and findings. The run refuses to
   start on a dirty tree so every artifact records the same `code_commit`.
3. **Nonexistent local times** are a quarantine reason (`nonexistent_local_time`): the
   published wall-clock time cannot have happened, so no UTC instant is faithful to it.
   Ambiguous times are kept, converted to the second occurrence, and flagged
   `is_dst_ambiguous`. Both have dbt unit tests; the committed silver summary
   `artifacts/silver/silver-20260920T005935Z.json` carries the real counts under
   `by_source.<source>.dst_ambiguous_starts` and
   `by_source.<source>.by_primary_reason.nonexistent_local_time`.
4. **Quarantine reasons.** Every failing reason is kept in `quarantine_reasons[]`;
   `primary_reason` is the first present in this precedence, so counts by primary reason sum
   to the quarantined total: `blank_row`, `unparseable_timestamp`, `nonexistent_local_time`,
   `exact_duplicate`, `natural_key_duplicate`, `end_sentinel_1970`, `end_before_start`,
   `negative_energy`, `energy_sentinel`, `charging_exceeds_connected`,
   `implied_kw_over_ceiling`. Structural reasons come first because a row that cannot be
   parsed cannot be judged on values; duplicates come before value checks because a duplicate
   is removed whatever its values and should not inflate the value-error counts.
5. **Deterministic dedup.** Every survivor choice is an `order by` that ends with `_row_hash`:
   Boulder `delivery_block desc, objectid2 desc, _row_hash`; Cary `charging_minutes desc,
   _row_hash`; DfT `family_rank` (raw before anomalies) `, _row_hash`. Two builds of the same
   input pick the same survivor regardless of DuckDB's scan order.
6. **Null-safe keys.** Natural-key comparisons use `is not distinct from` semantics: the key
   columns are coalesced to a sentinel token before hashing into `natural_key_hash`.
7. **Tolerance on `charging_exceeds_connected`.** Connected time is computed from the
   published timestamps, which Boulder gives at minute precision on most rows, while charging
   time has seconds; so on a valid row charging can exceed the computed connected time by up
   to a minute. <!-- param -->
   The first real build with a one-second tolerance quarantined 10,627 Boulder rows; the
   excess was under a minute on all but 3. <!-- scratch -->
   The rule was first relaxed to a global 2 minutes and then, per ADR-0010 (a), to the row's
   own timestamp precision with a within-tolerance flag. <!-- param --> On the committed silver summary
   `artifacts/silver/silver-20260920T005935Z.json`: `by_source.boulder.flags.charging_exceeds_connected_within_precision`
   rows are flagged and `by_source.boulder.by_primary_reason.charging_exceeds_connected` rows
   quarantined.
8. **Session timezone.** The dbt profile sets DuckDB's `TimeZone` to UTC so timestamptz
   values render and export identically on every machine.

**Consequences.** `docs/BRIEF.md` § 5 now says fall-back ambiguity resolves to the second
occurrence. The unified contract gains `quarantine_reasons[]` and `primary_reason` on the
quarantine model and `nonexistent_local_time` on the reason list. The release target is a
stub until Phase 6 adds the reconciliation and findings steps.
