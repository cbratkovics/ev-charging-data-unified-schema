-- Zero-session gaps longer than the source's threshold between consecutive non-trivial sessions
-- at a station (ADR-0006 g). The gap runs from the previous session's effective end (its end,
-- or start plus charging minutes where the source has no end) to the next session's start; the dates strictly between are
-- excluded from availability. Thresholds: Boulder 30 days, DfT 90 days, Cary 30 days, from the
-- 99.9th percentile of inter-session gaps in the profile artifact. Not exported.
{{ config(materialized='table', meta={'export': false}) }}

with sessions as (
    select
        station_key,
        source,
        start_utc,
        cast(start_local as date) as start_date,
        charging_minutes,
        cast(coalesce(end_local, start_local + to_minutes(cast(round(coalesce(charging_minutes, 0)) as bigint))) as date) as end_date,
        coalesce(end_utc, start_utc + to_minutes(cast(round(coalesce(charging_minutes, 0)) as bigint))) as end_eff_utc
    from {{ ref('fct_charging_session') }}
    where is_non_trivial
),

ordered as (
    select
        *,
        lead(start_utc) over (partition by station_key order by start_utc, end_eff_utc) as next_start_utc,
        lead(start_date) over (partition by station_key order by start_utc, end_eff_utc) as next_start_date
    from sessions
),

gaps as (
    select
        station_key,
        source,
        end_date as gap_after_date,
        next_start_date as gap_before_date,
        (epoch(next_start_utc) - epoch(end_eff_utc)) / 86400.0 as gap_days,
        case source
            when 'boulder' then 30
            when 'cary' then 30
            when 'dft_2017' then 90
        end as threshold_days
    from ordered
    where next_start_utc is not null
)

select
    station_key,
    source,
    gap_after_date,
    gap_before_date,
    gap_days,
    threshold_days,
    greatest(cast(gap_before_date - gap_after_date as integer) - 1, 0) as excluded_days
from gaps
where gap_days > threshold_days
