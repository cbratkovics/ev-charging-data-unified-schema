{#- Rules-based target from raw stat columns — the SQL twin of <package>/target.py. STUB: the
    weights match the synthetic loader's rules. When you replace the loader, rewrite this macro
    from the source's documented rules; tests/silver/assert_target_rules_reconcile_to_source.sql
    proves it against the value the source publishes, row for row. -#}
{% macro target_rules(relation_alias=none) -%}
    {%- set p = relation_alias ~ '.' if relation_alias else '' -%}
    (
        0.1 * coalesce({{ p }}stat_a, 0)
        + 0.5 * coalesce({{ p }}stat_b, 0)
        + 1.0 * coalesce({{ p }}stat_c, 0)
    )
{%- endmacro %}

{#- The raw stat columns kept from the source (the loader's STAT_COLUMNS minus the published
    target). One list, used by bronze typing and silver contracts. -#}
{% macro stat_columns() -%}
{{ return(['stat_a', 'stat_b', 'stat_c']) }}
{%- endmacro %}
