-- A payout total must equal the sum of its transactions' net amounts. Any row returned is a failure.
select payout_id, net_minor_total, net_minor_actual
from {{ ref('fct_payout') }}
where net_minor_delta <> 0
