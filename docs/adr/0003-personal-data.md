# ADR-0003 — User-level fields never reach silver, gold or exports (2026-09-19)

**Context.** The owner asked for a per-source check of user-level fields (user ids, driver
postal codes, vehicle details) and a policy. Phase 1 found:

| Source | User-level columns in the published file |
|---|---|
| Cary, NC | none; `zip_postal_code`, `address_*`, `city`, `state_province` describe the station |
| Boulder, CO | none; `Zip_Postal_Code`, `Address`, `City`, `State_Province` describe the station |
| Dundee, UK | none; `Postcode` is the site's postcode (constant per site) |
| Palo Alto, CA | **not verified** (file not downloadable in Phase 1). A third-party re-upload's column list names `User ID` and `Driver Postal Code` (user-level) and `MAC Address`, `System S/N`, `EVSE ID`, `Model Number` (device-level). |

**Decision.**

1. User-level columns are landed in bronze as strings like every other column (bronze is a
   faithful copy; dropping there would break row conservation and the drift contract), and are
   **not selected** by any silver model. They therefore cannot reach gold, the snapshot, the
   reconciliation artifact, the findings or `exports/`.
2. The list of user-level columns is declared per source in the source contract (Phase 2),
   so the exclusion is data, tested by a dbt test that fails if any declared user-level column
   name appears in a silver or gold relation.
3. Device-level identifiers (`EVSE ID`, `MAC Address`, serial numbers) are not personal data;
   they identify chargers. `EVSE ID` in particular is the best candidate for a stable port key
   in Palo Alto and is kept. `MAC Address` and `System S/N` are kept in silver only if they turn
   out to be needed for port identity, otherwise dropped, decided when the file is profiled.
4. Session counts per user, user-level dwell time, repeat-user analyses and any join between a
   user id and a location are out of scope and go to ROADMAP.md if ever wanted.
5. The Palo Alto row in the table above is re-verified against the real file before its loader
   ships, and this ADR is amended.

**Consequences.** Findings cannot use user behaviour (for example "share of sessions by
returning drivers"). The silver contract for Palo Alto will have two columns fewer than its
bronze model, and the description of `brz_palo_alto` says which ones and why.
