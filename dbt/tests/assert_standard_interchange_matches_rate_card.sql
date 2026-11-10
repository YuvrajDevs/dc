-- The SQL rate card must reproduce what the network charged for every transaction that
-- qualified normally. If this returns rows, the leakage numbers cannot be trusted.
select clearing_id, interchange_minor, expected_interchange_minor
from {{ ref('fct_clearing') }}
where qualification = 'standard'
  and interchange_overcharge_minor <> 0
