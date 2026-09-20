{#- Silver helpers. Every expression is pure SQL over string columns so it can be unit-tested
    with dbt unit tests and reasoned about from the model SQL alone. -#}

{#- H:MM:SS (hours unbounded) -> minutes as double; null when the shape does not match. -#}
{% macro hms_to_minutes(col) -%}
    case
        when regexp_matches({{ col }}, '^\d+:\d{2}:\d{2}$')
            then cast(split_part({{ col }}, ':', 1) as double) * 60
                + cast(split_part({{ col }}, ':', 2) as double)
                + cast(split_part({{ col }}, ':', 3) as double) / 60
    end
{%- endmacro %}

{#- Boulder's mixed column: M/D/YYYY H:MM or ISO YYYY-MM-DD HH:MM:SS -> naive timestamp. -#}
{% macro parse_us_mixed_timestamp(col) -%}
    case
        when regexp_matches({{ col }}, '^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$')
            then try_strptime({{ col }}, '%Y-%m-%d %H:%M:%S')
        when regexp_matches({{ col }}, '^\d{1,2}/\d{1,2}/\d{4} \d{1,2}:\d{2}$')
            then try_strptime({{ col }}, '%m/%d/%Y %H:%M')
    end
{%- endmacro %}

{#- DfT: a date column (ISO or day-first) plus a time column -> naive timestamp. -#}
{% macro parse_date_plus_time(date_col, time_col) -%}
    case
        when regexp_matches({{ date_col }}, '^\d{4}-\d{2}-\d{2}$')
            and regexp_matches({{ time_col }}, '^\d{1,2}:\d{2}:\d{2}$')
            then try_strptime({{ date_col }} || ' ' || {{ time_col }}, '%Y-%m-%d %H:%M:%S')
        when regexp_matches({{ date_col }}, '^\d{1,2}/\d{1,2}/\d{4}$')
            and regexp_matches({{ time_col }}, '^\d{1,2}:\d{2}:\d{2}$')
            then try_strptime({{ date_col }} || ' ' || {{ time_col }}, '%d/%m/%Y %H:%M:%S')
    end
{%- endmacro %}

{#- Wall-clock local naive timestamp -> UTC instant (timestamptz). DuckDB / ICU resolves an
    ambiguous fall-back time to the second occurrence and shifts a nonexistent spring-forward
    time forward one hour (ADR-0009). -#}
{% macro local_to_utc(ts, zone) -%}
    timezone('{{ zone }}', {{ ts }})
{%- endmacro %}

{#- True when the naive local timestamp does not exist in the zone (spring-forward gap):
    the round trip through UTC lands on a different wall-clock time. -#}
{% macro is_nonexistent_local(ts, zone) -%}
    ({{ ts }} is not null and timezone('{{ zone }}', timezone('{{ zone }}', {{ ts }})) <> {{ ts }})
{%- endmacro %}

{#- True when the naive local timestamp is ambiguous (fall-back hour). Under second-occurrence
    resolution the hour before it maps two hours earlier in UTC (ADR-0009). -#}
{% macro is_ambiguous_local(ts, zone) -%}
    (
        {{ ts }} is not null
        and timezone('{{ zone }}', timezone('{{ zone }}', {{ ts }})) = {{ ts }}
        and timezone('{{ zone }}', {{ ts }}) - timezone('{{ zone }}', {{ ts }} - interval 1 hour)
        = interval 2 hour
    )
{%- endmacro %}

{#- Minutes between two timestamptz instants. -#}
{% macro minutes_between(start_utc, end_utc) -%}
    (epoch({{ end_utc }}) - epoch({{ start_utc }})) / 60.0
{%- endmacro %}

{#- Null-safe natural-key hash: every key column coalesced to a sentinel before hashing, so
    null equals null (ADR-0009 item 6). -#}
{% macro natural_key_hash(cols) -%}
    md5(
        {%- for c in cols %}
        coalesce(cast({{ c }} as varchar), '<null>'){{ " || '\x1f' ||" if not loop.last }}
        {%- endfor %}
    )
{%- endmacro %}

{#- The fixed quarantine precedence (ADR-0009 item 4). `reasons` is a list of
    [reason_code, boolean_expression] pairs in precedence order; returns the SQL for the
    list of failing reasons and for the primary reason. -#}
{% macro quarantine_reasons_list(reasons) -%}
    list_filter(
        [
            {%- for code, expr in reasons %}
            case when {{ expr }} then '{{ code }}' end{{ "," if not loop.last }}
            {%- endfor %}
        ],
        x -> x is not null
    )
{%- endmacro %}

{% macro quarantine_primary_reason(reasons) -%}
    case
        {%- for code, expr in reasons %}
        when {{ expr }} then '{{ code }}'
        {%- endfor %}
    end
{%- endmacro %}

{#- Quality flags kept on accepted rows, same shape. -#}
{% macro quality_flags_list(flags) -%}
    {{ quarantine_reasons_list(flags) }}
{%- endmacro %}
