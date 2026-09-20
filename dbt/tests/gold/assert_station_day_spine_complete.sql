-- Every station has exactly one fct_station_day row per date of its active window, and every
-- active, non-excluded date carries available minutes (ADR-0011 item 4).
with expected as (
    select
        station_key,
        window_days,
        window_days - excluded_days as available_days
    from {{ ref('dim_station') }}
),

actual as (
    select
        station_key,
        count(*) as rows_,
        count(distinct local_date) as dates_,
        count(*) filter (where not is_excluded_day) as available_rows,
        count(*) filter (where not is_excluded_day and available_port_minutes <= 0) as available_rows_without_minutes
    from {{ ref('fct_station_day') }}
    group by station_key
)

select
    e.station_key,
    e.window_days,
    e.available_days,
    a.rows_,
    a.dates_,
    a.available_rows,
    a.available_rows_without_minutes
from expected as e
left join actual as a on e.station_key = a.station_key
where
    a.rows_ is null
    or a.rows_ <> e.window_days
    or a.dates_ <> e.window_days
    or a.available_rows <> e.available_days
    or a.available_rows_without_minutes > 0
