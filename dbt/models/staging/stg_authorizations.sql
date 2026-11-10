with ranked as (
    select *, row_number() over (
        partition by auth_id order by _batch_seq desc, _row_number desc
    ) as _rn
    from {{ source('raw', 'authorizations') }}
)
select
    auth_id,
    nullif(trim(order_ref), '') as order_ref,
    merchant_id,
    card_token,
    bin,
    currency,
    cast(amount_minor as bigint) as amount_minor,
    entry_mode,
    card_present = 'true' as card_present,
    three_ds,
    response_code,
    approved = 'true' as approved,
    cast(requested_at as timestamp) as requested_at,
    cast(cast(requested_at as timestamp) as date) as requested_date,
    nullif(trim(retry_of), '') as retry_of
from ranked
where _rn = 1
