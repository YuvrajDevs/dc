with ranked as (
    select *, row_number() over (
        partition by clearing_id order by _batch_seq desc, _row_number desc
    ) as _rn
    from {{ source('raw', 'clearing_records') }}
)
select
    clearing_id,
    auth_id,
    order_ref,
    txn_id,
    merchant_id,
    network,
    currency,
    cast(amount_minor as bigint) as amount_minor,
    cast(interchange_bps as bigint) as interchange_bps,
    cast(interchange_minor as bigint) as interchange_minor,
    cast(scheme_fee_minor as bigint) as scheme_fee_minor,
    qualification,
    cast(cleared_at as timestamp) as cleared_at,
    cast(cast(cleared_at as timestamp) as date) as cleared_date
from ranked
where _rn = 1
