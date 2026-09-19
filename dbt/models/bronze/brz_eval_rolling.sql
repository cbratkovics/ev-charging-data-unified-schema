{{ config(materialized='table') }}

-- One row per scored in-season period from artifacts/eval/rolling_<season>.json.
-- Optional family: empty (typed) until the scheduled job has written a rolling file.
{% if files_exist('artifacts/eval/rolling_*.json') %}
with files as (
    select * from {{ source('repo_files', 'eval_rolling') }}
)

select
    f.filename as source_file,
    cast(f.season as integer) as season,
    cast(p.period as integer) as period,
    cast(p.n as integer) as n,
    cast(p.champion.mae as double) as champion_mae,
    cast(p.champion.within_band1_rate as double) as champion_within_band1_rate,
    cast(p.champion.baseline_mae as double) as champion_baseline_mae,
    cast(p.challenger.mae as double) as challenger_mae,
    cast(p.challenger.within_band1_rate as double) as challenger_within_band1_rate,
    cast(p.challenger.baseline_mae as double) as challenger_baseline_mae,
    cast(p.scored_at_utc as timestamp) as scored_at_utc
from files as f, unnest(f.periods) as u (p)
{% else %}
{{ empty_typed_relation([
    ['source_file', 'varchar'], ['season', 'integer'], ['period', 'integer'], ['n', 'integer'],
    ['champion_mae', 'double'], ['champion_within_band1_rate', 'double'], ['champion_baseline_mae', 'double'],
    ['challenger_mae', 'double'], ['challenger_within_band1_rate', 'double'], ['challenger_baseline_mae', 'double'],
    ['scored_at_utc', 'timestamp'],
]) }}
{% endif %}
