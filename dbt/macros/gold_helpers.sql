{#- Minutes in a station-local calendar date: the UTC instants of local midnight and the next
    local midnight, so DST transition days are 1,380 or 1,500 minutes (ADR-0010 e). -#}
{% macro local_day_minutes(local_date, zone) -%}
    (
        epoch(timezone({{ zone }}, cast(({{ local_date }} + interval 1 day) as timestamp)))
        - epoch(timezone({{ zone }}, cast({{ local_date }} as timestamp)))
    ) / 60.0
{%- endmacro %}

{#- Utilization at any rollup: the ratio of summed numerator to summed denominator, never an
    average of daily ratios (docs/BRIEF.md § 5). Null-safe: sum ignores nulls and a zero
    denominator yields null; callers expose the contributing-row counts next to it. -#}
{% macro utilization_ratio(numerator, denominator) -%}
    sum({{ numerator }}) / nullif(sum({{ denominator }}), 0)
{%- endmacro %}

{#- Minutes of overlap between [a_start, a_end) and [b_start, b_end) as timestamptz; null when
    any bound is null. -#}
{% macro overlap_minutes(a_start, a_end, b_start, b_end) -%}
    greatest(
        (epoch(least({{ a_end }}, {{ b_end }})) - epoch(greatest({{ a_start }}, {{ b_start }}))) / 60.0,
        0
    )
{%- endmacro %}
