{{ config(materialized='table') }}

-- One row per trained model version (artifacts/models/<version>/metadata.json); the large
-- per-cohort blocks (feature lists, drift references) are not copied.
select
    filename as source_file,
    cast(model_version as varchar) as model_version,
    cast(feature_version as varchar) as feature_version,
    cast(sklearn_version as varchar) as sklearn_version,
    cast(data_library as varchar) as data_library,
    cast(trained_at_utc as timestamp) as trained_at_utc,
    cast(data_through.season as integer) as data_through_season,
    cast(data_through.period as integer) as data_through_period,
    seasons.train as train_seasons,
    cast(seasons.val as integer) as val_season,
    cast(seasons.test as integer) as test_season,
    cast(target as varchar) as target,
    cast(input_sha256 as varchar) as input_sha256,
    cast(input_rows as integer) as input_rows,
    cast(code_commit as varchar) as code_commit,
    cast(interval_method as varchar) as interval_method,
{% for c in var('cohorts') -%}
cast(cohorts.{{ c }}.champion as varchar) as champion_{{ c | lower }},
cast(cohorts.{{ c }}.n_features as integer) as n_features_{{ c | lower }},
cast(cohorts.{{ c }}.n_train as integer) as n_train_{{ c | lower }},
cast(cohorts.{{ c }}.n_test as integer) as n_test_{{ c | lower }}{{ "," if not loop.last }}  -- noqa: LT02

{% endfor %}
from {{ source('repo_files', 'model_metadata') }}
