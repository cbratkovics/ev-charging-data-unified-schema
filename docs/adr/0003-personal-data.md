# ADR-0003 — User-level fields never reach silver, gold or exports (2026-09-19)

**Context.** The owner asked for a per-source check of user-level fields (user ids, driver
postal codes, vehicle details) and a policy. Phase 1 found:

| Source | User-level columns in the published file |
|---|---|
| Cary, NC | none; `zip_postal_code`, `address_*`, `city`, `state_province` describe the station |
| Boulder, CO | none; `Zip_Postal_Code`, `Address`, `City`, `State_Province` describe the station |
| UK DfT 2017 | none; `Name` is the funding body (a council or public-sector organisation), `Area code` its ONS code, `Price` a fee, `ChargingEvent` a session id, `CPID` and `Connector` device ids |

**Decision.**

1. User-level columns are landed in bronze as strings like every other column (bronze is a
   faithful copy; dropping there would break row conservation and the drift contract), and are
   **not selected** by any silver model. They therefore cannot reach gold, the snapshot, the
   reconciliation artifact, the findings or `exports/`.
2. The list of user-level columns is declared per source in the source contract (Phase 2),
   so the exclusion is data, tested by a dbt test that fails if any declared user-level column
   name appears in a silver or gold relation.
3. Device-level identifiers (charge-point ids, serial numbers) are not personal data; they
   identify chargers and are kept where they give a stable station or port key.
4. Session counts per user, user-level dwell time, repeat-user analyses and any join between a
   user id and a location are out of scope and go to ROADMAP.md if ever wanted.
5. Any source added later gets a row in the table above before its loader ships.

**Consequences.** Findings cannot use user behaviour (for example "share of sessions by
returning drivers"). Where a bronze model carries a user-level column, its silver model has
fewer columns and the bronze description says which ones and why.
