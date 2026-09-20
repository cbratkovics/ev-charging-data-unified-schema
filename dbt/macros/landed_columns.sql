{#- The columns of a landed source, in a fixed order, read from the parquet files at run time.
    Bronze models select each landed column under its normalised name so the model's columns are
    exactly the union of the source's file headers (union_by_name) plus the landing metadata.
    At parse time (no execute) an empty list is returned; the model then compiles to `select *`,
    which is enough for `dbt parse` and for docs generation on a built warehouse. -#}
{% macro landed_columns(source_name, table_name) %}
    {% if not execute %}
        {{ return([]) }}
    {% endif %}
    {% set sql %}
        select column_name
        from (describe select * from {{ source(source_name, table_name) }})
    {% endset %}
    {% set result = run_query(sql) %}
    {{ return(result.columns[0].values() | list) }}
{% endmacro %}

{#- One bronze model body: every landed column, normalised names, metadata last. -#}
{% macro bronze_select(source_name, table_name) %}
    {%- set cols = landed_columns(source_name, table_name) -%}
    {%- if cols | length == 0 -%}
select * from {{ source(source_name, table_name) }}
    {%- else -%}
select
    {%- for col in cols if not col.startswith('_') %}
    "{{ col }}" as {{ normalize_column_name(col) }},
    {%- endfor %}
    _source,
    _file_name,
    _retrieved_at,
    _row_hash
from {{ source(source_name, table_name) }}
    {%- endif -%}
{% endmacro %}
