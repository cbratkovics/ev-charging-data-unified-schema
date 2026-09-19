-- Grain: one row per (station_id, period_key) for every period a prediction exists for: the
-- entity's attributes as they were when that period was scored, from the snp_entity SCD2 history.
-- A version captured with data through period K is the state used to score periods K+1 .. K'
-- (the next version's capture period). Periods before the first capture, and entities captured
-- later than the period, fall back to the current version with is_exact_asof = false.
{{ config(materialized='view', meta={'export': false}) }}

with periods as (
    select distinct
        station_id,
        period_key
    from {{ ref('slv_predictions') }}
),

history as (
    select
        station_id,
        station_name,
        channel,
        team,
        as_of_period_key as valid_from_period_key,
        lead(as_of_period_key) over (partition by station_id order by dbt_valid_from) as valid_to_period_key,
        dbt_valid_from
    from {{ ref('snp_entity') }}
),

matched as (
    select
        p.station_id,
        p.period_key,
        h.station_name,
        h.channel,
        h.team,
        h.valid_from_period_key,
        h.dbt_valid_from
    from periods as p
    left join history as h
        on
            p.station_id = h.station_id
            and p.period_key > h.valid_from_period_key
            and (h.valid_to_period_key is null or p.period_key <= h.valid_to_period_key)
)

select
    cast(m.station_id as varchar) as station_id,
    cast(m.period_key as integer) as period_key,
    cast(coalesce(m.station_name, c.station_name) as varchar) as station_name,
    cast(coalesce(m.channel, c.channel) as varchar) as channel,
    cast(coalesce(m.team, c.team) as varchar) as team,
    cast(m.valid_from_period_key is not null as boolean) as is_exact_asof,
    cast(coalesce(m.valid_from_period_key, c.version_from_period_key) as integer) as version_from_period_key,
    cast(coalesce(m.dbt_valid_from, c.version_valid_from_utc) as timestamp) as version_valid_from_utc
from matched as m
left join {{ ref('dim_entity_current') }} as c on m.station_id = c.station_id
