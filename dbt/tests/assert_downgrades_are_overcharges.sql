-- A downgraded transaction must cost more than the rate card says.
select clearing_id
from {{ ref('fct_clearing') }}
where qualification = 'downgraded'
  and interchange_overcharge_minor <= 0
