-- Grain: one row per (eval_id, season, period): the rolling-origin folds of each artifact.
with artifacts as (
    select * from {{ ref('brz_eval_artifacts') }}
)

select
    a.eval_id,
    a.kind,
    a.model.version as model_version,
    a.rolling_origin.candidate as candidate,
    cast(f.season as integer) as season,
    cast(f.period as integer) as period,
    cast(f.n as integer) as n,
    f.mae,
    f.baseline_mae
from artifacts as a, unnest(a.rolling_origin.folds) as u (f)
