# ADR-0016 — Deterministic station attributes, DfT name normalisation, and the operator grain (2026-09-20)

**Context.** docs/REPRODUCIBILITY.md promised content-identical gold and byte-identical exports.
The two releases of 2026-09-20 (`5aa9fde`, `700be5d`) disproved it: `exports/dim_station` and
`exports/mart_monthly` changed content between runs of identical inputs, with one or two
stations getting a different `site_key` or `operator_key` and a handful of DfT sessions moving
between operator rows of the mart. `dim_station` chose `source`, `operator_key`, `site_key`,
`station_name_raw` and `station_tz` with `any_value()`, which returns whichever row DuckDB
happened to scan first; setting `DUCKDB_THREADS=1` did not remove the churn. Three Boulder
and four Cary stations carry two addresses in their history (for example
`BOULDER / BASELINE ST1`: 4,353 sessions at 600 Baseline Rd, 2,150 at 900 Baseline Rd). <!-- scratch -->
In the DfT data 63 distinct funding-body names collapse to 57 once trailing and repeated
whitespace is removed, all six pairs being the same body with and without a trailing space, and
five charge points carry a body name on some sessions and a null name on others (172 sessions),
so their operator flipped between the name and `<null>`. <!-- scratch --> The idempotency tests
passed throughout because the fixture never gave one station two values to choose from.

**Decision.**

1. **Majority rule for every descriptive attribute of `dim_station`.** `site_key`,
   `station_name_raw`, `source` and `station_tz` are the value carried by the most non-trivial
   sessions at the station, ties broken by the value itself (ascending), nulls never competing;
   a null is chosen only when every session is null. `operator_key` is derived from the chosen
   `site_key` with the same expression the session fact uses (`dft_2017/<site>` or the source),
   so the station's operator is always consistent with its site. Two flags and two counts are
   added: `multi_site_key` / `site_key_candidates` (distinct non-null sites on the station's
   sessions) and `multi_operator` / `operator_candidates` (distinct operator keys, the null name
   counting as one). The silver summary artifact reports the flagged stations per source under
   `station_attributes`. Alternatives: first-seen (the defect), minimum value (deterministic but
   arbitrary: it would pick `1275 Alpine Ave` over the address with more sessions), most recent
   session (defensible for a station that moved, but it lets one late row rename a station and
   the data carries no move dates); the majority is the value most of the evidence supports and
   the flag says when the choice mattered.
2. **DfT funding-body names are normalised in silver.** `Name` is trimmed and inner whitespace
   collapsed to one space before it becomes `site_key` (and the `unknown/<Name>` station key);
   the landed spelling is kept as `site_key_raw` on every silver session model. The summary
   artifact records `dft_operator_names`: distinct raw and normalised names, the number
   collapsed, and each group of spellings. No other cleaning is applied: case and punctuation
   variants would be a judgment about identity that the data does not support.
3. **The operator of a station-day and of the monthly mart is the station's operator, not the
   session's.** Evaluated: taking `operator_key` for `mart_monthly` from each session where the
   source records it per session (only DfT does). Rejected. `fct_station_day` is one row per
   station and local date over a spine that includes days with no session, and its denominator,
   `available_port_minutes`, is a property of the station; a session-level operator would need
   the station-day split across operators, which either breaks the grain or apportions
   available minutes by a rule the data does not give. After normalisation no DfT charge point
   carries two body names on its sessions; the only remaining ambiguity is name versus null,
   which the majority rule resolves to the name. Sessions keep their own `operator_key` on
   `fct_charging_session`, so a session-grain operator rollup of counts and kWh remains possible
   inside the repository; the exported station-day and monthly relations use the station's
   operator and `multi_operator` says where the two can differ.
4. **Every ordering ends in a unique key.** The sweep found: five `any_value` picks in
   `dim_station` (item 1); the concurrency window in `dim_station` and the `lead` windows in
   `int_station_gaps` ordered by timestamps that tie for concurrent sessions (now closed by
   `session_sk`; their outputs were order-invariant, the order is now total anyway); the DfT
   exact-duplicate and natural-key ranks ordered by family then `_row_hash`, which two files can
   share because the hash covers content only (now family, file name, hash); the Boulder
   delivery-block window ordered by the file row id alone (now row id, hash); the summary's
   `qualify` over the raw families (now family, hash); the findings hour profile, which took one
   station's UTC-to-local offset from whichever session came first and so could shift an hour at
   a station whose history spans a DST change (now per session); the profiling "top" cuts of
   `value_counts` and `head` with tied counts (now count, then value); pandas sorts in the
   sweeps (now `kind="stable"` over a query with `order by`). Silver dedup already ended in
   `_row_hash` (ADR-0009); Cary's exact-duplicate rank orders identical rows and has no
   observable choice. No `limit` without `order by`, no unordered list or string aggregate and
   no `first`/`last` exist in the project.
5. **The test gap is closed.** The fixture gives Boulder station ST3 two addresses and DfT
   charge point `70903` two funding bodies, the minority value first in the file and first
   alphabetically, and the majority spelt three ways, so a first-seen or minimum pick and an
   un-normalised count each fail `test_station_attributes_follow_the_majority_rule_and_flag_ambiguity`.
   `test_two_builds_export_byte_identical_files_for_every_relation` writes the exports of two
   independent builds and compares the sha256 of every exported file, dimensions and the mart
   included.

**Consequences.** `make release` now builds with one DuckDB thread and a full refresh of the
warehouse, because a silver code change does not reach the incremental session fact until its
source is re-delivered or refreshed. `dim_operator` loses the six trailing-space rows; `mart_monthly` loses the
rows those keys and the `<null>` operator of the five name-or-null charge points produced;
`dim_station` keeps its row count and gains four columns; the snapshot records a new version
for every station whose `site_key` changed. Findings, utilization and reconciliation are
unchanged in value except the Boulder hour profile, which now places each session's minutes by
its own offset. The sessions that carry a minority operator can no longer be counted from the
exports; they can from `fct_charging_session`. Revisit if a source ever publishes an operator
change with a date: then the snapshot, not the majority, should carry it.
