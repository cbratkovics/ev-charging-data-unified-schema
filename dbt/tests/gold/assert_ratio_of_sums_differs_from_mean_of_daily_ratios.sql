-- Utilization must be a ratio of sums, never an average of daily percentages (docs/BRIEF.md
-- § 5). This test shows the two differ on this data: per source, connected-time utilization
-- as sum(connected) / sum(available) versus the mean of the daily ratios. It fails when they
-- agree to 1e-9 for a source with at least two active days, which would mean the distinction
-- is moot on this data and the docs claiming otherwise would be wrong.
with daily as (
    select
        source,
        connected_minutes,
        available_port_minutes,
        connected_minutes / available_port_minutes as daily_ratio
    from {{ ref('fct_station_day') }}
    where not is_excluded_day and available_port_minutes > 0 and connected_minutes is not null
),

per_source as (
    select
        source,
        count(*) as station_days,
        {{ utilization_ratio('connected_minutes', 'available_port_minutes') }} as ratio_of_sums,
        avg(daily_ratio) as mean_of_daily_ratios
    from daily
    group by source
)

select *
from per_source
where station_days >= 2 and abs(ratio_of_sums - mean_of_daily_ratios) < 1e-9
