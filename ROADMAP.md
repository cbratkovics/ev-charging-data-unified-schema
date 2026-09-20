# Roadmap

Ideas outside the v1 brief. Nothing here is built; nothing here is promised. The built scope is
three sources (Boulder, Cary, UK DfT 2017), bronze to gold, artifacts, findings and exports.

## Deferred sources

- Perth & Kinross (UK) charging sessions.
- Paris charging sessions.
- Caltech ACN-Data.

## Station-registry matching (cut from v1)

Matching US stations to the Alternative Fuel Stations registry (US and Canada; API now at
`developer.nlr.gov`, terms "may be used for any purpose whatsoever") was Phase 5 of the brief and
was cut: no key was available and the phases before it ran long. The design, if picked up:
normalise names and addresses; exact match first; fuzzy match with `rapidfuzz` on the remainder;
weighted score; confidence tiers; a review file for low-confidence and suspicious matches; an
explicit out-of-coverage status for the UK chargepoints; method, score and tier on every mapping
row; a match rate reported as coverage, not accuracy, with a hand-reviewed random sample.
Registry port counts would join the sensitivity artifact as a fourth denominator definition,
side by side with the inferred ones, never blended.

## Deferred capabilities

- A versioned public mart, once a genuine contract change arises (none has; ADR-0012's column
  rename was handled by a full refresh because nothing outside the repository reads the fact).
- Registry port counts as a fourth denominator definition in the sensitivity artifact, if the
  registry matching above is ever built.
- Disambiguating fall-back local times with the publisher's reported duration: where a source
  publishes a plug-in duration, a session starting in the repeated hour could be assigned the
  occurrence whose computed duration matches the reported one, instead of DuckDB's fixed
  second-occurrence rule (ADR-0009). Six DfT sessions are affected in the current data.

- A read-only API or frontend over `exports/` (the exports are the stable read contract for it).
- A cloud warehouse target; v1 is DuckDB only, by design ($0 runtime).
