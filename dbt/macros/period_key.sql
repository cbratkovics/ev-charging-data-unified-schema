{#- period_key = season * period_key_base + period: monotonic in time, one integer for window
    frames and lookbacks. period is an ordinal 1..N within the season; period_key_base (var,
    mirrored from config) is the next power of ten above N, so the key never collides. -#}
{% macro period_key(season_expr, period_expr) -%}
    ({{ season_expr }} * {{ var('period_key_base') }} + {{ period_expr }})
{%- endmacro %}
