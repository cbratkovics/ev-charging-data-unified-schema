{#- SCD2 history of the inferred station attributes. `check` strategy on the attributes that a
    rebuild can change, with updated_at driven by data_as_of_utc (the latest retrieval time of
    the station's source files) instead of the wall clock, so two builds of the same landed
    files produce a byte-identical snapshot (ADR-0011 item 6). A code change that alters an
    attribute without a new retrieval still produces a new version, stamped with the same
    data_as_of_utc as the one it supersedes. -#}
{% snapshot snp_station %}

{{
    config(
        schema='snapshots',
        unique_key='station_key',
        strategy='check',
        check_cols=['ports_inferred', 'ports_source', 'active_from', 'active_to', 'excluded_days', 'low_evidence', 'capacity_grain', 'site_key'],
        updated_at='data_as_of_utc',
        hard_deletes='ignore'
    )
}}

select
    station_key,
    source,
    site_key,
    capacity_grain,
    ports_inferred,
    ports_source,
    active_from,
    active_to,
    excluded_days,
    low_evidence,
    data_as_of_utc
from {{ ref('dim_station') }}

{% endsnapshot %}
