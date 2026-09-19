{{ config(materialized='table') }}

-- artifacts/models/<version>/test_predictions.csv, typed. model_version comes from the path.
select
    filename as source_file,
    regexp_extract(filename, 'models/([^/]+)/test_predictions\.csv$', 1) as model_version,
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
from {{ source('repo_files', 'predictions_test') }}
