-- One row per operator: the three publishers, plus one row per DfT funding body (the
-- organisation that received the grant and operates the chargepoints) with the publisher as
-- parent. Sessions carry operator_key. Full rebuild.
{{ config(materialized='table') }}

with bodies as (
    select distinct
        operator_key,
        source,
        site_key
    from {{ ref('fct_charging_session') }}
    where source = 'dft_2017'
)

select
    'boulder' as operator_key,
    'City of Boulder, CO' as operator_name,
    'boulder' as source,
    cast(null as varchar) as parent_operator_key,
    'US' as country,
    'America/Denver' as timezone
union all
select
    'cary' as operator_key,
    'Town of Cary, NC' as operator_name,
    'cary' as source,
    cast(null as varchar) as parent_operator_key,
    'US' as country,
    'America/New_York' as timezone
union all
select
    'dft_2017' as operator_key,
    'UK Department for Transport (publisher of the 2017 chargepoint analysis)' as operator_name,
    'dft_2017' as source,
    cast(null as varchar) as parent_operator_key,
    'GB' as country,
    'Europe/London' as timezone
union all
select
    operator_key,
    coalesce(site_key, '<null>') as operator_name,
    source,
    'dft_2017' as parent_operator_key,
    'GB' as country,
    'Europe/London' as timezone
from bodies
