# ADR-0005 — Unified session contract: the owner's Phase 1 amendments (2026-09-19)

**Context.** The Phase 1 checkpoint proposed a unified session contract. The owner approved it
with five amendments (a–e). Numbers below are read from
`artifacts/profile/<run_id>.json` (the run id is printed at the top of docs/PROFILE.md).

**Decision.**

- **(a) Durations are computed from UTC.** `connected_minutes` is `end_utc - start_utc` after
  converting each source's local wall-clock timestamps (Boulder `America/Denver`, DfT
  `Europe/London`; Cary is already UTC). Where the source also publishes a duration column
  (Boulder `Total_Duration`, DfT `PluginDuration`), the published value is kept as
  `connected_minutes_reported` and `duration_disagreement_minutes` records the difference; a
  disagreement above a tolerance of 2 minutes sets the flag `duration_disagrees`. <!-- param -->
  The tolerance comes from the profile: 147,795 of 148,132 Boulder rows agree within it. <!-- cite: artifacts/profile/profile-20260919T235137Z.json#sources.boulder.answers.durations.span_vs_recorded_duration.within_2_min; artifacts/profile/profile-20260919T235137Z.json#sources.boulder.answers.durations.span_vs_recorded_duration.rows_compared -->
  The wall-clock DST shifts
  that motivated computing from UTC show up as ±60-minute disagreements on transition dates
  (`answers.timezone.dst_transition_gaps`). A rounded-to-the-half-hour source (the DfT reports
  say some bodies rounded) will flag more rows; that is reported, not hidden.
- **(b) Boulder dedup prefers the latest delivery.** The natural key is (station name, start
  minute, end minute, energy). Among rows sharing a key, the row from the highest delivery block
  (the per-delivery `ObjectID` restarts at 0; the block index is derived from `ObjectId2`) wins,
  then the highest `ObjectId2`. Block 0 is never dropped by position. A test on the committed
  profile artifact asserts every block-0 key exists in block 1
  (`answers.overlap.delivery_blocks.blocks[0].rows_with_key_in_last_block == rows`);
  if a future delivery breaks that, the test fails and the rule is revisited.
- **(c) Cary.** UTC is corroborated by the seasonal shift of the raw-hour profile: the circular
  mean raw start hour is about one hour earlier in summer than in winter
  (`answers.timezone.seasonal_shift.summer_minus_winter_mean_raw_hour`), which is what true UTC
  timestamps of a fixed local habit produce; mislabelled local time would show no shift. The
  dedup rule for rows sharing (station name, start second) keeps the row with the larger
  charging time because every such group in the data pairs a zero-charging, zero-energy row
  with a real one (`answers.overlap.natural_key_conflicts`): an aborted plug-in logged at the
  same second as the successful one. The number of such conflicts is reported per run in the
  reconciliation artifact under `dedup.cary.natural_key_conflicts`.
- **(d) `capacity_grain` on the station dimension.** Every station-dimension row carries
  `capacity_grain` in {`port`, `unit`, `site`}: DfT rows with a `Connector` id are `port`;
  Boulder station names and DfT charge-point ids without connector ids are `unit`; Boulder
  addresses and DfT funding-body names are `site`. Utilization and capacity figures are
  never compared across grains; the gold models carry the grain on every measure row and a
  test fails if a rollup mixes grains.
- **(e) Duration availability is declared per source, never imputed.** The contract records
  `duration_availability` per source: Cary `charging_only`, Boulder `both`, DfT `plug_in_only`
  (the fasts report states charging time cannot be identified). `charging_minutes` is null for
  DfT, `connected_minutes` is null for Cary, and no model derives one from the other. The
  profile artifact carries the same classification (`answers.durations.availability`) and a
  test pins it.

**Consequences.** Charging-time utilization exists for Cary and Boulder; connected-time
utilization for Boulder and DfT; idle-after-charge only for Boulder. Findings say which. The
reconciliation artifact gains a `dedup` section per source (rows removed by rule, and for Cary
the conflict count). ADR-0006 covers the capacity denominator.
