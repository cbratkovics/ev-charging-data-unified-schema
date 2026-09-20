# ADR-0012 — Ports as the larger lower bound; one meaning for capacity_grain; registry matching cut (2026-09-20)

**Context.** The Phase 4 checkpoint raised three questions and proposed skipping Phase 5.
The owner answered all four.

**Decision.**

1. **Ports are the larger of two lower bounds.** `ports_inferred = max(connector-id count,
   robust max of observed concurrency at N = 5)`, floored at 1. Both counts are lower bounds on
   the true number of ports (a connector that was never used is not published as an id at a
   session; a port never used concurrently with its neighbours never shows in concurrency), so
   the larger is the tighter bound. `ports_source` records which bound was binding
   (`connector_ids`, `observed_concurrency`, or `floor` when neither reached 1). The sensitivity
   artifact keeps both pure definitions alongside; the first Phase 4 run showed why: under
   connector ids alone, 224 DfT station-days exceeded 100% utilization; under the robust max
   alone, 175 (`artifacts/sensitivity/sensitivity-20260920T013439Z.json`,
   `results[].station_days_over_100pct`). ADR-0007 item 4's precedence (connector ids first) is
   superseded.
2. **`capacity_grain` has one meaning.** It lives on `dim_station` (and, copied from there, on
   `fct_station_day`) and says what the station key identifies: `unit` throughout. The session
   fact's former `capacity_grain` column, which said whether the *row* named a connector, is
   renamed `port_id_present` (boolean) in silver and gold.
3. **Unknown-station rows.** DfT rows with a null charge-point id stay in the session fact and
   in session and energy totals under `dft_2017/unknown/<Name>` keys, carry no capacity, and
   their share of sessions and energy is reported in the silver summary
   (`unknown_station`), in the reconciliation sections Phase 6 adds, and in the README
   limitations.
4. **Registry matching is cut.** Phase 5 is skipped: no API key was available and the earlier
   phases ran long. `dim_station.registry_match_status` and `ports_registry` are removed, the
   `registry` value of `ports_source` never existed in built data and is removed from the
   docs, `.env.example` no longer names a key (the project reads no secret), and every mention
   of the registry as a feature is removed from the README, the brief, the data-sources page
   and the sensitivity definitions. The design is preserved in ROADMAP.md. ADR-0002 item 3
   and ADR-0006 (h) are annotated rather than rewritten.

**Consequences.** `dim_station` has two fewer columns; the session fact contract changes one
column name and type (a genuine contract change, handled by a full refresh, not by a
versioned model, because nothing outside this repository reads the fact yet). The brief's § 4
row 4 and § 5 registry section are removed and its amendments log records this ADR.
