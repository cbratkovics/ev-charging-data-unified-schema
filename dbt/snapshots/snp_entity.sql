{#- SCD Type 2 history of the entity dimension: `check` strategy on the attributes that change
    (cohort, team, display name). as_of_period_key is the warehouse's data-through period at the
    capture, so as-of resolution works in period terms. History starts at the first prod run. -#}
{% snapshot snp_entity %}

{{
    config(
        schema='snapshots',
        unique_key='station_id',
        strategy='check',
        check_cols=['station_name', 'channel', 'team'],
        hard_deletes='ignore'
    )
}}

select
    d.station_id,
    d.station_name,
    d.channel,
    d.team,
    (select max(s.period_key) from {{ ref('slv_period_rows') }} as s) as as_of_period_key
from {{ ref('dim_entity') }} as d

{% endsnapshot %}
