-- The rules macro must reproduce the source's own published target on every row to within 0.01
-- (the Python twin: tests/test_interfaces.py::test_target_spec_derives_and_reconciles).
select
    station_id,
    day,
    day,
    target_rules_value,
    utilization,
    abs(target_rules_value - utilization) as abs_diff
from {{ ref('slv_period_rows') }}
where utilization is not null and abs(target_rules_value - utilization) > 0.01
