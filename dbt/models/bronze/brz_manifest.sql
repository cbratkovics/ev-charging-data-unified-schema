{{ config(materialized='table') }}

-- artifacts/manifest.json as one row.
select
    filename as source_file,
    cast(manifest_version as varchar) as manifest_version,
    cast(feature_version as varchar) as feature_version,
    cast(champion.model_version as varchar) as champion_model_version,
    cast(challenger.model_version as varchar) as challenger_model_version,
    cast(eval_id as varchar) as eval_id,
    evaluations,
    cast(data_through.season as integer) as data_through_season,
    cast(data_through.period as integer) as data_through_period,
    cast(predictions.latest as varchar) as predictions_latest,
    cast(last_run.run_id as varchar) as last_run_id,
    cast(last_run.at_utc as timestamp) as last_run_at_utc,
    cast(last_run.action as varchar) as last_run_action,
    cast(last_run.rows as integer) as last_run_rows,
    cast(updated_at_utc as timestamp) as updated_at_utc
from {{ source('repo_files', 'manifest') }}
