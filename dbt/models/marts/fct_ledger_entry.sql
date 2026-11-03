select
    ledger_id,
    order_ref_raw,
    order_ref_norm,
    merchant_id,
    currency,
    amount_minor,
    amount_base_minor,
    booked_at,
    booked_date
from {{ ref('stg_ledger_entries') }}
