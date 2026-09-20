-- The unified session contract (docs/BRIEF.md § 5a): every source's accepted rows, one row
-- per session. is_non_trivial is the one rule gold and the findings use (ADR-0007 item 3).
{{ config(materialized='table') }}

{% set sources = ['boulder', 'cary', 'dft_2017'] %}

with unioned as (
    {% for s in sources %}
    select * from {{ ref('slv_sessions__' ~ s) }}
    where primary_reason is null
    {{ 'union all' if not loop.last }}
    {% endfor %}
)

select
    md5(source || '|' || natural_key_hash) as session_sk,
    source,
    source_family,
    source_session_id,
    source_file,
    source_delivery_block,
    station_key,
    station_name_raw,
    site_key,
    port_id,
    capacity_grain,
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
    coalesce(energy_kwh > 0, false)
    and coalesce(coalesce(connected_minutes, charging_minutes) > 3, false) as is_non_trivial,
    quality_flags,
    natural_key_hash,
    _row_hash
from unioned
