-- One row per calendar date spanning every station's active window. Full rebuild.
{{ config(materialized='table') }}

with bounds as (
    select
        min(active_from) as first_date,
        max(active_to) as last_date
    from {{ ref('dim_station') }}
),

spine as (
    select cast(unnest(generate_series(cast(first_date as date), cast(last_date as date), interval 1 day)) as date) as date_key
    from bounds
)

select
    date_key,
    cast(year(date_key) as integer) as year,
    cast(month(date_key) as integer) as month,
    cast(day(date_key) as integer) as day_of_month,
    cast(isodow(date_key) as integer) as iso_day_of_week,
    isodow(date_key) >= 6 as is_weekend,
    cast(strftime(date_key, '%Y-%m') as varchar) as year_month
from spine
