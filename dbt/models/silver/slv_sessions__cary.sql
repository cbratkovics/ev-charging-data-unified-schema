-- Cary, NC conformed sessions: one row per bronze row. Timestamps are true UTC (ADR-0005 c);
-- there is no end time, so connected time is null and never imputed (ADR-0005 e). Dedup on
-- (station name, start second) keeps the larger charging time, then _row_hash (ADR-0009).
{{ config(materialized='table') }}

{% set zone = 'America/New_York' %}
{% set kw_ceiling = implied_kw_ceiling("'cary'") %}
{% set reasons = session_quarantine_rules(kw_ceiling) %}
{% set flags = session_quality_flags() %}

with src as (
    select * from {{ ref('brz_cary') }}
),

typed as (
    select
        _row_hash,
        _file_name,
        station_name,
        address_1,
        try_cast(start_date as timestamptz) as start_utc,
        1 as timestamp_precision_seconds,
        {{ hms_to_minutes('charging_time_hh_mm_ss') }} as charging_minutes,
        try_cast(energy_kwh as double) as energy_kwh,
        (
            station_name is null and start_date is null and charging_time_hh_mm_ss is null
            and energy_kwh is null
        ) as is_blank_row
    from src
),

converted as (
    select
        *,
        timezone('{{ zone }}', start_utc) as start_local,
        cast(null as timestamp) as end_local,
        cast(null as timestamptz) as end_utc,
        false as is_nonexistent_start,
        false as is_nonexistent_end,
        false as is_dst_ambiguous,
        false as is_end_sentinel,
        false as has_end
    from typed
),

measured as (
    select
        *,
        cast(null as double) as connected_minutes,
        cast(null as double) as connected_minutes_reported,
        cast(null as double) as duration_disagreement_minutes,
        case when charging_minutes > 0 then energy_kwh / (charging_minutes / 60.0) end as implied_kw,
        false as publisher_excluded_rule
    from converted
),

keyed as (
    select
        *,
        {{ natural_key_hash(['station_name', 'start_utc']) }} as natural_key_hash
    from measured
),

ranked as (
    select
        *,
        row_number() over (
            partition by _row_hash order by _row_hash asc
        ) as exact_dup_rank,
        row_number() over (
            partition by natural_key_hash
            order by charging_minutes desc nulls last, _row_hash asc
        ) as natural_key_rank
    from keyed
)

select
    'cary' as source,
    'cary' as source_family,
    cast(null as varchar) as source_session_id,
    _file_name as source_file,
    cast(null as integer) as source_delivery_block,
    'cary/' || station_name as station_key,
    station_name as station_name_raw,
    address_1 as site_key,
    cast(null as varchar) as port_id,
    'unit' as capacity_grain,
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
    cast(null as double) as idle_minutes,
    'charging_only' as duration_availability,
    publisher_excluded_rule,
    implied_kw,
    timestamp_precision_seconds,
    natural_key_hash,
    {{ quality_flags_list(flags) }} as quality_flags,
    {{ quarantine_reasons_list(reasons) }} as quarantine_reasons,
    {{ quarantine_primary_reason(reasons) }} as primary_reason,
    _row_hash
from ranked
