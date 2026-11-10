with ranked as (
    select *, row_number() over (
        partition by dispute_id order by _batch_seq desc, _row_number desc
    ) as _rn
    from {{ source('raw', 'disputes') }}
)
select
    dispute_id,
    order_ref,
    merchant_id,
    network,
    reason_category,
    reason_code,
    reason_label,
    currency,
    cast(amount_minor as bigint) as amount_minor,
    cast(fee_minor as bigint) as fee_minor,
    cast(opened_at as timestamp) as opened_at,
    cast(cast(opened_at as timestamp) as date) as opened_date,
    cast(response_due as date) as response_due,
    cast(nullif(responded_on, '') as date) as responded_on,
    status,
    outcome
from ranked
where _rn = 1
