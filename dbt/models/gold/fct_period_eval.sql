-- Grain: one row per (eval_window, day, day, model_version, candidate, cohort),
-- cohort = 'ALL' or a channel. Metrics computed in SQL from fct_entity_period over rows
-- with a realised actual; definitions match the evaluation artifacts.
with rows_with_actual as (
    select * from {{ ref('fct_entity_period') }}
    where actual is not null
),

cohorts as (
    select
        'ALL' as cohort,
        *
    from rows_with_actual
    union all
    select
        channel as cohort,
        *
    from rows_with_actual
)

select
    cast(eval_window as varchar) as eval_window,
    cast(day as integer) as day,
    cast(day as integer) as day,
    cast(period_key as integer) as period_key,
    cast(model_version as varchar) as model_version,
    cast(candidate as varchar) as candidate,
    cast(cohort as varchar) as cohort,
    cast(count(*) as integer) as n,
    cast(avg(abs_error) as double) as mae,
    cast(median(abs_error) as double) as median_ae,
    cast(sqrt(avg(abs_error * abs_error)) as double) as rmse,
    cast(avg(case when within_band1 then 1.0 else 0.0 end) as double) as within_band1_rate,
    cast(avg(case when within_band2 then 1.0 else 0.0 end) as double) as within_band2_rate,
    cast(avg(case when interval_hit then 1.0 else 0.0 end) as double) as interval_coverage,
    cast(avg(baseline_abs_error) as double) as baseline_mae,
    cast(avg(case when baseline_within_band1 then 1.0 else 0.0 end) as double) as baseline_within_band1_rate,
    cast(avg(abs_error) - avg(baseline_abs_error) as double) as mae_minus_baseline
from cohorts
group by 1, 2, 3, 4, 5, 6, 7
