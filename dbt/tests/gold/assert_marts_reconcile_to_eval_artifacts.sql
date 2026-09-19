-- The claim-discipline rule in dbt: for every committed evaluation artifact, the n-weighted
-- aggregate of fct_period_eval over the artifact's window (its season, model version and the
-- candidate it evaluated per cohort) must match the published n, MAE and both tolerance bands to
-- 1e-4 (the artifacts are rounded to 4 dp). Any row returned is a disagreement and fails the build.
{% set tol = 0.0001 %}

with published as (
    select
        eval_id,
        kind || ':' || season as eval_window,
        model_version,
        cohort,
        candidate,
        n,
        mae,
        within_band1_rate,
        within_band2_rate
    from {{ ref('slv_eval_metrics') }}
),

by_cohort as (
    select
        p.eval_id,
        p.cohort,
        sum(w.n) as n,
        sum(w.mae * w.n) / sum(w.n) as mae,
        sum(w.within_band1_rate * w.n) / sum(w.n) as within_band1_rate,
        sum(w.within_band2_rate * w.n) / sum(w.n) as within_band2_rate
    from published as p
    inner join {{ ref('fct_period_eval') }} as w
        on
            p.eval_window = w.eval_window
            and p.model_version = w.model_version
            and p.cohort = w.cohort
            and p.candidate = w.candidate
    where p.cohort <> 'ALL'
    group by 1, 2
),

overall as (
    select
        eval_id,
        'ALL' as cohort,
        sum(n) as n,
        sum(mae * n) / sum(n) as mae,
        sum(within_band1_rate * n) / sum(n) as within_band1_rate,
        sum(within_band2_rate * n) / sum(n) as within_band2_rate
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
    p.mae as published_mae,
    c.mae as computed_mae,
    p.within_band1_rate as published_band1,
    c.within_band1_rate as computed_band1
from published as p
left join computed as c on p.eval_id = c.eval_id and p.cohort = c.cohort
where
    c.n is null
    or p.n <> c.n
    or abs(p.mae - c.mae) > {{ tol }}
    or abs(p.within_band1_rate - c.within_band1_rate) > {{ tol }}
    or abs(p.within_band2_rate - c.within_band2_rate) > {{ tol }}
