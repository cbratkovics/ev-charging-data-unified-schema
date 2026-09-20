-- Every station-day row carries the grain of its station, and a source never mixes grains
-- (ADR-0005 d): figures at different capacity grains are never summed together.
with mismatch as (
    select f.station_key
    from {{ ref('fct_station_day') }} as f
    inner join {{ ref('dim_station') }} as d on f.station_key = d.station_key
    where f.capacity_grain <> d.capacity_grain
),

mixed as (
    select source
    from {{ ref('fct_station_day') }}
    group by source
    having count(distinct capacity_grain) > 1
)

select
    station_key as offender,
    'row grain differs from station grain' as problem
from mismatch
union all
select
    source as offender,
    'source mixes capacity grains' as problem
from mixed
