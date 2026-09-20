-- One row per station x station-local date over the station's active window (a spine, so
-- active days with no session carry available minutes and zero usage; excluded days carry
-- zero available minutes; ADR-0011 item 4). Sessions crossing local midnight are split into
-- per-date pieces (ADR-0011 item 5): where the source publishes charging time, energy and
-- charging minutes are allocated over the charging window, assumed to start at session start
-- and last charging_minutes; connected minutes over the connected window (start to end);
-- where the source publishes no charging time (DfT), energy is allocated over the connected
-- window. Sessions are counted on their start date. Measures use non-trivial sessions only
-- (ADR-0007 item 3); trivial sessions are counted separately. Where a source lacks a duration
-- type the measure is null, never zero (ADR-0010 g). available_port_minutes = ports_inferred
-- times the minutes in the local date (1,380 / 1,500 on DST transition days). No ratio is
-- stored here: utilization is always sum over sum at the rollup (macro utilization_ratio).
-- Full rebuild.
{{ config(materialized='table') }}

with stations as (
    select
        station_key,
        source,
        operator_key,
        station_tz,
        capacity_grain,
        ports_inferred,
        active_from,
        active_to
    from {{ ref('dim_station') }}
),

spine as (
    select
        s.station_key,
        s.source,
        s.operator_key,
        s.station_tz,
        s.capacity_grain,
        s.ports_inferred,
        cast(unnest(generate_series(s.active_from, s.active_to, interval 1 day)) as date) as local_date
    from stations as s
),

excluded as (
    select
        sp.station_key,
        sp.local_date
    from spine as sp
    inner join {{ ref('int_station_gaps') }} as g
        on
            sp.station_key = g.station_key
            and sp.local_date > g.gap_after_date
            and sp.local_date < g.gap_before_date
),

sessions as (
    select
        f.session_sk,
        f.station_key,
        f.is_non_trivial,
        f.start_utc,
        f.end_utc,
        f.start_local,
        f.end_local,
        f.energy_kwh,
        f.charging_minutes,
        f.connected_minutes,
        f.start_tz,
        case
            when f.charging_minutes is not null
                then f.start_utc + to_minutes(cast(round(f.charging_minutes * 60) as bigint)) / 60
        end as charging_end_utc,
        cast(f.start_local as date) as start_date,
        cast(
            coalesce(
                f.end_local,
                f.start_local + to_minutes(cast(round(coalesce(f.charging_minutes, 0)) as bigint))
            ) as date
        ) as last_date
    from {{ ref('fct_charging_session') }} as f
),

pieces as (
    select
        s.*,
        cast(unnest(generate_series(s.start_date, s.last_date, interval 1 day)) as date) as local_date
    from sessions as s
),

measured as (
    select
        p.station_key,
        p.local_date,
        p.session_sk,
        p.is_non_trivial,
        p.local_date = p.start_date as is_start_day,
        timezone(p.start_tz, cast(p.local_date as timestamp)) as day_start_utc,
        timezone(p.start_tz, cast(p.local_date + interval 1 day as timestamp)) as day_end_utc,
        p.energy_kwh,
        p.charging_minutes,
        p.connected_minutes,
        case
            when p.end_utc is not null
                then {{ overlap_minutes('p.start_utc', 'p.end_utc', 'timezone(p.start_tz, cast(p.local_date as timestamp))', 'timezone(p.start_tz, cast(p.local_date + interval 1 day as timestamp))') }}
        end as connected_piece,
        case
            when p.charging_end_utc is not null
                then {{ overlap_minutes('p.start_utc', 'p.charging_end_utc', 'timezone(p.start_tz, cast(p.local_date as timestamp))', 'timezone(p.start_tz, cast(p.local_date + interval 1 day as timestamp))') }}
        end as charging_piece
    from pieces as p
),

allocated as (
    select
        *,
        case
            when charging_minutes is not null and charging_minutes > 0
                then energy_kwh * charging_piece / charging_minutes
            when charging_minutes is null and connected_minutes is not null and connected_minutes > 0
                then energy_kwh * connected_piece / connected_minutes
            when is_start_day then energy_kwh
            else 0
        end as energy_piece
    from measured
),

usage as (
    select
        station_key,
        local_date,
        count(*) filter (where is_start_day and is_non_trivial) as sessions,
        count(*) filter (where is_start_day and not is_non_trivial) as trivial_sessions,
        sum(energy_piece) filter (where is_non_trivial) as energy_kwh,
        sum(charging_piece) filter (where is_non_trivial) as charging_minutes,
        sum(connected_piece) filter (where is_non_trivial) as connected_minutes,
        count(charging_piece) filter (where is_non_trivial) as charging_pieces,
        count(connected_piece) filter (where is_non_trivial) as connected_pieces
    from allocated
    group by station_key, local_date
)

select
    sp.station_key,
    sp.local_date,
    sp.source,
    sp.operator_key,
    sp.capacity_grain,
    sp.ports_inferred,
    e.station_key is not null as is_excluded_day,
    {{ local_day_minutes('sp.local_date', 'sp.station_tz') }} as day_minutes,
    case when e.station_key is not null then 0 else sp.ports_inferred * {{ local_day_minutes('sp.local_date', 'sp.station_tz') }} end
        as available_port_minutes,
    coalesce(u.sessions, 0) as sessions,
    coalesce(u.trivial_sessions, 0) as trivial_sessions,
    u.energy_kwh,
    u.charging_minutes,
    u.connected_minutes,
    coalesce(u.charging_pieces, 0) as charging_pieces,
    coalesce(u.connected_pieces, 0) as connected_pieces,
    case when u.charging_minutes is not null and u.connected_minutes is not null then greatest(u.connected_minutes - u.charging_minutes, 0) end
        as idle_minutes
from spine as sp
left join excluded as e on sp.station_key = e.station_key and sp.local_date = e.local_date
left join usage as u on sp.station_key = u.station_key and sp.local_date = u.local_date
