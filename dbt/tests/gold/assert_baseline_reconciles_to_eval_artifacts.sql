-- The SQL causal baseline must reproduce the evaluator's baseline MAE per artifact and cohort to
-- 1e-4, and its within-band-1 rate to within three rows: an error of exactly the band width is
-- decided by floating-point rounding (the evaluator averages exact rationals, DuckDB rounds
-- fsum(x)/n), and DuckDB's parallel summation order is not deterministic (docs/REPRODUCIBILITY.md).
-- Needs the full row history (the seed of every entity's trailing mean); disabled when the
-- warehouse is built from a partial fixture (var full_rows = false).
{{ config(enabled=var('full_rows', true)) }}
{% set tol = 0.0001 %}
{% set max_rows_off = 3 %}

with published as (
    select
        eval_id,
        kind || ':' || season as eval_window,
        model_version,
        cohort,
        candidate,
        baseline_mae,
        baseline_within_band1_rate
    from {{ ref('slv_eval_metrics') }}
),

by_cohort as (
    select
        p.eval_id,
        p.cohort,
        sum(w.n) as n,
        sum(w.baseline_mae * w.n) / sum(w.n) as baseline_mae,
        sum(w.baseline_within_band1_rate * w.n) / sum(w.n) as baseline_within_band1_rate
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
        sum(baseline_mae * n) / sum(n) as baseline_mae,
        sum(baseline_within_band1_rate * n) / sum(n) as baseline_within_band1_rate
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
    c.n,
    p.baseline_mae as published_baseline_mae,
    c.baseline_mae as computed_baseline_mae,
    abs(p.baseline_within_band1_rate - c.baseline_within_band1_rate) * c.n as band1_rows_off
from published as p
left join computed as c on p.eval_id = c.eval_id and p.cohort = c.cohort
where
    c.baseline_mae is null
    or abs(p.baseline_mae - c.baseline_mae) > {{ tol }}
    or abs(p.baseline_within_band1_rate - c.baseline_within_band1_rate) * c.n > {{ max_rows_off }} + 0.5
