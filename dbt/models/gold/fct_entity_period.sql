-- Grain: one row per (station_id, day, day, model_version, candidate):
-- every recorded prediction next to what happened, the error metrics and the causal baseline.
--
-- actual: the target from slv_period_rows (rules macro); when the row is not in the warehouse the
--   value recorded in the prediction artifact is used and actual_source says so.
-- baseline: the evaluator's causal trailing mean reproduced in SQL (fsum, exact summation): the
--   mean of the entity's realised target over (a) rows strictly before the evaluation window
--   started and (b) evaluated rows of the same window and candidate from strictly earlier periods;
--   cohort fallback under the same rule; falling back to the prediction itself.
{% set band1 = var('within_k')[0] %}
{% set band2 = var('within_k')[1] %}

with predictions as (
    select * from {{ ref('slv_predictions') }}
),

actuals as (
    select
        station_id,
        period_key,
        channel,
        utilization as actual_value
    from {{ ref('slv_period_rows') }}
),

windows as (
    select distinct
        eval_window,
        window_start_key
    from predictions
),

seed_entity as (
    select
        w.eval_window,
        a.station_id,
        fsum(a.actual_value) as seed_sum,
        count(a.actual_value) as seed_cnt
    from windows as w
    inner join actuals as a on w.window_start_key > a.period_key
    group by 1, 2
),

seed_cohort as (
    select
        w.eval_window,
        a.channel,
        fsum(a.actual_value) as seed_sum,
        count(a.actual_value) as seed_cnt
    from windows as w
    inner join actuals as a on w.window_start_key > a.period_key
    group by 1, 2
),

joined as (
    select
        p.*,
        a.actual_value as actual_from_rows,
        coalesce(a.actual_value, p.actual_recorded) as actual
    from predictions as p
    left join actuals as a on p.station_id = a.station_id and p.period_key = a.period_key
),

running as (
    select
        *,
        fsum(actual) over (partition by eval_window, candidate, station_id order by period_key range between unbounded preceding and 1 preceding) as run_entity_sum,
        count(actual) over (partition by eval_window, candidate, station_id order by period_key range between unbounded preceding and 1 preceding) as run_entity_cnt,
        fsum(actual) over (partition by eval_window, candidate, channel order by period_key range between unbounded preceding and 1 preceding) as run_cohort_sum,
        count(actual) over (partition by eval_window, candidate, channel order by period_key range between unbounded preceding and 1 preceding) as run_cohort_cnt
    from joined
),

with_baseline as (
    select
        r.*,
        coalesce(se.seed_sum, 0) + coalesce(r.run_entity_sum, 0) as entity_hist_sum,
        coalesce(se.seed_cnt, 0) + coalesce(r.run_entity_cnt, 0) as entity_hist_cnt,
        coalesce(sc.seed_sum, 0) + coalesce(r.run_cohort_sum, 0) as cohort_hist_sum,
        coalesce(sc.seed_cnt, 0) + coalesce(r.run_cohort_cnt, 0) as cohort_hist_cnt
    from running as r
    left join seed_entity as se on r.eval_window = se.eval_window and r.station_id = se.station_id
    left join seed_cohort as sc on r.eval_window = sc.eval_window and r.channel = sc.channel
),

final as (
    select
        *,
        case
            when entity_hist_cnt > 0 then entity_hist_sum / entity_hist_cnt
            when cohort_hist_cnt > 0 then cohort_hist_sum / cohort_hist_cnt
            else prediction
        end as baseline
    from with_baseline
)

select
    cast(station_id as varchar) as station_id,
    cast(day as integer) as day,
    cast(day as integer) as day,
    cast(period_key as integer) as period_key,
    cast(model_version as varchar) as model_version,
    cast(candidate as varchar) as candidate,
    cast(channel as varchar) as channel,
    cast(source as varchar) as source,
    cast(eval_window as varchar) as eval_window,
    cast(prediction as double) as prediction,
    cast(prediction_floor as double) as prediction_floor,
    cast(prediction_ceiling as double) as prediction_ceiling,
    cast(actual as double) as actual,
    cast(case when actual_from_rows is not null then 'rows' when actual_recorded is not null then 'artifact' end as varchar) as actual_source,
    cast(abs(actual - prediction) as double) as abs_error,
    cast(case when actual is not null then abs(actual - prediction) <= {{ band1 }} end as boolean) as within_band1,
    cast(case when actual is not null then abs(actual - prediction) <= {{ band2 }} end as boolean) as within_band2,
    cast(case when actual is not null then prediction_floor <= actual and actual <= prediction_ceiling end as boolean) as interval_hit,
    cast(baseline as double) as baseline,
    cast(abs(actual - baseline) as double) as baseline_abs_error,
    cast(case when actual is not null then abs(actual - baseline) <= {{ band1 }} end as boolean) as baseline_within_band1
from final
