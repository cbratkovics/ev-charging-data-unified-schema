-- Grain: one row per (season, period): in-season champion vs challenger shadow evaluation.
select
    season,
    period,
    {{ period_key('season', 'period') }} as period_key,
    n,
    champion_mae,
    champion_within_band1_rate,
    champion_baseline_mae,
    challenger_mae,
    challenger_within_band1_rate,
    challenger_baseline_mae,
    scored_at_utc
from {{ ref('brz_eval_rolling') }}
