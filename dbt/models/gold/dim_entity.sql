-- Grain: one row per station_id. Current (latest-seen) attributes, no history (history:
-- snapshot snp_entity, views dim_entity_current / dim_entity_asof). Newest source row wins;
-- entities known only from a prediction file fall back to it.
with from_rows as (
    select
        station_id,
        station_name,
        channel,
        team,
        min(day) over (partition by station_id) as first_season,
        day as last_season,
        day as last_period,
        count(*) over (partition by station_id) as rows_played,
        row_number() over (partition by station_id order by period_key desc) as rn
    from {{ ref('slv_period_rows') }}
),

from_predictions as (
    select
        station_id,
        station_name,
        channel,
        team,
        row_number() over (partition by station_id order by period_key desc, candidate asc) as rn
    from {{ ref('slv_predictions') }}
),

ids as (
    select station_id from from_rows
    union
    select station_id from from_predictions
)

select
    cast(i.station_id as varchar) as station_id,
    cast(coalesce(r.station_name, p.station_name) as varchar) as station_name,
    cast(coalesce(r.channel, p.channel) as varchar) as channel,
    cast(coalesce(r.team, p.team) as varchar) as team,
    cast(r.first_season as integer) as first_season,
    cast(r.last_season as integer) as last_season,
    cast(r.last_period as integer) as last_period,
    cast(coalesce(r.rows_played, 0) as integer) as rows_played,
    cast(case when r.station_id is not null then 'rows' else 'predictions' end as varchar) as attribute_source
from ids as i
left join from_rows as r on i.station_id = r.station_id and r.rn = 1
left join from_predictions as p on i.station_id = p.station_id and p.rn = 1
