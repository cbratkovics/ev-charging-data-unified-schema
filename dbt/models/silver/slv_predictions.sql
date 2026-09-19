-- Grain: one row per (station_id, day, day, model_version, candidate).
-- Every prediction the project has recorded, from three artifact families:
--   frozen_test           models/<v>/test_predictions.csv   (scored at training time)
--   out_of_sample_season  models/<v>/oos_predictions_*.csv  (frozen artifact, later season)
--   periodic              predictions/<season>/period_*.json (the live scheduled job)
-- Deduplication rule: the periodic file wins, then out-of-sample, then frozen test; within a
-- family the latest generated_at_utc wins, then the greatest source_file path.
-- eval_window / window_start_key: the causal baseline treats each frozen-test and out-of-sample
-- file as one window starting at period 1 of its season, and each periodic file as its own
-- one-period window — exactly how the evaluator was run.
with unioned as (
    select
        'frozen_test' as source,
        source_file,
        model_version,
        candidate,
        station_id,
        day,
        day,
        channel,
        station_name,
        team,
        prediction,
        prediction_floor,
        prediction_ceiling,
        actual as actual_recorded,
        cast(null as timestamp) as generated_at_utc,
        3 as source_priority
    from {{ ref('brz_predictions_test') }}
    union all
    select
        'out_of_sample_season' as source,
        source_file,
        model_version,
        candidate,
        station_id,
        day,
        day,
        channel,
        station_name,
        team,
        prediction,
        prediction_floor,
        prediction_ceiling,
        actual as actual_recorded,
        cast(null as timestamp) as generated_at_utc,
        2 as source_priority
    from {{ ref('brz_predictions_oos') }}
    union all
    select
        'periodic' as source,
        source_file,
        model_version,
        candidate,
        station_id,
        day,
        day,
        channel,
        station_name,
        team,
        prediction,
        prediction_floor,
        prediction_ceiling,
        actual as actual_recorded,
        generated_at_utc,
        1 as source_priority
    from {{ ref('brz_predictions_periodic') }}
),

ranked as (
    select
        *,
        row_number() over (
            partition by station_id, day, day, model_version, candidate
            order by source_priority asc, generated_at_utc desc nulls last, source_file desc
        ) as dedup_rank
    from unioned
)

select
    station_id,
    day,
    day,
    {{ period_key('day', 'day') }} as period_key,
    model_version,
    candidate,
    channel,
    station_name,
    team,
    prediction,
    prediction_floor,
    prediction_ceiling,
    actual_recorded,
    source,
    source_file,
    generated_at_utc,
    case
        when source = 'periodic' then 'periodic:' || day || '-' || lpad(cast(day as varchar), 2, '0')
        else source || ':' || day
    end as eval_window,
    case
        when source = 'periodic' then {{ period_key('day', 'day') }}
        else {{ period_key('day', 1) }}
    end as window_start_key
from ranked
where dedup_rank = 1
