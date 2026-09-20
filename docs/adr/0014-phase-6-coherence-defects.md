# ADR-0014 — Three coherence defects found at the Phase 6 review, and how they were fixed (2026-09-20)

**Context.** The owner read the Phase 6 checkpoint against the Phase 4 one and found three
inconsistencies the number checker cannot see, because it verifies that each number matches a
key and not that the numbers agree with each other. All three were real.

**Findings and decisions.**

1. **Cary's utilization moved without a reason.** At Phase 4 the sensitivity artifact gave Cary
   a charging-time utilization of 7.12% under the robust max at N = 5; the first Phase 6
   findings artifact gave 6.18% under the production port count, although Cary has no
   connector ids and the production rule cannot change its ports.
   <!-- cite: artifacts/sensitivity/sensitivity-20260920T013439Z.json#results[21].utilization; artifacts/findings/findings-20260920T021459Z.json#utilization_ranges.cary__charging.production -->
   The sensitivity artifacts before and after were identical for Cary, so the drift was between
   the Python sweep (the sensitivity) and the SQL sweep (`dim_station`). Per station they agreed
   on 20 of 21 Cary keys; on `cary/TOWN OF CARY / CHARGER #1` SQL inferred two ports and the
   Python sweep one. <!-- scratch -->
   Cause: for sources without an end timestamp the SQL models built the charging-window end as
   `start + round(charging_minutes)` whole minutes, while the Python sweep used exact seconds. At
   a single-port station used back to back, rounding an end up by as much as thirty seconds
   overlapped the next session's start, so SQL saw two concurrent sessions on enough days to
   pass N = 5 and inferred a second port. Fix: `dim_station`, `int_station_gaps` and
   `fct_station_day` now use `to_seconds(round(charging_minutes * 60))`. Cary's production
   utilization is 7.12%, inside its range of 6.15% to 7.44%.
   <!-- cite: artifacts/findings/findings-20260920T022915Z.json#utilization_ranges.cary__charging.production; artifacts/findings/findings-20260920T022915Z.json#utilization_ranges.cary__charging.min; artifacts/findings/findings-20260920T022915Z.json#utilization_ranges.cary__charging.max -->
   `tests/test_gold_python_coherence.py` now asserts that `dim_station.ports_inferred` equals
   the sensitivity module's production definition for every station of the fixture warehouse.
2. **DfT's production utilization lay outside its own range.** The first Phase 6 findings gave
   8.73% under production against a range of 8.75% to 11.41%.
   <!-- cite: artifacts/findings/findings-20260920T021459Z.json#utilization_ranges.dft_2017__connected.production; artifacts/findings/findings-20260920T021459Z.json#utilization_ranges.dft_2017__connected.min; artifacts/findings/findings-20260920T021459Z.json#utilization_ranges.dft_2017__connected.max -->
   The production rule takes the larger of two lower bounds per station, so its utilization is
   at or below both pure definitions; a range built from the pure definitions alone excludes it
   by construction. Fix: the sensitivity artifact carries `production` as a definition of its
   own and the range spans every definition including it. DfT's production value is
   8.73% in a range of 8.73% to 11.41%.
   <!-- cite: artifacts/findings/findings-20260920T022915Z.json#utilization_ranges.dft_2017__connected.production; artifacts/findings/findings-20260920T022915Z.json#utilization_ranges.dft_2017__connected.min; artifacts/findings/findings-20260920T022915Z.json#utilization_ranges.dft_2017__connected.max -->
   `tests/test_findings_artifact.py` asserts production inside [min, max] for every source and
   flavour, in both artifacts.
3. **The DfT publisher-rule finding mixed populations and did not sum.** The old sentence set
   9,258 moved events and 17,679 unexplained rows beside 38,376 accepted rows; the moved events
   are quarantined duplicates, not accepted rows, and a second figure of 8,975 disagreed with
   9,258. <!-- scratch -->
   Fix: one generated table accounts for every landed row of the rapids anomalies file once:
   total 48,619 = accepted 38,376 (meets the stated rule 20,699, does not 17,677)
   + quarantined 10,243, with the 10,183 duplicates split by the surviving twin's family and status.
   <!-- cite: artifacts/findings/findings-20260920T022915Z.json#dft_anomalies_population.total; artifacts/findings/findings-20260920T022915Z.json#dft_anomalies_population.accepted; artifacts/findings/findings-20260920T022915Z.json#dft_anomalies_population.accepted_meets_rule; artifacts/findings/findings-20260920T022915Z.json#dft_anomalies_population.accepted_not_meeting_rule; artifacts/findings/findings-20260920T022915Z.json#dft_anomalies_population.quarantined; artifacts/findings/findings-20260920T022915Z.json#dft_anomalies_population.quarantined_by_primary_reason.natural_key_duplicate -->
   The two earlier figures were two different counts: 9,258 is the number of anomalies rows
   whose natural key also appears in the fasts raw file, which the table now reproduces exactly
   as 8,872 duplicates of an accepted fasts row plus 386 duplicates of a fasts row that was itself quarantined for
   implied power; 8,975 came from an earlier bucket rule that looked only for a twin among the
   accepted rows of the gold fact and so counted the 8,872 plus part of another family.
   <!-- cite: artifacts/findings/findings-20260920T022915Z.json#dft_anomalies_population.natural_key_duplicate_by_twin["fasts/accepted"]; artifacts/findings/findings-20260920T022915Z.json#dft_anomalies_population.natural_key_duplicate_by_twin["fasts/quarantined"] -->
   `moved_to_fasts_raw` is now defined as the sum of the two fasts rows, 9,258, and a test asserts every part of the table sums.
   <!-- cite: artifacts/findings/findings-20260920T022915Z.json#dft_anomalies_population.moved_to_fasts_raw -->
4. **A coherence test for the findings artifact.** `tests/test_findings_artifact.py`: parts sum
   to wholes (the population table, the station groups, the hour profiles), shares lie in
   [0, 1], idle nests inside connected and full-occupancy idle inside idle, production inside
   every range. It runs on the committed artifacts, so a regenerated artifact that breaks
   coherence fails `make test`.
5. **"Blocking idle" is now "idle at full occupancy".** It is framed as an upper bound on
   displaced demand (ports are lower bounds, every idle minute at a single-port station counts by
   definition, no queue data), quoted as "up to", and reported for the 14 single-port and
   36 multi-port Boulder stations separately: 100% and 21.9% of idle time respectively,
   the latter being 9.5% of the multi-port group's connected time.
   <!-- cite: artifacts/findings/findings-20260920T022915Z.json#boulder_idle_by_station_group.single_port.stations; artifacts/findings/findings-20260920T022915Z.json#boulder_idle_by_station_group.multi_port.stations; artifacts/findings/findings-20260920T022915Z.json#boulder_idle_by_station_group.single_port.full_occupancy_share_of_idle; artifacts/findings/findings-20260920T022915Z.json#boulder_idle_by_station_group.multi_port.full_occupancy_share_of_idle; artifacts/findings/findings-20260920T022915Z.json#boulder_idle_by_station_group.multi_port.full_occupancy_idle_share_of_connected -->
   "Every station has some" now says what it means: every station records at least one such
   minute, which is automatic for the single-port group.

**Consequences.** The pre-fix findings artifact `findings-20260920T021459Z.json` is kept because this ADR
cites it. The three defects were caught by reading two checkpoints side by side, not by any
test; the tests added here cover the same class of defect for the future.
