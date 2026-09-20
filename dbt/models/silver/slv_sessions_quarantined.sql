-- Every rejected bronze row with all of its failing reasons and one primary reason by the fixed
-- precedence (ADR-0009 item 4), so counts by primary_reason sum to the quarantined total.
{{ config(materialized='table') }}

{% set sources = ['boulder', 'cary', 'dft_2017'] %}

with unioned as (
    {% for s in sources %}
    select * from {{ ref('slv_sessions__' ~ s) }}
    where primary_reason is not null
    {{ 'union all' if not loop.last }}
    {% endfor %}
)

select
    source,
    source_family,
    source_file,
    station_key,
    start_local,
    end_local,
    energy_kwh,
    charging_minutes,
    connected_minutes,
    implied_kw,
    natural_key_hash,
    primary_reason,
    quarantine_reasons,
    quality_flags,
    _row_hash
from unioned
