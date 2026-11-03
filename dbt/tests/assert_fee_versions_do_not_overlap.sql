-- Two versions of the same fee must never be valid on the same day.
select a.fee_tier, a.currency, a.valid_from
from {{ ref('dim_fee_schedule') }} a
join {{ ref('dim_fee_schedule') }} b
  on a.fee_tier = b.fee_tier and a.currency = b.currency
 and a.valid_from < b.valid_from and b.valid_from < a.valid_to
