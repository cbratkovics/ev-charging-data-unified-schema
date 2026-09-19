{{ config(materialized='table') }}

-- One row per prediction record in every artifacts/predictions/<season>/period_<pp>.json.
-- Optional family: empty (typed) until the scheduled job has scored a period.
{% if files_exist('artifacts/predictions/*/period_*.json') %}
with files as (
    select * from {{ source('repo_files', 'predictions_periodic') }}
)

select
    f.filename as source_file,
    cast(f.season as integer) as day,
    cast(f.period as integer) as day,
    cast(f.model_version as varchar) as model_version,
    cast(f.feature_version as varchar) as feature_version,
    cast(f.generated_at_utc as timestamp) as generated_at_utc,
    cast(f.actuals_attached_at_utc as timestamp) as actuals_attached_at_utc,
    cast(p.station_id as varchar) as station_id,
    cast(p.name as varchar) as station_name,
    cast(p.team as varchar) as team,
    cast(p.channel as varchar) as channel,
    cast(p.candidate as varchar) as candidate,
    cast(p.prediction as double) as prediction,
    cast(p.floor as double) as prediction_floor,
    cast(p.ceiling as double) as prediction_ceiling,
    cast(p.actual as double) as actual
from files as f, unnest(f.predictions) as u (p)
{% else %}
{{ empty_typed_relation([
    ['source_file', 'varchar'], ['day', 'integer'], ['day', 'integer'],
    ['model_version', 'varchar'], ['feature_version', 'varchar'], ['generated_at_utc', 'timestamp'],
    ['actuals_attached_at_utc', 'timestamp'], ['station_id', 'varchar'], ['station_name', 'varchar'],
    ['team', 'varchar'], ['channel', 'varchar'], ['candidate', 'varchar'], ['prediction', 'double'],
    ['prediction_floor', 'double'], ['prediction_ceiling', 'double'], ['actual', 'double'],
]) }}
{% endif %}
