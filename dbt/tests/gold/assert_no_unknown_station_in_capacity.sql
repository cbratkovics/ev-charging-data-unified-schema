-- Unknown-station keys (DfT rows with a null CPID, keyed unknown/<Name>) carry no capacity:
-- they must not appear in dim_station or fct_station_day (ADR-0007 item 1). Their sessions and
-- energy stay in fct_charging_session and are reported separately.
select
    station_key,
    'dim_station' as relation
from {{ ref('dim_station') }}
where contains(station_key, '/unknown/')
union all
select
    station_key,
    'fct_station_day' as relation
from {{ ref('fct_station_day') }}
where contains(station_key, '/unknown/')
