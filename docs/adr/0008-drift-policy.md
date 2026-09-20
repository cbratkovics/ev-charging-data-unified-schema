# ADR-0008 — Source contracts and the drift policy as built (2026-09-19)

**Context.** Brief § 5 asks for a declared expected schema per source, a per-file comparison
on every run written to `artifacts/drift/<run_id>.json`, and a warn / quarantine / alias
policy. Everything lands as strings, so "type" needs a definition, and a quarantined batch
needs a place to go that bronze cannot read.

**Decision.**

1. **A contract per source and per file family.** The DfT publication is four files with three
   distinct headers, so its contract has four `FamilyContract`s selected by a file-name
   pattern, each with its own column list, alias map (`EnergySupplied` to `Energy` in the
   rapids files), null tokens (`NA`) and published duration unit (minutes in the rapids raw
   file, hours in the fasts files, none in the rapids anomalies file). Boulder and Cary have
   one family each.
2. **Logical type is what the values parse as.** Each column declares one of integer,
   decimal, datetime, date, duration_hms or text; the check infers the landed column's type
   from its values with the same 99% rule the profiler uses, <!-- param --> after removing the family's null
   tokens. Integer values satisfy a decimal declaration; text accepts anything; a wholly null
   column is not judged (info `all_null`). Identifier columns are declared text even when
   most values look numeric (DfT `ChargingEvent` is a mix of integers and UUIDs; the first
   real run flagged it as retyped under an integer declaration, and the contract was
   corrected, not the data).
3. **Outcomes.** Unknown column: `warn`, the column is landed and carried through bronze.
   Missing required column, or a required column whose values no longer parse as declared:
   `quarantine` with a reason code. Missing optional column: `info`. Retyped optional column:
   `warn`. A published name in the alias map: renamed on landing, recorded as `aliased`; if
   both the published name and its target are present, `warn` and no rename. A file matching
   no family: `quarantine` with `unknown_family`.
4. **A quarantined batch is landed aside, never dropped.** It is written to
   `data/landed/<source>/_quarantined/<file>.parquet`, recorded in the landing manifest with
   that path, and listed in the drift artifact. The dbt sources read
   `data/landed/<source>/*.parquet`, so bronze never sees it, and the run continues with the
   other files. When a later run finds the file conforming again, it is re-landed in the
   main directory and the quarantined copy removed. Reconciliation (Phase 6) counts raw rows
   against bronze rows plus quarantined-batch rows.
5. **The no-op rule includes the outcome.** A file whose bytes are unchanged and whose
   outcome is unchanged is not re-landed; a contract change that flips a file between landed
   and quarantined re-lands it even though the bytes did not change.
6. **Bronze normalises names only.** `normalize_column_name` lower-cases and snake-cases the
   publisher's headers; nothing else changes. A DfT union across families leaves a column
   null in the files that do not carry it (`pluginduration` in the rapids anomalies file,
   `area_code` outside it).

**What real drift the artifact records.** On the first real run the six files landed with
zero quarantines: the two rapids files record the `EnergySupplied` alias; the header
differences between DfT families are absorbed by the per-family contracts and are visible as
which columns each bronze row carries; the value-domain drift (UUID event ids, `Connector`
text variants, day-first dates, hours versus minutes) is in `docs/PROFILE.md` and is handled
in silver by family. The quarantine and warn branches are exercised on the fixture by
`tests/test_ingest.py` (a renamed required column quarantines the file and lands it aside;
the run continues) and `tests/test_contracts.py`.

**Consequences.** Adding a source means writing its contract before its loader; adding a
file family means adding a `FamilyContract`. Bronze descriptions repeat the contract, and
`scripts/check_dbt_descriptions.py` fails if a landed column arrives without one, which is
the intended friction: an unknown column is a warning at ingest and a failure at docs time.
