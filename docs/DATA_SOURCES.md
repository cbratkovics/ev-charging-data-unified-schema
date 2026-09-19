# Data sources

Four public session sources and one reference registry. Per source: the exact endpoints used,
the licence **verbatim as published** with the URL it was read from, and what this repository
commits (docs/adr/0002-source-redistribution.md). Retrieval time, size, row count and SHA-256 of
every downloaded file are in the generated inventory at the end of this page; the full hashes
are in `artifacts/profile/<run_id>.json`. Discovery was done on 2026-09-19.

## Cary, NC — Town of Cary, "Electric Vehicle Charging Stations"

- Portal: Opendatasoft. Dataset page: <https://data.townofcary.org/explore/dataset/electric-vehicle-charging-stations/>
- Endpoints used:
  - metadata: `https://data.townofcary.org/api/explore/v2.1/catalog/datasets/electric-vehicle-charging-stations`
  - full CSV: `https://data.townofcary.org/api/explore/v2.1/catalog/datasets/electric-vehicle-charging-stations/exports/csv?delimiter=,&use_labels=false`
    (the bare export defaults to `;` as delimiter; the file carries a UTF-8 BOM and CRLF line endings)
- Licence, verbatim from the metadata JSON (`metas.default`): `"license": "CC0 1.0 Universal"`,
  `"license_url": "https://creativecommons.org/publicdomain/zero/1.0/"`, `"attributions": null`,
  `"publisher": "Cary"`. Read from the metadata endpoint above.
- Publisher description, verbatim (HTML stripped): "This dataset contains session details from
  publicly available, Town-owned electric vehicle charging stations. The dataset does not include
  the EV charging station located at Herb Young Community Center Parking Deck (121 Wilkinson
  Avenue Cary, NC 27513) although it is operational. This report was pulled January 3, 2023. The
  dataset is updated monthly."
- Portal metadata: `records_count` 20142, `modified` 2026-06-11T20:19:45Z,
  `data_processed` 2026-02-19T19:08:52Z, `timezone` "US/Eastern". Despite "updated monthly" the
  sessions end on 2023-01-03 (docs/PROFILE.md); the later timestamps are re-processing.
- Committed: nothing from the file (see ADR-0002); the inventory row below and the profile
  aggregates.

## Boulder, CO — City of Boulder, "Electric Vehicle Charging Station Data"

- Portal: ArcGIS Hub. Item page: <https://open-data.bouldercolorado.gov/datasets/95992b3938be4622b07f0b05eba95d4c_0>
- Endpoints used:
  - full CSV (two redirects to a short-lived signed URL; the Hub URL is what is recorded):
    `https://open-data.bouldercolorado.gov/api/download/v1/items/95992b3938be4622b07f0b05eba95d4c/csv?layers=0`
  - item metadata: `https://www.arcgis.com/sharing/rest/content/items/95992b3938be4622b07f0b05eba95d4c?f=json`
  - feature service (every non-id field is a string): `https://services.arcgis.com/ePKBjXrBZ2vEEgWd/arcgis/rest/services/Electric_Vehicle_Charging_Station_Data/FeatureServer/0`
  - data dictionary (2020, describes an older column layout): `https://webappsprod.bouldercolorado.gov/opendata/ev_datadictionary.csv`
- Licence, verbatim from the item metadata field `licenseInfo`:
  `<p><a href='https://creativecommons.org/publicdomain/zero/1.0/' target='_blank' rel='nofollow ugc noopener noreferrer'><span style='font-family:&quot;Arial&quot;,sans-serif; color:#005E95; background:white;'>CC0 License</span></a></p>`
  (visible text "CC0 License", linked to the CC0 1.0 deed). `accessInformation` is `null`.
  Read from the item metadata endpoint above.
- Publisher description, verbatim (HTML stripped): "This dataset shows the energy use, length of
  charging time, gasoline savings and greenhouse gas emission reductions from all city-owned
  electric vehicle (EV) charging stations. Data are broken out by charging station
  name/location, transaction date, and transaction start time; 1 row indicates 1 EV charging
  station transaction. A data dictionary with descriptions of the fields included in the
  dataset can be downloaded https://webappsprod.bouldercolorado.gov/opendata/ev_datadictionary.csv."
- Portal metadata: feature count 148136; layer data last edited 2023-12-06T20:47:00Z. The
  static file index `https://www-static.bouldercolorado.gov/docs/opendata/` named in the brief
  has no DNS record any more; the three EV CSVs a stale search index lists there could not be
  retrieved. The "overlapping re-deliveries" the brief anticipated are inside this one file
  (docs/PROFILE.md).
- Committed: nothing from the file (see ADR-0002); inventory row and profile aggregates.

## Dundee, UK — Dundee City Council, "Public EV Charge Point Usage"

- Portal: ArcGIS Hub. All six items are plain CSV attachments (no feature service). Item pages:
  - 2021 (27 Jul–31 Dec): <https://data.dundeecity.gov.uk/datasets/189b838f51e74f6bb77509d91c47d7c0>
  - 2022: <https://data.dundeecity.gov.uk/datasets/f1a6b5df441d4606821d5f1a78e92d7e>
  - 2023: <https://data.dundeecity.gov.uk/datasets/80df5f177b8c4a94b2bc692835801e8e>
  - 2024: <https://data.dundeecity.gov.uk/datasets/8b443deaf9174b7aa9d3e10eaa906422>
  - 2024, earlier upload of the same year (header `Column1` instead of `Postcode`, blank rows, newest-first order): <https://data.dundeecity.gov.uk/datasets/701795ab29c04e4bbf21f6a4be3404cd>
  - 2025 (1 Jan–31 Aug): <https://data.dundeecity.gov.uk/datasets/e185a3a1cfc948a69ada76e950b9d447>
