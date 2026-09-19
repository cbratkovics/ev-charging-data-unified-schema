-- Freshness contract (HOLD-grade): the rows must reach the expected complete (season, period) the
-- scheduled job passes as vars. When the vars are unset the test passes.
{% set season = var('expected_season') %}
{% set period = var('expected_period') %}

with latest as (
    select max(period_key) as latest_period_key from {{ ref('slv_period_rows') }}
)

select
    latest_period_key,
{% if season is none or period is none %}
cast(null as integer) as expected_period_key
from latest
where false
{% else %}
    {{ period_key(season, period) }} as expected_period_key
from latest
where latest_period_key is null or latest_period_key < {{ period_key(season, period) }}
    {% endif %}
