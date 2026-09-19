-- Grain: one row per station_id — the current version from the snp_entity snapshot (SCD2).
-- Not exported (meta export=false); downstream marts pick this for "attributes now".
{{ config(materialized='view', meta={'export': false}) }}

select
    cast(station_id as varchar) as station_id,
    cast(station_name as varchar) as station_name,
    cast(channel as varchar) as channel,
    cast(team as varchar) as team,
    cast(as_of_period_key as integer) as version_from_period_key,
    cast(dbt_valid_from as timestamp) as version_valid_from_utc
from {{ ref('snp_entity') }}
where dbt_valid_to is null
