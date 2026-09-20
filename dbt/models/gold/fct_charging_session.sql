-- One row per accepted session (docs/BRIEF.md § 5). Incremental by source-level replace
-- (ADR-0011 items 1 and 2): every row carries the sha256 of the landed file it came from; when
-- any of a source's files is new, changed or gone since the last build, all of that source's
-- rows are deleted and reinserted from silver. There is no event-time lookback. A source whose
-- files all vanish keeps its old rows until a full refresh (delete+insert only deletes the
-- keys it reinserts); the reconciliation artifact would show the mismatch.
{{
    config(
        materialized='incremental',
        incremental_strategy='delete+insert',
        unique_key='source',
        on_schema_change='fail'
    )
}}

with files as (
    select
        source,
        file_name,
        sha256
    from {{ ref('meta_landed_files') }}
),

{% if is_incremental() %}
loaded as (
    select distinct
        source,
        source_file,
        source_file_sha256
    from {{ this }}
),

changed as (
    select f.source
    from files as f
    where
        not exists (
            select 1
            from loaded as l
            where
                l.source = f.source
                and l.source_file = f.file_name
                and l.source_file_sha256 = f.sha256
        )
    union
    select l.source
    from loaded as l
    where not exists (
        select 1
        from files as f
        where
            f.source = l.source
            and f.file_name = l.source_file
            and f.sha256 = l.source_file_sha256
    )
),
{% endif %}

sessions as (
    select
        s.*,
        f.sha256 as source_file_sha256
    from {{ ref('slv_sessions_unioned') }} as s
    left join files as f
        on s.source = f.source and s.source_file = f.file_name
    {% if is_incremental() %}
    where s.source in (select changed.source from changed)
    {% endif %}
)

select
    session_sk,
    source,
    source_family,
    source_session_id,
    source_file,
    source_file_sha256,
    cast(source_delivery_block as integer) as source_delivery_block,
    case when source = 'dft_2017' then 'dft_2017/' || coalesce(site_key, '<null>') else source end
        as operator_key,
    station_key,
    station_name_raw,
    site_key,
    port_id,
    port_id_present,
    start_utc,
    end_utc,
    start_local,
    end_local,
    start_tz,
    is_dst_ambiguous,
    energy_kwh,
    charging_minutes,
    connected_minutes,
    connected_minutes_reported,
    duration_disagreement_minutes,
    idle_minutes,
    duration_availability,
    publisher_excluded_rule,
    implied_kw,
    timestamp_precision_seconds,
    is_non_trivial,
    list_aggregate(quality_flags, 'string_agg', ',') as quality_flags,
    natural_key_hash,
    _row_hash
from sessions
