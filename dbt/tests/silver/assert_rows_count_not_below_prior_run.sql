-- Row-count monotonicity: the rows may only grow between scheduled runs (var prior_row_count from
-- manifest.last_run.rows). Unset = pass.
{% set prior = var('prior_row_count') %}

select
    count(*) as row_count,
{% if prior is none %}
cast(null as integer) as prior_row_count
from {{ ref('slv_period_rows') }}
having false
{% else %}
    {{ prior }} as prior_row_count
from {{ ref('slv_period_rows') }}
having count(*) < {{ prior }}
    {% endif %}
