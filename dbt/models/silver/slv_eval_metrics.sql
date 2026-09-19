-- Grain: one row per (eval_id, cohort). cohort = 'ALL' plus one row per cohort. The numbers are
-- the committed evaluation artifacts verbatim (rounded to 4 dp as published); the gold
-- reconciliation tests compare fct_period_eval against this table.
with artifacts as (
    select * from {{ ref('brz_eval_artifacts') }}
),

cohorts as (
    select
        a.eval_id,
        'ALL' as cohort,
        cast(null as varchar) as candidate,
        a.metrics.n as n,
        a.metrics.mae as mae,
        a.metrics.median_ae as median_ae,
        a.metrics.rmse as rmse,
        a.metrics.within_band1_rate as within_band1_rate,
        a.metrics.within_band2_rate as within_band2_rate,
        a.baseline.n as baseline_n,
        a.baseline.mae as baseline_mae,
        a.baseline.within_band1_rate as baseline_within_band1_rate
    from artifacts as a
    {% for c in var('cohorts') %}
    union all
    select
        a.eval_id,
        '{{ c }}' as cohort,
        a.model.candidate.{{ c }} as candidate,
        a.cohorts.{{ c }}.n as n,
        a.cohorts.{{ c }}.mae as mae,
        a.cohorts.{{ c }}.median_ae as median_ae,
        a.cohorts.{{ c }}.rmse as rmse,
        a.cohorts.{{ c }}.within_band1_rate as within_band1_rate,
        a.cohorts.{{ c }}.within_band2_rate as within_band2_rate,
        a.cohorts.{{ c }}.baseline.n as baseline_n,
        a.cohorts.{{ c }}.baseline.mae as baseline_mae,
        a.cohorts.{{ c }}.baseline.within_band1_rate as baseline_within_band1_rate
    from artifacts as a
    {% endfor %}
)

select
    a.eval_id,
    a.kind,
    a.season,
    a.model.version as model_version,
    a.model.feature_version as feature_version,
    a.code_commit,
    a.generated_at_utc,
    a.input.path as input_path,
    a.input.sha256 as input_sha256,
    a.baseline.name as baseline_name,
    c.cohort,
    c.candidate,
    cast(c.n as integer) as n,
    c.mae,
    c.median_ae,
    c.rmse,
    c.within_band1_rate,
    c.within_band2_rate,
    cast(c.baseline_n as integer) as baseline_n,
    c.baseline_mae,
    c.baseline_within_band1_rate
from cohorts as c
inner join artifacts as a on c.eval_id = a.eval_id
