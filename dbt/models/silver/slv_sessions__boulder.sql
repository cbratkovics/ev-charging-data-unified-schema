-- Boulder, CO conformed sessions: one row per bronze row (accepted rows carry a null
-- primary_reason; slv_sessions_unioned / slv_sessions_quarantined split on it, so
-- bronze = accepted + quarantined holds by construction). Rules: docs/BRIEF.md § 5,
-- ADR-0005 (a, b), ADR-0009 (DST edge cases, quarantine precedence, deterministic dedup).
{{ config(materialized='table') }}

{% set zone = 'America/Denver' %}
{% set kw_ceiling = implied_kw_ceiling("'boulder'") %}
{% set reasons = session_quarantine_rules(kw_ceiling) %}
{% set flags = session_quality_flags() %}

with src as (
    select * from {{ ref('brz_boulder') }}
),

typed as (
    select
        _row_hash,
        _file_name,
        station_name,
        address,
        {{ parse_us_mixed_timestamp('start_date_time') }} as start_local,
        {{ parse_us_mixed_timestamp('end_date_time') }} as end_local,
        -- precision of the published timestamps: ISO rows carry seconds, M/D/YYYY H:MM rows do not
        case
            when
                regexp_matches(start_date_time, '^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$')
                and regexp_matches(end_date_time, '^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$')
                then 1
            else 60
        end as timestamp_precision_seconds,
        {{ hms_to_minutes('total_duration_hh_mm_ss') }} as connected_minutes_reported,
        {{ hms_to_minutes('charging_time_hh_mm_ss') }} as charging_minutes,
        try_cast(energy_kwh as double) as energy_kwh,
        try_cast(objectid as integer) as delivery_row_id,
        try_cast(objectid2 as integer) as file_row_id,
        (
            station_name is null and start_date_time is null and end_date_time is null
            and energy_kwh is null and objectid2 is null
        ) as is_blank_row
    from src
),

-- the per-delivery row id restarts at 0 at every concatenated delivery (ADR-0005 b)
blocks as (
    select
        *,
        sum(case when delivery_row_id = 0 then 1 else 0 end)
            over (order by file_row_id rows unbounded preceding)
        - 1 as delivery_block
    from typed
),

converted as (
    select
        *,
        {{ local_to_utc('start_local', zone) }} as start_utc,
        {{ local_to_utc('end_local', zone) }} as end_utc,
        {{ is_nonexistent_local('start_local', zone) }} as is_nonexistent_start,
        {{ is_nonexistent_local('end_local', zone) }} as is_nonexistent_end,
        {{ is_ambiguous_local('start_local', zone) }} as is_dst_ambiguous,
        false as is_end_sentinel,
        true as has_end
    from blocks
),

measured as (
    select
        *,
        {{ minutes_between('start_utc', 'end_utc') }} as connected_minutes,
        {{ minutes_between('start_utc', 'end_utc') }} - connected_minutes_reported
            as duration_disagreement_minutes,
        case when charging_minutes > 0 then energy_kwh / (charging_minutes / 60.0) end as implied_kw,
        false as publisher_excluded_rule,
        'boulder' as station_key_prefix
    from converted
),

keyed as (
    select
        *,
        {{ natural_key_hash([
            'station_name',
            "date_trunc('minute', start_local)",
            "date_trunc('minute', end_local)",
            'energy_kwh'
        ]) }} as natural_key_hash
    from measured
),

ranked as (
    select
        *,
        row_number() over (
            partition by _row_hash
            order by delivery_block desc, file_row_id desc, _row_hash asc
        ) as exact_dup_rank,
        row_number() over (
            partition by natural_key_hash
            order by delivery_block desc, file_row_id desc, _row_hash asc
        ) as natural_key_rank
    from keyed
)

select
    'boulder' as source,
    'boulder' as source_family,
    cast(null as varchar) as source_session_id,
    _file_name as source_file,
    delivery_block as source_delivery_block,
    'boulder/' || station_name as station_key,
    station_name as station_name_raw,
    address as site_key,
    cast(null as varchar) as port_id,
    false as port_id_present,
    start_utc,
    end_utc,
    start_local,
    end_local,
    '{{ zone }}' as start_tz,
    is_dst_ambiguous,
    energy_kwh,
    charging_minutes,
    connected_minutes,
    connected_minutes_reported,
    duration_disagreement_minutes,
    greatest(connected_minutes - charging_minutes, 0) as idle_minutes,
    'both' as duration_availability,
    publisher_excluded_rule,
    implied_kw,
    timestamp_precision_seconds,
    natural_key_hash,
    {{ quality_flags_list(flags) }} as quality_flags,
    {{ quarantine_reasons_list(reasons) }} as quarantine_reasons,
    {{ quarantine_primary_reason(reasons) }} as primary_reason,
    _row_hash
from ranked
