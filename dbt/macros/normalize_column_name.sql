{#- Bronze column-name normalisation, the only transformation bronze applies: lower snake_case,
    non-alphanumerics collapsed to one underscore, no leading / trailing underscore, and a
    leading digit prefixed with `c_`. Applied in Jinja at compile time to the landed columns. -#}
{% macro normalize_column_name(name) -%}
    {%- set lowered = name | lower | trim -%}
    {%- set replaced = modules.re.sub('[^a-z0-9]+', '_', lowered) -%}
    {%- set stripped = replaced.strip('_') -%}
    {%- if stripped and stripped[0] in '0123456789' -%}
        {{ 'c_' ~ stripped }}
    {%- else -%}
        {{ stripped }}
    {%- endif -%}
{%- endmacro %}
