-- Row conservation (docs/BRIEF.md § 5): for every source and file, bronze rows =
-- accepted + quarantined. Fails on any file where the three counts do not add up.
{% set sources = ['boulder', 'cary', 'dft_2017'] %}

with bronze as (
    {% for s in sources %}
    select
        '{{ s }}' as source,
        _file_name as source_file,
        count(*) as bronze_rows
    from {{ ref('brz_' ~ s) }}
    group by 1, 2
    {{ 'union all' if not loop.last }}
    {% endfor %}
),

accepted as (
    select
        source,
        source_file,
        count(*) as accepted_rows
    from {{ ref('slv_sessions_unioned') }}
    group by 1, 2
),

quarantined as (
    select
        source,
        source_file,
        count(*) as quarantined_rows
    from {{ ref('slv_sessions_quarantined') }}
    group by 1, 2
)

select
    b.source,
    b.source_file,
    b.bronze_rows,
    coalesce(a.accepted_rows, 0) as accepted_rows,
    coalesce(q.quarantined_rows, 0) as quarantined_rows
from bronze as b
left join accepted as a on b.source = a.source and b.source_file = a.source_file
left join quarantined as q on b.source = q.source and b.source_file = q.source_file
where b.bronze_rows <> coalesce(a.accepted_rows, 0) + coalesce(q.quarantined_rows, 0)
