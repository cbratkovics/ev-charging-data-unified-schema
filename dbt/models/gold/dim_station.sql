-- One row per station key with the inferred capacity and the active window (ADR-0006,
-- ADR-0007 item 4, ADR-0011 item 7). Full rebuild every run because every attribute depends
-- on the whole history. The station key is a unit (a Boulder or Cary station name, a DfT
-- charge-point id); port-level keys are not built, so capacity_grain is 'unit' throughout and
-- ports_inferred counts the ports of that unit. Ports: the larger of the distinct published
-- connector ids and the robust max of observed concurrency (highest level reached on at least
-- 5 distinct local dates, over non-trivial sessions; the charging window stands in for the
-- connected window where the source has no end time), floored at 1; both are lower bounds on
-- the true count and ports_source names the one that was binding (ADR-0012). Port counts are
-- inferred, not inventoried: they undercount ports never used concurrently and overcount where
-- overlapping records are data errors; availability is assumed 24 hours within the active
-- window (docs/BRIEF.md § 5, README limitations). Unknown-station keys (dft_2017/unknown/<Name>)
-- are not stations and are excluded here and from fct_station_day (ADR-0007 item 1).
-- Descriptive attributes (site_key, station_name_raw, source, station_tz) follow the majority
-- rule (ADR-0016): the value carried by the most non-trivial sessions, ties broken by the value
-- itself, nulls never competing; operator_key is derived from the chosen site exactly as the
-- session fact derives it. multi_site_key / multi_operator flag stations whose sessions carried
-- more than one value; every window and pick ends in a unique key so a rebuild is identical.
{{ config(materialized='table') }}

{% set robust_n = 5 %}
{% set levels = [1, 2, 3, 4, 5, 6, 7, 8] %}

with sessions as (
    select
        session_sk,
        station_key,
        source,
        operator_key,
        site_key,
        station_name_raw,
        start_tz,
        start_utc,
        start_local,
        end_local,
        -- effective end at second precision: rounding to whole minutes overlapped back-to-back
        -- sessions at single-port stations and inflated the inferred ports (ADR-0014)
        coalesce(end_utc, start_utc + to_seconds(cast(round(charging_minutes * 60) as bigint))) as end_eff_utc,
        coalesce(end_local, start_local + to_seconds(cast(round(charging_minutes * 60) as bigint))) as end_eff_local,
        port_id
    from {{ ref('fct_charging_session') }}
    -- unknown-station keys (a null CPID under a funding body) stay in the session fact and its
    -- totals but have no capacity or utilization (ADR-0007 item 1)
    where is_non_trivial and not contains(station_key, '/unknown/')
),

per_station as (
    select
        station_key,
        count(*) as non_trivial_sessions,
        count(distinct cast(start_local as date)) as active_days,
        min(cast(start_local as date)) as active_from,
        max(cast(end_eff_local as date)) as active_to,
        count(distinct port_id) as connector_ids,
        count(distinct site_key) as site_key_candidates,
        count(distinct operator_key) as operator_candidates
    from sessions
    group by station_key
),

-- the majority rule per attribute: most sessions, then the value itself; nulls do not compete
{% for col in ['source', 'site_key', 'station_name_raw', 'start_tz'] %}
pick_{{ col }} as (
    select
        station_key,
        {{ col }}
    from (
        select
            station_key,
            {{ col }},
            count(*) as n
        from sessions
        where {{ col }} is not null
        group by station_key, {{ col }}
    )
    qualify row_number() over (partition by station_key order by n desc, {{ col }} asc) = 1
),
{% endfor %}

events as (
    select
        session_sk,
        station_key,
        start_utc as t,
        1 as d,
        cast(start_local as date) as local_date
    from sessions
    union all
    select
        session_sk,
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
            order by t asc, d asc, session_sk asc
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
    ps.source,
    -- the same derivation as fct_charging_session.operator_key, applied to the chosen site
    case when ps.source = 'dft_2017' then 'dft_2017/' || coalesce(pk.site_key, '<null>') else ps.source end
        as operator_key,
    pk.site_key,
    pn.station_name_raw,
    pt.start_tz as station_tz,
    p.site_key_candidates > 1 as multi_site_key,
    p.operator_candidates > 1 as multi_operator,
    p.site_key_candidates,
    p.operator_candidates,
    'unit' as capacity_grain,
    -- both counts are lower bounds on the true ports; the larger is the tighter bound (ADR-0012)
    cast(greatest(p.connector_ids, coalesce(r.robust_max_n5, 0), 1) as integer) as ports_inferred,
    case
        when greatest(p.connector_ids, coalesce(r.robust_max_n5, 0)) < 1 then 'floor'
        when p.connector_ids >= coalesce(r.robust_max_n5, 0) then 'connector_ids'
        else 'observed_concurrency'
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
    d.data_as_of_utc
from per_station as p
inner join pick_source as ps on p.station_key = ps.station_key
left join pick_site_key as pk on p.station_key = pk.station_key
left join pick_station_name_raw as pn on p.station_key = pn.station_key
inner join pick_start_tz as pt on p.station_key = pt.station_key
left join robust as r on p.station_key = r.station_key
left join gaps as g on p.station_key = g.station_key
left join data_as_of as d on ps.source = d.source
