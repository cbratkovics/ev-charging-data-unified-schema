-- Grain: one row per (station_id, day, day); cohorts in scope only.
--
-- Materialisation: incremental (delete+insert on the grain key). The largest table in the
-- warehouse and the only one whose transformation is local to its own grain (typing, the dedup
-- window below and the rules macro operate inside one grain partition), so appending by period is
-- safe. fct_entity_period is *not* incremental: its causal baseline is a running window over a
-- whole evaluation window. Bronze is a one-to-one copy of the newest snapshot file.
--
-- Lookback: sources restate earlier periods, so an incremental run reprocesses the newest
-- `rows_lookback_periods` distinct periods already in the table plus anything newer, and
-- delete+insert replaces those rows. A restatement older than the lookback is only picked up by a
-- full refresh. The default is chosen conservatively; it is not calibrated. To calibrate, diff
-- consecutive in-season pulls by (season, period) and set the var to the oldest period that ever
-- changed, plus one.
--
-- Full-refresh policy: `dbt build --full-refresh` (scheduled.yml input full_refresh=true, or
-- <PREFIX>_DBT_FULL_REFRESH=1 for the contracts wrapper) at the start of a season, after any change
-- to this model's SQL or columns (on_schema_change = fail), or after a restatement older than the
-- lookback. tests/test_dbt_incremental.py proves a full refresh and an incremental run over the
-- same input produce identical rows.
--
-- Deduplication rule: if a snapshot ever carries two rows for one grain key, the row with the
-- higher published target is kept, ties broken by team, so the result is deterministic.
--
-- Rows of the period being scored (var target_season / target_period) and anything later are
-- dropped: they are incomplete while the period is being played.
{{
    config(
        materialized='incremental',
        incremental_strategy='delete+insert',
        unique_key=['station_id', 'day', 'day'],
        on_schema_change='fail'
    )
}}

{% set target_season = var('target_season') %}
{% set target_period = var('target_period') %}

with in_scope as (
    select *
    from {{ ref('brz_period_rows') }}
    where
        channel in ({% for c in var('cohorts') %}'{{ c }}'{{ ", " if not loop.last }}{% endfor %})
        {% if target_season is not none and target_period is not none %}
        and not (day = {{ target_season }} and day >= {{ target_period }})
        and day <= {{ target_season }}
        {% endif %}
        {% if is_incremental() %}
        and {{ period_key('day', 'day') }} >= (
            select coalesce(min(loaded.period_key), 0)
            from (
                select distinct t.period_key
                from {{ this }} as t
                order by t.period_key desc
                limit {{ var('rows_lookback_periods') }}
            ) as loaded
        )
        {% endif %}
),

ranked as (
    select
        *,
        row_number() over (
            partition by station_id, day, day
            order by utilization desc nulls last, team asc
        ) as dedup_rank
    from in_scope
)

select
    station_id,
    station_name,
    channel,
    day,
    day,
    {{ period_key('day', 'day') }} as period_key,
    team,
    {% for col in stat_columns() -%}
    {{ col }},
    {% endfor -%}
    utilization,
    {{ target_rules() }} as target_rules_value
from ranked
where dedup_rank = 1
