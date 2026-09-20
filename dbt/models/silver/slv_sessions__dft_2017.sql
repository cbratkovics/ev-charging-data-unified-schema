-- UK DfT 2017 conformed events: one row per bronze row across the four files. The family is
-- read from the file name; literal NA tokens are nulled here (bronze keeps them); dates are ISO
-- or day-first per value; PluginDuration is minutes in the rapids raw file and hours in the
-- fasts files (contract). Timestamps are wall-clock Europe/London. Rows with a null CPID get
-- the station key unknown/<Name> (ADR-0007). Dedup on the null-safe natural key prefers the
-- raw file over the anomalies file, then _row_hash (ADR-0009).
{{ config(materialized='table') }}

{% set zone = 'Europe/London' %}
{% set kw_ceiling = implied_kw_ceiling('source_family') %}
{% set reasons = session_quarantine_rules(kw_ceiling) %}
{% set flags = session_quality_flags() %}

with src as (
    select * from {{ ref('brz_dft_2017') }}
),

families as (
    select
        *,
        case
            when _file_name like '%local_authority_rapids_raw%' then 'rapids'
            when _file_name like '%local_authority_rapids_incomplete_anomalies%' then 'rapids_anomalies'
            when _file_name like '%public_sector_fasts_raw%' then 'fasts'
            when _file_name like '%public_sector_fasts_incomplete_anomalies%' then 'fasts_anomalies'
        end as source_family
    from src
),

typed as (
    select
        _row_hash,
        _file_name,
        source_family,
        nullif(chargingevent, 'NA') as source_session_id,
        nullif(cpid, 'NA') as cpid,
        nullif(connector, 'NA') as connector,
        nullif(name, 'NA') as name,
        {{ parse_date_plus_time("nullif(startdate, 'NA')", "nullif(starttime, 'NA')") }} as start_local,
        {{ parse_date_plus_time("nullif(enddate, 'NA')", "nullif(endtime, 'NA')") }} as end_local,
        nullif(enddate, 'NA') like '1970-%' or nullif(enddate, 'NA') like '%/1970' as is_end_sentinel,
        case source_family
            when 'rapids' then try_cast(nullif(pluginduration, 'NA') as double)
            when 'fasts' then try_cast(nullif(pluginduration, 'NA') as double) * 60
            when 'fasts_anomalies' then try_cast(nullif(pluginduration, 'NA') as double) * 60
        end as connected_minutes_reported,
        try_cast(nullif(energy, 'NA') as double) as energy_kwh,
        -- published times carry seconds in every family (hh:mm:ss); dates are whole days
        1 as timestamp_precision_seconds,
        (
            nullif(cpid, 'NA') is null and nullif(startdate, 'NA') is null
            and nullif(enddate, 'NA') is null and nullif(energy, 'NA') is null
            and nullif(name, 'NA') is null
        ) as is_blank_row
    from families
),

converted as (
    select
        *,
        {{ local_to_utc('start_local', zone) }} as start_utc,
        {{ local_to_utc('end_local', zone) }} as end_utc,
        {{ is_nonexistent_local('start_local', zone) }} as is_nonexistent_start,
        {{ is_nonexistent_local('end_local', zone) }} as is_nonexistent_end,
        {{ is_ambiguous_local('start_local', zone) }} as is_dst_ambiguous,
        true as has_end
    from typed
),

measured as (
    select
        *,
        {{ minutes_between('start_utc', 'end_utc') }} as connected_minutes,
        {{ minutes_between('start_utc', 'end_utc') }} - connected_minutes_reported
            as duration_disagreement_minutes,
        cast(null as double) as charging_minutes,
        case
            when {{ minutes_between('start_utc', 'end_utc') }} > 0
                then energy_kwh / ({{ minutes_between('start_utc', 'end_utc') }} / 60.0)
        end as implied_kw,
        -- the publisher's exclusion rule, reproduced as a flag (ADR-0007 item 2)
        coalesce(energy_kwh = 0, false)
        or coalesce(
            coalesce(connected_minutes_reported, {{ minutes_between('start_utc', 'end_utc') }}) <= 3,
            false
        ) as publisher_excluded_rule,
        case source_family when 'rapids' then 0 when 'fasts' then 0 else 1 end as family_rank
    from converted
),

keyed as (
    select
        *,
        {{ natural_key_hash([
            'cpid',
            'connector',
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
            partition by _row_hash order by family_rank asc, _row_hash asc
        ) as exact_dup_rank,
        row_number() over (
            partition by natural_key_hash order by family_rank asc, _row_hash asc
        ) as natural_key_rank
    from keyed
)

select
    'dft_2017' as source,
    source_family,
    source_session_id,
    _file_name as source_file,
    cast(null as integer) as source_delivery_block,
    'dft_2017/' || coalesce(cpid, 'unknown/' || coalesce(name, '<null>')) as station_key,
    cpid as station_name_raw,
    name as site_key,
    connector as port_id,
    case when connector is not null then 'port' else 'unit' end as capacity_grain,
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
    'plug_in_only' as duration_availability,
    publisher_excluded_rule,
    implied_kw,
    timestamp_precision_seconds,
    natural_key_hash,
    {{ quality_flags_list(flags) }} as quality_flags,
    {{ quarantine_reasons_list(reasons) }} as quarantine_reasons,
    {{ quarantine_primary_reason(reasons) }} as primary_reason,
    _row_hash
from ranked
