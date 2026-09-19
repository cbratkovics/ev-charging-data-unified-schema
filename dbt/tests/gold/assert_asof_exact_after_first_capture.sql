-- dim_entity_asof must resolve every period after the snapshot's first capture exactly from
-- history: for any entity in snp_entity, a prediction period later than the earliest
-- as_of_period_key has a matching version, so is_exact_asof is true.
with first_capture as (
    select min(as_of_period_key) as first_period_key from {{ ref('snp_entity') }}
)

select
    a.station_id,
    a.period_key,
    a.is_exact_asof,
    f.first_period_key
from {{ ref('dim_entity_asof') }} as a
cross join first_capture as f
where
    a.period_key > f.first_period_key
    and not a.is_exact_asof
    and a.station_id in (select s.station_id from {{ ref('snp_entity') }} as s)
