-- Claim discipline for the v2 decisions mart: recommendation_within_band1_rate is the same
-- tolerance-band metric the artifacts publish. At min_floor = 0 every entity is recommended
-- (floors are clipped at 0), so the outcome-weighted aggregate of v2 at that threshold over each
-- artifact's window, model version and per-cohort candidate must equal the published n and
-- within_band1_rate to 1e-4. The API may not move to v2 while this test is absent or failing.
{% set tol = 0.0001 %}

with published as (
    select
        eval_id,
        kind || ':' || season as eval_window,
        model_version,
        cohort,
        candidate,
        n,
        within_band1_rate
    from {{ ref('slv_eval_metrics') }}
),

windows as (
    select distinct
        eval_window,
        day,
        day,
        model_version,
        candidate
    from {{ ref('fct_period_eval') }}
),

inclusive as (
    select
        d.day,
        d.day,
        d.channel,
        d.model_version,
        d.candidate,
        d.recommendations_with_outcome,
        d.recommendation_within_band1_rate,
        w.eval_window
    from {{ ref('fct_decision_policy', v=2) }} as d
    inner join windows as w
        on
            d.day = w.day
            and d.day = w.day
            and d.model_version = w.model_version
            and d.candidate = w.candidate
    where d.min_floor = 0
),

by_cohort as (
    select
        p.eval_id,
        p.cohort,
        sum(i.recommendations_with_outcome) as n,
        sum(i.recommendation_within_band1_rate * i.recommendations_with_outcome)
        / sum(i.recommendations_with_outcome) as within_band1_rate
    from published as p
    inner join inclusive as i
        on
            p.eval_window = i.eval_window
            and p.model_version = i.model_version
            and p.cohort = i.channel
            and p.candidate = i.candidate
    where p.cohort <> 'ALL'
    group by 1, 2
),

overall as (
    select
        eval_id,
        'ALL' as cohort,
        sum(n) as n,
        sum(within_band1_rate * n) / sum(n) as within_band1_rate
    from by_cohort
    group by 1
),

computed as (
    select * from by_cohort
    union all
    select * from overall
)

select
    p.eval_id,
    p.cohort,
    p.n as published_n,
    c.n as computed_n,
    p.within_band1_rate as published_band1,
    c.within_band1_rate as computed_band1
from published as p
left join computed as c on p.eval_id = c.eval_id and p.cohort = c.cohort
where
    c.n is null
    or p.n <> c.n
    or abs(p.within_band1_rate - c.within_band1_rate) > {{ tol }}
