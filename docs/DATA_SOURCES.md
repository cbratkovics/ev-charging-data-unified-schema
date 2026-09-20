# Data sources

Three public session sources, every one under an explicit open licence
(docs/adr/0004-source-policy.md). Per source: the exact endpoints used, the licence
**verbatim as published** with the URL it was read from, and what this repository commits
(docs/adr/0002-source-redistribution.md). Retrieval time, size, row count and SHA-256 of every
downloaded file are in the generated inventory at the end of this page; the full hashes are in
`artifacts/profile/<run_id>.json`. Discovery was done on 2026-09-19.

Attribution required by the Open Government Licence: *Contains public sector information
licensed under the Open Government Licence v3.0.*

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

## UK Department for Transport — "Electric Chargepoint Analysis 2017"

Two statistical releases with raw charging-event files: Local Authority Rapids (revised
13 December 2018) and Public Sector Fasts (published 13 December 2018). Both are badged
Experimental Statistics by the publisher.

- Publication pages:
  - Rapids: <https://www.gov.uk/government/statistics/electric-chargepoint-analysis-2017-local-authority-rapids>
    (published 21 June 2018, last updated 13 December 2018)
  - Fasts: <https://www.gov.uk/government/statistics/electric-chargepoint-analysis-2017-public-sector-fasts>
    (published 13 December 2018)
- Files used (all `assets.publishing.service.gov.uk`):
  - Rapids raw data (revised): `https://assets.publishing.service.gov.uk/media/5c1147ece5274a0bcac5f8d5/electric-chargepoint-analysis-2017-raw-rapids-data.csv`
  - Rapids incomplete or anomalous raw data (revised): `https://assets.publishing.service.gov.uk/media/5c114827e5274a0bd964df2b/electric-chargepoint-analysis-2017-rapids-incomplete-anomalies.csv`
  - Fasts raw data: `https://assets.publishing.service.gov.uk/media/5c128fa5e5274a0ba8c4ba79/electric-chargepoint-analysis-2017-raw-public-sector-fasts-data.csv`
  - Fasts incomplete or anomalous raw data: `https://assets.publishing.service.gov.uk/media/5c128de8e5274a0ae06bd792/electric-chargepoint-analysis-2017-public-sector-fasts-incomplete-anomalies.csv`
  - The two PDF reports (rapids revised, fasts) for definitions; not data.
- Licence, verbatim from both publication pages: "All content is available under the Open
  Government Licence v3.0, except where otherwise stated", linked to
  <https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/>, with
  "© Crown copyright". The licence grants, verbatim: "copy, publish, distribute and transmit the
  Information; adapt the Information; exploit the Information commercially and non-commercially"
  and requires that you "acknowledge the source of the Information in your product or application
  by including or linking to any attribution statement specified by the Information Provider(s)";
  the default statement is "Contains public sector information licensed under the Open Government
  Licence v3.0." Read from the OGL page above.
- What the revised rapids release changed, verbatim from the publication page: "The original
  release omitted data from Cornwall Council, approximately 2,500 charging events. This has now
  been added to the underlying data and analysis presented in this release. Some of the chargepoints
  reported to DfT as rapids were actually fast chargers. Charging events from fast chargers have
  been removed and added to our separate publication on Public Sector Fasts. This removed
  approximately 25,000 events from the dataset and resulted in slightly higher average energy
  supplied per event and shorter average durations. Most of the figures in the release have been
  revised. Further analysis has revealed that several local authorities received funding for
  chargepoints outside their geographical boundaries, for example via joint bids. Therefore the
  local authority name does not indicate where the chargepoint is located. Less than half of the
  chargepoints had an identifiable location, so geographical analysis is not possible and the local
  authority map has been removed."
- Publisher's exclusion rule, verbatim (rapids report p2; the fasts report says the same): "All
  analyses are restricted to those charging events that actually drew some positive charge.
  Plug-in events that registered no electric charge or were less than or equal to 3 minutes in
  length were excluded." Rapids report p14: "Some data has also had to be excluded because it is
  incomplete, for example no start time or start day, end day or end time. Some events that were
  not consistent with local rapid chargepoints, and assumed to be accidentally included from other
  schemes, have also been excluded." and "Depending on the source of the data, there can be marked
  differences in how the individual charging events have been recorded. With the example of charge
  time, some organisations and local authorities have rounded their start and end time to the
  nearest half hour while others have provided the exact hours, minutes and seconds." Events over
  100 kWh were excluded from the analysis (report p14 note). The "incomplete or anomalous" files
  are the rows the publisher excluded; this project lands them too so the exclusion is reproduced
  in silver, not inherited.
- Publisher's caveats, verbatim (fasts report p2): "Around 6,000 charging events did not have any
  chargepoint identifier. It is also possible that chargepoint identifiers may not be consistent
  across time, and a single chargepoint may have more than one ID in the dataset. For this reason,
  the number of chargepoints should be read as an estimate." and p9: "We attempted to match
  provided chargepoint IDs to the National Chargepoint Registry in order to determine the location
  of the chargepoints. A basic matching exercise resulted in less than 10% of IDs matching."
- Plug-in duration: the reports describe "plug-in duration" as the time the vehicle was plugged
  in; charging (energy-drawing) time is not recorded ("it is not possible to identify when the
  vehicle was actually drawing charge", fasts report p1). The published `PluginDuration` column is
  in minutes in the rapids raw file and in hours in the two fasts files (docs/PROFILE.md); the
  rapids anomalies file has no duration column and day-first dates.
- Timezone: not stated by the publisher. Timestamps are treated as UK local wall-clock time
  (`Europe/London`); docs/PROFILE.md records the evidence.
- Committed: nothing from the files (ADR-0002); inventory rows and profile aggregates.

## Inventory of downloaded files

<!-- generated:inventory start -->
_Generated by `scripts/render_profile.py` from `artifacts/profile/profile-20260920T025421Z.json` (code commit `29a5bfe19536`); full hashes are in the artifact._

| Source | File | Retrieved (UTC) | Bytes | Data rows | SHA-256 (prefix) |
|---|---|---|---|---|---|
| Boulder, CO | `Electric_Vehicle_Charging_Station_Data.csv` | 2026-09-19T23:10:30+00:00 | 23,276,419 | 148,136 | `f1f620bb616fa6c0…` |
| Cary, NC | `electric-vehicle-charging-stations.csv` | 2026-09-19T23:08:39+00:00 | 2,500,986 | 20,142 | `9f8037bfd9246cce…` |
| UK DfT, Electric Chargepoint Analysis 2017 | `dft_2017_local_authority_rapids_raw.csv` | 2026-09-19T23:38:54+00:00 | 11,744,472 | 108,746 | `466c9b55bbdf6fce…` |
| UK DfT, Electric Chargepoint Analysis 2017 | `dft_2017_local_authority_rapids_incomplete_anomalies.csv` | 2026-09-19T23:38:58+00:00 | 4,895,356 | 48,619 | `169c0c359544fb43…` |
| UK DfT, Electric Chargepoint Analysis 2017 | `dft_2017_public_sector_fasts_raw.csv` | 2026-09-19T23:39:02+00:00 | 11,819,515 | 103,326 | `c96a8c06b54c6591…` |
| UK DfT, Electric Chargepoint Analysis 2017 | `dft_2017_public_sector_fasts_incomplete_anomalies.csv` | 2026-09-19T23:39:05+00:00 | 1,240,348 | 11,606 | `e0dd59631bc42799…` |
<!-- generated:inventory end -->
