# Test fixture

**Hand-built, not real data.** The files under this directory are a tiny synthetic fixture
shaped like the four sources' landed parquet (same column names, same string typing, same
landing metadata). They exist so `make test` and CI run offline and so the drift, quarantine,
dedup, midnight-split and idempotency branches have deterministic inputs. No number derived
from this fixture may appear anywhere in the README, docs or findings.

Real data is downloaded at build time into `data/raw/` and `data/landed/` (git-ignored); see
`docs/DATA_SOURCES.md` for what is committed per source and why.
