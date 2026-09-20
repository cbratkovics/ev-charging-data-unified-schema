# Test fixture

**Hand-built, not real data.** `raw/<source>/*.csv` are tiny files shaped exactly like the
published sources (same headers, BOMs, quoting, `NA` tokens, mixed timestamp formats, the two
Boulder delivery blocks, the DfT unit and header differences), with invented stations and
sessions. They exist so `make test` and CI run offline and so the contract, drift, quarantine,
dedup, DST, midnight-split and idempotency branches have deterministic inputs. The landed
parquet under `landed/` is regenerated from them by `make fixture` and is git-ignored.

No number derived from this fixture may appear anywhere in the README, docs or findings. Real
data is downloaded at build time into `data/raw/` and `data/landed/` (git-ignored);
`docs/DATA_SOURCES.md` records what is committed per source and why.

What each fixture exercises:

- `cary`: a natural-key conflict (aborted plug-in at the same second), a session over 24 h, a
  midnight crossing in local time, a zero-energy row.
- `boulder`: two delivery blocks (ObjectID restarts at 0), the ISO-format rows inside block 0,
  a spring-forward and a fall-back session, an energy value formatted `5.0` vs `5`, a
  zero-charging row, a midnight crossing. Station ST3 carries two addresses: the minority address comes
  first in the file and first alphabetically, so only the majority rule (ADR-0016) picks
  `9 Fixture Ct`.
- `dft_2017`: the four headers, `EnergySupplied` vs `Energy`, `PluginDuration` in minutes vs
  hours, ISO vs day-first dates, `NA` tokens, a null CPID, a text-variant connector, the 1970
  end sentinel, a row present in both the raw and the anomalies file, a DST-spanning session
  in each of the two families, a row meeting the publisher's exclusion rule. Charge point 70903
  carries two funding bodies, the majority (`Fixture Council`) landed in three spellings that
  normalisation collapses, the minority (`Zed Council`) first in the file: only the majority
  rule after normalisation picks `dft_2017/Fixture Council`.
