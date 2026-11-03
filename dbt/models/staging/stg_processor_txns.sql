with ranked as (
    select *, row_number() over (
        partition by txn_id order by _batch_seq desc, _row_number desc
    ) as _rn
    from {{ source('raw', 'processor_txns') }}
)
select
    txn_id,
    nullif(upper(trim(order_ref)), '')          as order_ref_norm,
    order_ref                                   as order_ref_raw,
    merchant_id,
    currency,
    cast(gross_minor as bigint)                 as gross_minor,
    cast(fee_minor as bigint)                   as fee_minor,
    cast(net_minor as bigint)                   as net_minor,
    cast(captured_at as timestamp)              as captured_at,
    cast(cast(captured_at as timestamp) as date) as captured_date,
    payout_id,
    _batch_id
from ranked
where _rn = 1
