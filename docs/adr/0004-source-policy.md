# ADR-0004 — Source policy: explicit, verbatim open licence or nothing (2026-09-19)

**Context.** The build brief admitted sources whose licence was unstated, on a
download-at-build-time, aggregates-only basis. Phase 1 found two such sources among the four:
Dundee City Council's six annual files (`licenseInfo: null` on every item, no site terms page) and
Palo Alto's file (no dataset-level licence; a city-wide use agreement naming no open licence;
and, separately, a portal returning HTTP 502 on every attempt). The owner replaced the brief's
rule with a hard rule after the Phase 1 checkpoint.

**Decision.**

1. A source is used only if the publisher states an open licence explicitly, on the dataset or
   on the page that serves it, and the statement is recorded verbatim with its URL in
   docs/DATA_SOURCES.md. A licence inferred from sibling datasets, a portal default, or a
   third-party re-upload does not count. "Unstated" means not used, whatever the access terms.
2. Dundee and Palo Alto are removed entirely: no loader, no config entry, no dbt source, no
   profile section, no raw file, no roadmap item to retry them. Their discovery record survives
   only in this ADR and in the Phase 1 checkpoint of the conversation that produced it.
3. The replacement is the UK Department for Transport's "Electric Chargepoint Analysis 2017"
   raw data (local-authority rapids and public-sector fasts, plus the two published
   incomplete-or-anomalous files). Both publication pages state "All content is available under
   the Open Government Licence v3.0, except where otherwise stated" with the OGL v3.0 URL. The
   licence's attribution statement is carried in docs/DATA_SOURCES.md and the README.
4. The approved set is therefore Cary (CC0 1.0), Boulder (CC0) and DfT 2017 (OGL v3.0). The
   station registry's terms permit any use. Any future source passes the same gate before a
   loader is written.

**Consequences.** The project now spans three operators in two countries and five years
(Cary 2012–2023, Boulder 2018–2023, DfT 2017), with the period mismatch the brief already
required findings to state. The UK source has no station-registry coverage and carries an
explicit `out_of_coverage` status in Phase 5. ADR-0002 is amended to the approved set. The
brief's "download at build time, commit aggregates" path for unlicensed sources is retired.