- Endpoints used: `https://www.arcgis.com/sharing/rest/content/items/<item id>/data` for each item.
- Licence: **unstated** on every item. `licenseInfo: null` and `accessInformation: null` in the
  item metadata (`https://www.arcgis.com/sharing/rest/content/items/<item id>?f=json`);
  `"license": "none"` from the Hub API (`https://data.dundeecity.gov.uk/api/v3/datasets/<item id>`).
  The portal's footer "Terms of Service" and "Privacy Policy" links point to `#`; no site-wide
  terms page exists. Other items on the same portal do carry per-item licence text, so the
  absence here is a per-item choice, not a portal default. Not assumed to be OGL.
- Publisher description, verbatim (2022, 2023, 2024 items): "This file contains charging data
  from sessions completed at DCC-owned public charge points in {year}." 2021 item: "File contains
  all charging sessions at DCC-owned public charge points from end of July 2021 to 31 December
  2021. Any data before the end of July is not accessible to us due to the backoffice change."
  No 2018–2020 files exist.
- A charge-point location feature layer ("All public chargers one layer", item
  6f7be3e24dd344ad8b69027e7ba5ece7, licence also unstated) was queried once for profiling; it
  matches almost none of the usage charge-point ids (docs/PROFILE.md) and is not used.
- Committed: nothing from the files (see ADR-0002); inventory rows and profile aggregates.

## Palo Alto, CA — "Electric Vehicle Charging Station Usage (July 2011 - Dec 2020)"

- **Not downloaded.** The city portal moved from `data.cityofpaloalto.org` (now 404 on every
  path) to `data.paloalto.gov`, whose file endpoint returned HTTP 502 on every attempt on
  2026-09-19. The ORNL mirror named in the brief
  (<https://openenergyhub.ornl.gov/explore/dataset/electric-vehicle-charging-station-usage-july-2011-dec-2020/>)
  is a catalogue stub: `records_count: 0`, `fields: []`, and its CSV export is a header-only file.
- Full-file URL from an archived copy of the dataset page (2026-01-21):
  `https://data.paloalto.gov/datasets/194693-electric-vehicle-charging-station-usage-july-2011-dec-2020.download/`
  (file "ChargePoint Data CY20Q4.csv"; the page's own note says the export button caps at 10,000
  rows and the full file is under Information → "Data Collected from").
- Licence: **unstated at dataset level**. The archived page shows no licence field. The ORNL
  metadata records, verbatim: "No license, or terms of use, asserted by data producer for this
  dataset was found." The city's portal-wide "Open Data Terms and Conditions of Use" (Feb. 16,
  2018, <https://www.paloalto.gov/Departments/Information-Technology/Open-Data-Portal/Terms-of-Use>)
  states, verbatim: "The City grants any interested user (the "User") access to and use of the
  Data subject to the City's Open Data Terms and Conditions of Use (the "Terms") and applicable
  laws." and "The Data, including the Derivative Work, are made available on an "as is" and "as
  available" basis without any express or implied warranty". It names no open licence.
- Committed: nothing. Treated as Dundee once downloadable (ADR-0002).

## Station registry — Alternative Fuel Stations API (US and Canada)

- The brief's host `developer.nrel.gov` no longer resolves. The lab is now the National
  Laboratory of the Rockies; the same API is at `https://developer.nlr.gov`.
- Docs: <https://developer.nlr.gov/docs/transportation/alt-fuel-stations-v1/all/>.
  Endpoint: `GET https://developer.nlr.gov/api/alt-fuel-stations/v1.{json|csv|geojson}?api_key=…&fuel_type=ELEC&state=…&status=all&access=all&limit=all`.
  A `zip` filter works; a `city` filter returned nothing. Rate limit
  (<https://developer.nlr.gov/docs/rate-limits/>): "Hourly Limit: 1,000 requests per hour" per key;
  `DEMO_KEY` "30 requests per IP address per hour" and "50 requests per IP address per day";
  headers `X-RateLimit-Limit` / `X-RateLimit-Remaining`; HTTP 429 on overage.
- Response fields relevant here: `id` ("A unique identifier for this specific station"),
  `station_name`, `street_address`, `city`, `state`, `zip`, `latitude`, `longitude`,
  `ev_level1_evse_num`, `ev_level2_evse_num`, `ev_dc_fast_num`, `ev_connector_types[]`,
  `ev_network`, `ev_network_ids {station, posts, ports}`, `ev_charging_units[]` (per unit:
  `port_count`, `charging_level`, connector `power_kw`), `open_date`, `date_last_confirmed`,
  `updated_at`, `status_code` (E / P / T), `access_code`, `facility_type`.
- Terms, verbatim from <https://afdc.energy.gov/data_download> ("Data Download Terms and
  Conditions"): "These data and software code ("Data") are provided by the National Laboratory of
  the Rockies ("NLR"), which is operated by the Alliance for Energy Innovation, LLC ("Alliance"),
  for the U.S. Department of Energy ("DOE"), and may be used for any purpose whatsoever." and "The
  names DOE/NLR/Alliance shall not be used in any representation, advertising, publicity or other
  manner whatsoever to endorse or promote any entity that adopts or uses the Data." followed by
  an as-is warranty disclaimer, indemnification and limitation of liability.
- Coverage: US and Canada only. Dundee stations are out of coverage and will carry an explicit
  `out_of_coverage` status (Phase 5).
- Status: the registry pull is deferred until `NREL_API_KEY` is set; the response shape above was
  captured with `DEMO_KEY` on one record.

## Inventory of downloaded files

<!-- generated:inventory start -->
<!-- generated:inventory end -->
