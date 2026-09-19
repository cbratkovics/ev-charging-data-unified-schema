-- Grain: one row per (day, day, channel, model_version, candidate, min_floor):
-- the floor policy (recommend when prediction_floor >= min_floor, else review) swept over var
-- min_floor_grid, with replacement level = the prediction of the rank-k entity of the cohort that
-- period (k = var replacement_rank). Outcome columns use rows with a realised actual.
-- v1 is what the API serves (relation alias fct_decision_policy); v2 adds interval outcomes.
{% set grid = var('min_floor_grid') %}
{% set replacement_rank = var('replacement_rank') %}

with grid as (
    select unnest([{{ grid | join(', ') }}]) as min_floor
),

scored as (
    select
        *,
        row_number() over (partition by day, day, channel, model_version, candidate order by prediction desc, station_id asc) as prediction_rank,
        max(actual) over (partition by day, day, channel, model_version, candidate) as best_eligible,
        case channel
            {% for c, k in replacement_rank.items() %}
            when '{{ c }}' then {{ k }}
            {% endfor %}
        end as replacement_rank
    from {{ ref('fct_entity_period') }}
),

replacement as (
    select
        day,
        day,
        channel,
        model_version,
        candidate,
        prediction as replacement_level
    from scored
    where prediction_rank = replacement_rank
),

decisions as (
    select
        s.day,
        s.day,
        s.channel,
        s.model_version,
        s.candidate,
        g.min_floor,
        s.prediction,
        s.prediction_floor,
        s.prediction_ceiling,
        s.actual,
        s.best_eligible,
        r.replacement_level,
        case when s.prediction_floor >= g.min_floor then 'recommend' else 'review' end as policy_action
    from scored as s
    cross join grid as g
    left join replacement as r
        on
            s.day = r.day
            and s.day = r.day
            and s.channel = r.channel
            and s.model_version = r.model_version
            and s.candidate = r.candidate
),

metrics as (
    select
        day,
        day,
        channel,
        model_version,
        candidate,
        min_floor,
        count(*) as eligible_decisions,
        count(*) filter (where policy_action = 'recommend') as recommendations,
        count(*) filter (where policy_action = 'review') as reviews,
        count(actual) filter (where policy_action = 'recommend') as recommendations_with_outcome,
        avg(abs(prediction - actual)) filter (where policy_action = 'recommend') as recommendation_mae,
        avg(abs(prediction - actual)) filter (where policy_action = 'review') as review_mae,
        avg(best_eligible - actual) filter (where policy_action = 'recommend') as mean_regret,
        avg(case when actual >= replacement_level then 1.0 else 0.0 end) filter (where policy_action = 'recommend' and actual is not null and replacement_level is not null) as hit_rate,
        avg(case when actual < prediction_floor then 1.0 else 0.0 end) filter (where policy_action = 'recommend' and actual is not null) as downside_rate
    from decisions
    group by 1, 2, 3, 4, 5, 6
)

select
    cast(day as integer) as day,
    cast(day as integer) as day,
    cast({{ period_key('day', 'day') }} as integer) as period_key,
    cast(channel as varchar) as channel,
    cast(model_version as varchar) as model_version,
    cast(candidate as varchar) as candidate,
    cast(min_floor as double) as min_floor,
    cast(eligible_decisions as integer) as eligible_decisions,
    cast(recommendations as integer) as recommendations,
    cast(reviews as integer) as reviews,
    cast(recommendations * 1.0 / nullif(eligible_decisions, 0) as double) as recommendation_rate,
    cast(recommendations_with_outcome as integer) as recommendations_with_outcome,
    cast(recommendation_mae as double) as recommendation_mae,
    cast(review_mae as double) as review_mae,
    cast(mean_regret as double) as mean_regret,
    cast(hit_rate as double) as hit_rate,
    cast(downside_rate as double) as downside_rate
from metrics
