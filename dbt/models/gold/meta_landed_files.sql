-- The landing manifest as a table: one row per landed file that bronze reads (quarantined
-- batches excluded). fct_charging_session carries each row's sha256 and compares against this
-- table to decide which sources to replace (ADR-0011 items 1 and 2). Not exported.
{{ config(materialized='table', meta={'export': false}) }}

with entries as (
    select unnest(map_entries(files)) as f
    from {{ source('landed', 'manifest') }}
)

select
    cast(f.key as varchar) as manifest_key,
    cast(f.value.source as varchar) as source,
    cast(f.value.file_name as varchar) as file_name,
    cast(f.value.sha256 as varchar) as sha256,
    cast(f.value.row_count as bigint) as row_count,
    cast(f.value.retrieved_at as timestamptz) as retrieved_at_utc,
    cast(f.value.landed_path as varchar) as landed_path
from entries
where not contains(f.value.landed_path, '/_quarantined/')
