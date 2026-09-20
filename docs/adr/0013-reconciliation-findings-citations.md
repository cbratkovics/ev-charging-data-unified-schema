# ADR-0013 — Reconciliation identities, findings, and how documents cite artifacts (2026-09-20)

**Context.** Phase 6 delivers the reconciliation artifact, the findings and the checker that
enforces claim discipline (docs/BRIEF.md rule 3). The owner amended the plan in five points;
this ADR records the rules as built.

**Decision.**

1. **Two identities, in the silver summary artifact.** Reconciliation extends
   `artifacts/silver/<run_id>.json` (section `reconciliation`), per source, overall and per
   month of the session's local start:
   - (i) **raw = fact + quarantined by primary reason**, for rows and for kWh on parsed
     values: every bronze row is either in `fct_charging_session` or in
     `slv_sessions_quarantined` under exactly one primary reason. The DfT rows the publisher
     moved between publications appear as a breakdown *inside* `natural_key_duplicate`
     (`same_event_in_raw_file`, `within_family`, `other`), never as a separate term, so nothing
     is counted twice. Rows whose start could not be parsed sit in the month bucket
     `unparsed`.
   - (ii) **fact = counted in station-day measures + trivial + unknown-station**, for
     sessions and kWh: a fact row is counted in `fct_station_day` only if it is non-trivial and
     at a known station. Sessions are exact by start date. kWh in `fct_station_day` is
     allocated by piece date, so per month the difference between the fact's start-month kWh
     and the station-day month kWh is the documented term `midnight_spill_kwh` (zero at the
     source level).
   - **Residual and tolerance.** Only what remains after the identity terms is compared with
     the tolerance: rows and sessions must reconcile exactly; kWh within 1e-6 relative (the
     conservation test's tolerance for the midnight split). <!-- param --> A residual outside tolerance is
     `blocking`; inside tolerance but non-zero is `non_blocking`; zero is `ok`. Each carries a
     one-line interpretation. `classify()` is pure and tested per branch; a blocking residual
     makes `scripts/silver_summary.py` exit non-zero, which fails `make release` and the
     full-build workflow.
2. **Citation stability.** Living documents (README, `docs/FINDINGS.md`, `docs/CARD.md`) cite
   `artifacts/<kind>/latest.json` paths, resolved through `latest.json` to the current file.
   ADRs cite the point-in-time artifact they were written against by run id. `make release`
   runs `scripts/prune_artifacts.py`, which keeps every artifact cited by an ADR, the current
   file of every kind and `latest.json`, and deletes the rest. The checker fails on a citation
   whose file or key does not exist.
3. **Readability.** Number-bearing blocks in README, FINDINGS and CARD are rendered from the
   artifacts between `<!-- generated:<name> start -->` / `end` markers by
   `scripts/render_docs.py`, with `--check` in CI like the other rendered documents. A number
   in free prose carries its key in an HTML comment immediately after the sentence:
   `<!-- cite: artifacts/silver/latest.json#by_source.boulder.accepted -->`. Rendered Markdown
   shows no citation brackets.
4. **The checker (`scripts/check_doc_numbers.py`).** It scans README.md, docs/FINDINGS.md,
   docs/CARD.md and docs/adr/*.md. Generated blocks are trusted to their renderer's `--check`.
   Outside them, a *measured number* is any numeric token with a thousands separator, a
   decimal point, a percent sign, a value of 1,000 or more, or a unit or noun of measure
   directly after it (rows, sessions, stations, files, kWh, minutes, hours, days, keys,
   columns, ports). <!-- param --> Every measured number in a sentence must be covered by a `cite:` comment
   in that sentence (several keys may be listed, separated by `;`), and the cited value must
   equal the printed one at the printed precision (thousands separators and percent
   formatting are normalised; a percent is compared against a ratio times 100). <!-- param --> Allowed
   without citation: years, ISO dates and times, ADR and phase numbers, version pins, and
   small integers (below 1,000, no decimals, no unit). <!-- param --> `<!-- param -->` after a sentence marks numbers
   that are design parameters or arithmetic constants (a threshold, a tolerance, the minutes
   in a DST day), not measurements. In ADRs only, `<!-- scratch -->` after a sentence marks a
   number that came from an exploratory query recorded at the time and not from a committed
   artifact; the marker is the honest label. The checker counts both kinds so their number is
   visible in its output.
5. **Findings.** `scripts/findings.py` computes every finding's numbers from gold and the
   sensitivity artifact into `artifacts/findings/<run_id>.json` and renders
   `docs/FINDINGS.md` from it. Findings are within-source only; the period mismatch between
   sources is stated once at the top. Each finding states its period, cites its keys, gives
   its sensitivity range across the denominator definitions, says what would change the
   conclusion, and says what the data cannot show: there is no queue or demand data, ports
   are inferred lower bounds, DfT covers one year.
6. **Boulder idle finding.** Two idle measures: the headline idle share
   (1 − charging / connected over non-trivial sessions) and *blocking idle*, the idle minutes
   accrued while every inferred port at the station was occupied, computed from the
   connected-interval sweep per station under the production port count and, for the range,
   under each robust-max N. Both are reported overall and by hour of day; the smaller,
   honest number leads when blocking idle is rare.

**Consequences.** The silver summary schema gains `reconciliation` and a `status` the
release run reads. Findings numbers live in their own artifact. Historical numbers in
ADR-0005 to ADR-0012 are either re-cited against the artifact they came from or marked
`scratch`. CI runs the checker and the three `--check` renderers.
