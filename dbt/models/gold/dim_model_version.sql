-- Grain: one row per model_version: training provenance plus the manifest's champion / challenger
-- slots. Versions that only appear in prediction files are kept with null provenance.
with versions as (
    select model_version from {{ ref('brz_model_metadata') }}
    union
    select distinct model_version from {{ ref('slv_predictions') }}
),

manifest as (
    select * from {{ ref('brz_manifest') }}
)

select
    cast(v.model_version as varchar) as model_version,
    cast(m.feature_version as varchar) as feature_version,
    cast(m.trained_at_utc as timestamp) as trained_at_utc,
    cast(m.data_through_season as integer) as data_through_season,
    cast(m.data_through_period as integer) as data_through_period,
    cast(array_to_string(m.train_seasons, ',') as varchar) as train_seasons,
    cast(m.val_season as integer) as val_season,
    cast(m.test_season as integer) as test_season,
    cast(m.target as varchar) as target,
    cast(m.input_sha256 as varchar) as input_sha256,
    cast(m.input_rows as integer) as input_rows,
    cast(m.code_commit as varchar) as code_commit,
    cast(m.sklearn_version as varchar) as sklearn_version,
    cast(m.data_library as varchar) as data_library,
    cast(m.interval_method as varchar) as interval_method,
    cast(coalesce(mf.champion_model_version = v.model_version, false) as boolean) as is_champion,
    cast(coalesce(mf.challenger_model_version = v.model_version, false) as boolean) as is_challenger
from versions as v
left join {{ ref('brz_model_metadata') }} as m on v.model_version = m.model_version
left join manifest as mf on true
