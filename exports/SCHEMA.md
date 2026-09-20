# exports/ — the read contract

_Written by `scripts/export.py` from the gold layer; do not edit by hand. Every file is listed in `manifest.json` with its row count, byte size and sha256. Rows are sorted by the grain key, so two builds of the same inputs produce identical bytes._

Grain: station-day and above only; no session-grain rows are exported (ADR-0015).

## Attribution and licences

Contains public sector information licensed under the Open Government Licence v3.0 (UK Department for Transport, Electric Chargepoint Analysis 2017). Boulder, CO and Cary, NC data are published under CC0; see docs/DATA_SOURCES.md for the verbatim licences and URLs.

| Source | Licence | Where stated |
|---|---|---|
| Boulder, CO | CC0 ("CC0 License", linked to CC0 1.0) | ArcGIS item metadata, `licenseInfo` |
| Cary, NC | CC0 1.0 Universal | Opendatasoft dataset metadata, `license` and `license_url` |
| UK Department for Transport, 2017 | Open Government Licence v3.0 | both publication pages on gov.uk |

Utilization is never stored: compute it as a ratio of sums (a measure's minutes over `available_port_minutes`) at whatever rollup you need.

## `dim_date`

One row per calendar date spanning every station's active window. Full rebuild.

Grain: date_key. Formats: parquet, json. Rows: 4,200.

| Column | Type | Description |
|---|---|---|
| `date_key` | date | calendar date |
| `year` | integer | year |
| `month` | integer | month 1..12 |
| `day_of_month` | integer | day of month |
| `iso_day_of_week` | integer | 1 = Monday .. 7 = Sunday |
| `is_weekend` | boolean | Saturday or Sunday |
| `year_month` | varchar | YYYY-MM |

## `dim_operator`

One row per operator: the three publishers and one row per DfT funding body with the publisher as parent. Full rebuild.

Grain: operator_key. Formats: parquet, json. Rows: 67.

| Column | Type | Description |
|---|---|---|
| `operator_key` | varchar | operator identifier; sessions carry it |
| `operator_name` | varchar | display name |
| `source` | varchar | source short name |
| `parent_operator_key` | varchar | the publisher for DfT funding bodies; null for publishers |
| `country` | varchar | ISO country of the operator |
| `timezone` | varchar | IANA zone of the operator's stations |

## `dim_station`

One row per station key (a unit) with inferred capacity, active window and excluded days (ADR-0006, ADR-0007 item 4, ADR-0011 item 7). Port counts are inferred as the larger of the connector-id count and the observed-concurrency robust max, not inventoried: they undercount ports never used concurrently and overcount where overlapping records are data errors; availability is assumed 24 hours a day within the active window. Full rebuild.

Grain: station_key. Formats: parquet, json. Rows: 908.

| Column | Type | Description |
|---|---|---|
| `station_key` | varchar | station identifier |
| `source` | varchar | source short name |
| `operator_key` | varchar | operator |
| `site_key` | varchar | site grouping |
| `station_name_raw` | varchar | the publisher's station identifier |
| `station_tz` | varchar | IANA zone |
| `capacity_grain` | varchar | grain of the station key: unit throughout (port-level keys are not built; ADR-0005 d) |
| `ports_inferred` | integer | ports in service: the larger of the distinct published connector ids and the robust max of observed concurrency at N = 5 over non-trivial sessions, floored at 1; both are lower bounds on the true count (ADR-0012) |
| `ports_source` | varchar | which lower bound was binding: connector_ids, observed_concurrency, or floor when neither reached 1 |
| `ports_inferred_n` | integer | the N of the robust max (distinct active dates a level must be reached on) |
| `robust_max_n5` | integer | highest concurrency level reached on at least N distinct dates; null when none |
| `plain_max_concurrency` | integer | highest concurrency level reached on any date |
| `connector_ids` | bigint | distinct connector ids published for the unit (DfT) |
| `low_evidence` | boolean | fewer than N active dates: the inferred port count rests on little evidence |
| `non_trivial_sessions` | bigint | non-trivial sessions at the unit |
| `active_days` | bigint | distinct local dates with a non-trivial session start |
| `active_from` | date | first non-trivial session date |
| `active_to` | date | last non-trivial session end date |
| `window_days` | integer | dates in the active window |
| `excluded_days` | bigint | dates inside gaps over the source threshold, excluded from availability |
| `excluded_gaps` | bigint | number of such gaps |
| `data_as_of_utc` | timestamp with time zone | latest retrieval time of the source's landed files; drives the snapshot's validity stamps (ADR-0011 item 6) |

## `fct_station_day`

One row per station x station-local date over the station's active window (spine), with sessions crossing midnight split into per-date pieces. Energy and charging minutes are allocated over the charging window, assumed to begin at session start, where the source publishes charging time; over the connected window where it does not (DfT). Connected minutes are allocated over the connected window. Measures use non-trivial sessions only; a source's absent duration type is null, never zero. available_port_minutes = ports_inferred x minutes in the local date (1,380 or 1,500 on DST days); 0 on excluded days. No ratio is stored: utilization is sum over sum at the rollup (macro utilization_ratio). Full rebuild.

Grain: station_key, local_date. Formats: parquet. Rows: 306,091.

| Column | Type | Description |
|---|---|---|
| `station_key` | varchar | station identifier |
| `local_date` | date | station-local calendar date |
| `source` | varchar | source short name |
| `operator_key` | varchar | operator |
| `capacity_grain` | varchar | grain of the station key (unit) |
| `ports_inferred` | integer | the station's inferred ports (denominator basis) |
| `is_excluded_day` | boolean | date lies inside a zero-session gap over the source threshold; availability is 0 |
| `day_minutes` | double | minutes in the local date: 1440, or 1380 / 1500 on DST transition days |
| `available_port_minutes` | double | ports_inferred x day_minutes on available days; 0 on excluded days |
| `sessions` | bigint | non-trivial sessions starting on the date |
| `trivial_sessions` | bigint | trivial sessions starting on the date (not in the measures) |
| `energy_kwh` | double | energy allocated to the date (non-trivial sessions); null when no non-trivial piece falls on it |
| `charging_minutes` | double | charging minutes allocated to the date; null where the source has no charging time or no piece falls on it |
| `connected_minutes` | double | connected minutes allocated to the date; null where the source has no end time or no piece falls on it |
| `charging_pieces` | bigint | session pieces contributing charging minutes (visibility of nulls in rollups) |
| `connected_pieces` | bigint | session pieces contributing connected minutes |
| `idle_minutes` | double | connected minus charging, clamped at zero, where both exist (Boulder) |

## `mart_monthly`

Monthly rollup at source x operator x calendar month (station-local dates): sums of the station-day measures and the counts needed to recompute any ratio; no ratio is stored (utilization is sum over sum at any rollup). Null measures stay null where the source lacks that duration type. Exported as Parquet and JSON.

Grain: source, operator_key, year_month. Formats: parquet, json. Rows: 877.

| Column | Type | Description |
|---|---|---|
| `source` | varchar | source short name |
| `operator_key` | varchar | operator |
| `year_month` | varchar | YYYY-MM of the station-local date |
| `station_days` | bigint | station-day rows in the month (spine rows, excluded days included) |
| `excluded_station_days` | bigint | station-days inside a zero-session gap (availability 0) |
| `stations` | bigint | distinct stations with a row in the month |
| `sessions` | hugeint | non-trivial sessions starting in the month |
| `trivial_sessions` | hugeint | trivial sessions starting in the month |
| `energy_kwh` | double | energy allocated to the month's station-days (non-trivial sessions) |
| `charging_minutes` | double | charging minutes allocated; null where the source has no charging time |
| `connected_minutes` | double | connected minutes allocated; null where the source has no end time |
| `idle_minutes` | double | idle minutes (connected minus charging, clamped) where both exist |
| `available_port_minutes` | double | sum of ports_inferred x day minutes over available station-days |
| `charging_pieces` | hugeint | session pieces contributing charging minutes |
| `connected_pieces` | hugeint | session pieces contributing connected minutes |
