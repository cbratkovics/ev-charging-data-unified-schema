-- Monthly rollup at source x operator x calendar month of the station-local date: sums of the
-- station-day measures plus the counts needed to recompute any ratio (utilization = sum of a
-- measure over sum of available port minutes, never an average of daily ratios). No ratio is
-- stored. Null measures stay null (a source without that duration type). Full rebuild.
{{ config(materialized='table') }}

select
    source,
    operator_key,
    cast(strftime(local_date, '%Y-%m') as varchar) as year_month,
    count(*) as station_days,
    count(*) filter (where is_excluded_day) as excluded_station_days,
    count(distinct station_key) as stations,
    sum(sessions) as sessions,
    sum(trivial_sessions) as trivial_sessions,
    sum(energy_kwh) as energy_kwh,
    sum(charging_minutes) as charging_minutes,
    sum(connected_minutes) as connected_minutes,
    sum(idle_minutes) as idle_minutes,
    sum(available_port_minutes) as available_port_minutes,
    sum(charging_pieces) as charging_pieces,
    sum(connected_pieces) as connected_pieces
from {{ ref('fct_station_day') }}
group by source, operator_key, year_month
