{#- The value rules every silver model applies, in one place (docs/BRIEF.md § 5, ADR-0007,
    ADR-0009). Column names are the conformed silver names. charging_exceeds_connected allows
    2 minutes: connected time is computed from minute-precision timestamps while charging time
    has seconds, so charging can exceed it by up to a minute on a valid row (ADR-0009). -#}

{% macro session_quarantine_rules(kw_ceiling_expr) -%}
    {{ return([
        ['blank_row', 'is_blank_row'],
        ['unparseable_timestamp', 'start_local is null or (has_end and end_local is null and not is_end_sentinel)'],
        ['nonexistent_local_time', 'is_nonexistent_start or is_nonexistent_end'],
        ['exact_duplicate', 'exact_dup_rank > 1'],
        ['natural_key_duplicate', 'natural_key_rank > 1'],
        ['end_sentinel_1970', 'is_end_sentinel'],
        ['end_before_start', 'connected_minutes < 0'],
        ['negative_energy', 'energy_kwh < 0'],
        ['energy_sentinel', 'energy_kwh < -1000'],
        ['charging_exceeds_connected', 'charging_minutes > connected_minutes + 2'],
        ['implied_kw_over_ceiling', 'implied_kw > ' ~ kw_ceiling_expr],
    ]) }}
{%- endmacro %}

{% macro session_quality_flags() -%}
    {{ return([
        ['zero_energy', 'energy_kwh = 0'],
        ['over_24h', 'coalesce(connected_minutes, charging_minutes) > 1440'],
        ['duration_disagrees', 'abs(duration_disagreement_minutes) > 2'],
        ['dst_ambiguous', 'is_dst_ambiguous'],
        ['publisher_excluded_rule', 'publisher_excluded_rule'],
        ['unknown_station', "contains(station_key, '/unknown/')"],
    ]) }}
{%- endmacro %}

{#- Ceilings per source / family (ADR-0007 item 5). -#}
{% macro implied_kw_ceiling(source_family_expr) -%}
    case {{ source_family_expr }}
        when 'boulder' then 20.0
        when 'cary' then 20.0
        when 'rapids' then 55.0
        when 'rapids_anomalies' then 55.0
        when 'fasts' then 30.0
        when 'fasts_anomalies' then 30.0
    end
{%- endmacro %}
