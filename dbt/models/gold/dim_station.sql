-- One row per station key with the inferred capacity and the active window (ADR-0006,
-- ADR-0007 item 4, ADR-0011 item 7). Full rebuild every run because every attribute depends
-- on the whole history. The station key is a unit (a Boulder or Cary station name, a DfT
-- charge-point id); port-level keys are not built, so capacity_grain is 'unit' throughout and
-- ports_inferred counts the ports of that unit. Ports: distinct connector ids where the unit
-- publishes any, else the robust max of observed concurrency (highest level reached on at
-- least 5 distinct local dates, over non-trivial sessions; the charging window stands in for
-- the connected window where the source has no end time), floored at 1. Port counts are
-- inferred, not inventoried: they undercount ports never used concurrently and overcount where
-- overlapping records are data errors; availability is assumed 24 hours within the active
-- window (docs/BRIEF.md § 5, README limitations).
{{ config(materialized='table') }}

{% set robust_n = 5 %}
{% set levels = [1, 2, 3, 4, 5, 6, 7, 8] %}

with sessions as (
    select
        station_key,
        source,
        operator_key,
        site_key,
        station_name_raw,
        start_tz,
        start_utc,
        start_local,
        end_local,
        coalesce(end_utc, start_utc + to_minutes(cast(round(charging_minutes) as bigint))) as end_eff_utc,
        coalesce(end_local, start_local + to_minutes(cast(round(charging_minutes) as bigint))) as end_eff_local,
        port_id
    from {{ ref('fct_charging_session') }}
    where is_non_trivial
),

per_station as (
    select
        station_key,
        any_value(source) as source,
        any_value(operator_key) as operator_key,
        any_value(site_key) as site_key,
        any_value(station_name_raw) as station_name_raw,
        any_value(start_tz) as station_tz,
        count(*) as non_trivial_sessions,
        count(distinct cast(start_local as date)) as active_days,
        min(cast(start_local as date)) as active_from,
        max(cast(end_eff_local as date)) as active_to,
        count(distinct port_id) as connector_ids
    from sessions
    group by station_key
),

events as (
    select
        station_key,
        start_utc as t,
        1 as d,
        cast(start_local as date) as local_date
    from sessions
    union all
    select
        station_key,
        end_eff_utc as t,
        -1 as d,
        null as local_date
    from sessions
),

running as (
    select
        station_key,
        d,
        local_date,
        sum(d) over (
            partition by station_key
            order by t asc, d asc
            rows between unbounded preceding and current row
        ) as concurrency
    from events
),

days_at_level as (
    select
        r.station_key,
        lvl.k,
        count(distinct r.local_date) as days
    from running as r
    cross join unnest([{{ levels | join(', ') }}]) as lvl (k)
    where r.d = 1 and r.concurrency >= lvl.k
    group by r.station_key, lvl.k
),

robust as (
    select
        station_key,
        max(k) filter (where days >= {{ robust_n }}) as robust_max_n5,
        max(k) filter (where days >= 1) as plain_max
    from days_at_level
    group by station_key
),

gaps as (
    select
        station_key,
        sum(excluded_days) as excluded_days,
        count(*) as excluded_gaps
    from {{ ref('int_station_gaps') }}
    group by station_key
),

data_as_of as (
    select
        source,
        max(retrieved_at_utc) as data_as_of_utc
    from {{ ref('meta_landed_files') }}
    group by source
)

select
    p.station_key,
    p.source,
    p.operator_key,
    p.site_key,
    p.station_name_raw,
    p.station_tz,
    'unit' as capacity_grain,
    cast(
        case
            when p.connector_ids > 0 then p.connector_ids
            else greatest(coalesce(r.robust_max_n5, 0), 1)
        end as integer
    ) as ports_inferred,
    case
        when p.connector_ids > 0 then 'connector_ids'
        when coalesce(r.robust_max_n5, 0) >= 1 then 'observed_concurrency'
        else 'floor'
    end as ports_source,
    {{ robust_n }} as ports_inferred_n,
    r.robust_max_n5,
    r.plain_max as plain_max_concurrency,
    p.connector_ids,
    p.active_days < {{ robust_n }} as low_evidence,
    p.non_trivial_sessions,
    p.active_days,
    p.active_from,
    p.active_to,
    cast(p.active_to - p.active_from as integer) + 1 as window_days,
    cast(coalesce(g.excluded_days, 0) as bigint) as excluded_days,
    coalesce(g.excluded_gaps, 0) as excluded_gaps,
    case p.source when 'dft_2017' then 'out_of_coverage' else 'unmatched' end as registry_match_status,
    cast(null as integer) as ports_registry,
    d.data_as_of_utc
from per_station as p
left join robust as r on p.station_key = r.station_key
left join gaps as g on p.station_key = g.station_key
left join data_as_of as d on p.source = d.source
