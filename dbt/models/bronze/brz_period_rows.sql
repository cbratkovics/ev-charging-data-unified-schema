{{ config(materialized='table') }}

-- Newest source snapshot only: cache files are named period_rows_<first>-<last>_<load-date>.parquet,
-- so the lexicographically greatest filename is the widest season range at the latest load date.
-- Columns: the id + raw stat columns the package keeps (data.loader.ID_COLUMNS / STAT_COLUMNS), typed.
with snapshots as (
    select * from {{ source('repo_files', 'period_rows') }}
),

newest as (
    select max(filename) as filename from snapshots
)

select
    s.filename as source_file,
    cast(s.station_id as varchar) as station_id,
    cast(s.station_name as varchar) as station_name,
    cast(s.channel as varchar) as channel,
    cast(s.day as integer) as day,
    cast(s.day as integer) as day,
    cast(s.team as varchar) as team,
    {% for col in stat_columns() -%}
    cast(s.{{ col }} as double) as {{ col }},
    {% endfor -%}
    cast(s.utilization as double) as utilization
from snapshots as s
inner join newest as n on s.filename = n.filename
