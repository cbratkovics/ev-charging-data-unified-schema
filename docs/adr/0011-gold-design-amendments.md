# ADR-0011 — Gold design as amended at the Phase 4 go-ahead (2026-09-20)

**Context.** The owner approved the Phase 4 plan with six amendments. They change how the
session fact is refreshed, how station-days are laid out, how measures are allocated across
midnight, and how the SCD2 snapshot stays reproducible.

**Decision.**

1. **Source-level replace, no event-time lookback.** `fct_charging_session` is incremental
   with `delete+insert` on `source`: when any landed file of a source is new, changed
   (different sha256) or gone, every row of that source is deleted and reinserted from
   silver. A merge on `session_sk` would leave orphans when a re-delivery changes a
   natural-key field (energy is part of the key) or drops a session; a source-level replace
   cannot. The fixture re-delivery test changes an energy value, removes a session and
   re-delivers old sessions, and asserts the incremental result equals a full refresh.
2. **Change detection by hashes on the fact rows.** Every fact row carries
   `source_file_sha256`, joined from `meta_landed_files` (the landing manifest read by dbt).
   A source is "changed" when a manifest file has no fact rows with its sha256, or fact rows
   name a file or sha256 the manifest no longer has. No snapshot of the manifest is kept: the
   fact table itself is the record of what was loaded, so there is no second state to drift.
3. **Only the session fact is incremental.** `dim_station` and `fct_station_day` are full
   rebuilds every run: inferred ports, robust max, active windows and excluded days depend on
   the whole history, and a partial rebuild would silently keep stale capacity.
4. **A station × local-date spine.** `fct_station_day` has one row for every date in each
   station's active window, active or excluded. Active, non-excluded days with no session
   carry `available_port_minutes > 0` and zero usage; excluded days carry
   `is_excluded_day = true` and `available_port_minutes = 0`. A singular test asserts every
   active date in the window has exactly one row and that the row count equals the window
   length per station.
5. **Allocation across midnight.** A session is split into per-local-date pieces. Where the
   source publishes charging time, energy and charging minutes are allocated over the
   *charging window*, assumed to begin at session start and run for `charging_minutes`;
   connected minutes are allocated over the connected window (start to end). Where the
   source publishes no charging time (DfT), energy is allocated over the connected window.
   Both assumptions are stated in the model docs. Sessions are counted on their start date.
   Measures use non-trivial sessions only (ADR-0007 item 3); trivial sessions are counted
   separately per day.
6. **Deterministic snapshot validity.** `snp_station` uses the `check` strategy with
   `updated_at = data_as_of_utc`, the latest `retrieved_at` among the station's source
   files. dbt then stamps `dbt_valid_from`, `dbt_updated_at` and the `dbt_scd_id` hash from
   that column instead of the wall clock, so two builds of the same landed files produce a
   byte-identical snapshot and the idempotency comparison includes the validity columns.
   Verified in `tests/test_dbt_gold.py`. The cost: a code change that alters an attribute
   without a new retrieval produces a new version stamped with the same `data_as_of_utc` as
   the old one; the check strategy still records it, ordered by `dbt_scd_id`, and the run
   log says so.
7. **Ports, active window, availability.** As ADR-0006 and ADR-0007: connector ids where
   any exist, else robust max at N = 5 over non-trivial sessions, floored at 1; `low_evidence`
   below 5 active days; the active window from the first non-trivial session start to the last
   non-trivial session's effective end (its end, or start plus charging minutes where the
   source has no end, so a Cary session that charges for 47 hours extends the window) minus
   gaps over the source threshold measured from that effective end (Boulder 30 days, DfT 90
   days, Cary 30 days). ADR-0006 said start-to-next-start for Cary; the effective end is used
   instead so that the window, the gaps and the midnight split agree on where a session ends.
   Available minutes per local date come from the UTC instants of local midnight to the next
   local midnight, so DST transition days are 1,380 or 1,500 minutes (ADR-0010 e).

**Consequences.** `fct_charging_session` gains `source_file_sha256`; the gold layer gains
`meta_landed_files`; the snapshot's `updated_at` is data-derived. The sensitivity artifact
(ADR-0006 h, ADR-0010 f) is computed from the session fact by a script so every denominator
definition uses the same sessions.
