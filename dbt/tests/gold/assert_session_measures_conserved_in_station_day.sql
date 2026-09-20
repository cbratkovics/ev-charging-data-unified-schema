-- The midnight split conserves the measures: per source, energy, charging and connected
-- minutes summed over fct_station_day equal the sums over non-trivial sessions in
-- fct_charging_session (to 1e-6 relative), and session counts match exactly.
with sessions as (
    select
        source,
        count(*) filter (where is_non_trivial) as sessions,
        sum(energy_kwh) filter (where is_non_trivial) as energy_kwh,
        sum(charging_minutes) filter (where is_non_trivial) as charging_minutes,
        sum(connected_minutes) filter (where is_non_trivial) as connected_minutes
    from {{ ref('fct_charging_session') }}
    group by source
),

days as (
    select
        source,
        sum(sessions) as sessions,
        sum(energy_kwh) as energy_kwh,
        sum(charging_minutes) as charging_minutes,
        sum(connected_minutes) as connected_minutes
    from {{ ref('fct_station_day') }}
    group by source
)

select
    s.source,
    s.sessions as session_rows,
    d.sessions as day_rows,
    s.energy_kwh as session_kwh,
    d.energy_kwh as day_kwh
from sessions as s
inner join days as d on s.source = d.source
where
    s.sessions <> d.sessions
    or abs(coalesce(s.energy_kwh, 0) - coalesce(d.energy_kwh, 0)) > 1e-6 * greatest(abs(coalesce(s.energy_kwh, 0)), 1)
    or abs(coalesce(s.charging_minutes, 0) - coalesce(d.charging_minutes, 0)) > 1e-6 * greatest(abs(coalesce(s.charging_minutes, 0)), 1)
    or abs(coalesce(s.connected_minutes, 0) - coalesce(d.connected_minutes, 0)) > 1e-6 * greatest(abs(coalesce(s.connected_minutes, 0)), 1)
    or (s.charging_minutes is null) <> (d.charging_minutes is null)
    or (s.connected_minutes is null) <> (d.connected_minutes is null)
