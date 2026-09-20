-- Every quarantined row has exactly one primary reason that is one of its failing reasons
-- (ADR-0009 item 4), so a breakdown by primary_reason sums to the quarantined total.
select *
from {{ ref('slv_sessions_quarantined') }}
where
    primary_reason is null
    or not list_contains(quarantine_reasons, primary_reason)
    or len(quarantine_reasons) = 0
