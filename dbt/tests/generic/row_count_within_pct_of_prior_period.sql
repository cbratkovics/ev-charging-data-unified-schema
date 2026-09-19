{#- Contract: the newest period's row count is within `tolerance_pct` of the period before it.
    Passes trivially when fewer than two periods exist. -#}
{% test row_count_within_pct_of_prior_period(model, period_columns, tolerance_pct=0.35) %}

{%- set cols = period_columns | join(', ') -%}

with per_period as (
    select
        {{ cols }},
        count(*) as row_count
    from {{ model }}
    group by {{ cols }}
),

ordered as (
    select
        {{ cols }},
        row_count,
        lag(row_count) over (order by {{ cols }}) as prior_row_count,
        row_number() over (order by {{ cols }} desc) as recency
    from per_period
)

select
    {{ cols }},
    row_count,
    prior_row_count,
    abs(row_count - prior_row_count) * 1.0 / prior_row_count as change_pct,
    {{ tolerance_pct }} as tolerance_pct
from ordered
where
    recency = 1
    and prior_row_count is not null
    and abs(row_count - prior_row_count) * 1.0 / prior_row_count > {{ tolerance_pct }}

{% endtest %}
