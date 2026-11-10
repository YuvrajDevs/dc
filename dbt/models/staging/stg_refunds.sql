with ranked as (
    select *, row_number() over (
        partition by refund_id order by _batch_seq desc, _row_number desc
    ) as _rn
    from {{ source('raw', 'refunds') }}
)
select
    refund_id,
    order_ref,
    merchant_id,
    currency,
    cast(amount_minor as bigint) as amount_minor,
    cast(refunded_at as timestamp) as refunded_at
from ranked
where _rn = 1
