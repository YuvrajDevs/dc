-- Each transaction with the fee the schedule says it should have paid on its capture date.
select
    t.txn_id,
    t.order_ref_norm,
    t.order_ref_raw,
    t.merchant_id,
    t.currency,
    t.gross_minor,
    t.fee_minor,
    t.net_minor,
    t.captured_at,
    t.captured_date,
    t.payout_id,
    m.fee_tier,
    (t.gross_minor * f.bps + 5000) // 10000 + f.fixed_minor      as expected_fee_minor,
    t.fee_minor - ((t.gross_minor * f.bps + 5000) // 10000 + f.fixed_minor) as fee_delta_minor
from {{ ref('stg_processor_txns') }} t
left join {{ ref('dim_merchant') }} m on m.merchant_id = t.merchant_id
left join {{ ref('dim_fee_schedule') }} f
    on f.fee_tier = m.fee_tier
   and f.currency = t.currency
   and t.captured_date >= f.valid_from
   and t.captured_date <  f.valid_to
