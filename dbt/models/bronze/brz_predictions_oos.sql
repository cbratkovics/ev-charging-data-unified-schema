{{ config(materialized='table') }}

-- artifacts/models/<version>/oos_predictions_<season>.csv, typed. model_version comes from the
-- path. Optional family: empty (typed) until an out-of-sample season has been scored.
{% if files_exist('artifacts/models/*/oos_predictions_*.csv') %}
select
    filename as source_file,
    regexp_extract(filename, 'models/([^/]+)/oos_predictions_\d+\.csv$', 1) as model_version,
    cast(station_id as varchar) as station_id,
    cast(day as integer) as day,
    cast(day as integer) as day,
    cast(channel as varchar) as channel,
    cast(station_name as varchar) as station_name,
    cast(team as varchar) as team,
    cast(candidate as varchar) as candidate,
    cast(prediction as double) as prediction,
    cast(prediction_floor as double) as prediction_floor,
    cast(prediction_ceiling as double) as prediction_ceiling,
    cast(actual as double) as actual
from {{ source('repo_files', 'predictions_oos') }}
{% else %}
{{ empty_typed_relation([
    ['source_file', 'varchar'], ['model_version', 'varchar'], ['station_id', 'varchar'],
    ['day', 'integer'], ['day', 'integer'], ['channel', 'varchar'],
    ['station_name', 'varchar'], ['team', 'varchar'], ['candidate', 'varchar'],
    ['prediction', 'double'], ['prediction_floor', 'double'], ['prediction_ceiling', 'double'], ['actual', 'double'],
]) }}
{% endif %}
