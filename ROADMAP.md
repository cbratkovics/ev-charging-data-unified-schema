# Roadmap

Ideas outside the v1 brief. Nothing here is built; nothing here is promised.

## Deferred sources

- Perth & Kinross (UK) charging sessions.
- Paris charging sessions.
- Caltech ACN-Data.

## Deferred capabilities

- Disambiguating fall-back local times with the publisher's reported duration: where a source
  publishes a plug-in duration, a session starting in the repeated hour could be assigned the
  occurrence whose computed duration matches the reported one, instead of DuckDB's fixed
  second-occurrence rule (ADR-0009). Six DfT sessions are affected in the current data.

- A read-only API or frontend over `exports/` (the exports are the stable read contract for it).
- A cloud warehouse target; v1 is DuckDB only, by design ($0 runtime).
