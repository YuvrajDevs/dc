with ranked as (
    select *, row_number() over (
        partition by payout_id order by _batch_seq desc, _row_number desc
    ) as _rn
    from {{ source('raw', 'processor_payouts') }}
)
select
    payout_id,
    merchant_id,
    currency,
    cast(payout_date as date)        as payout_date,
    cast(txn_count as bigint)        as txn_count,
    cast(net_minor_total as bigint)  as net_minor_total,
    _batch_id
from ranked
where _rn = 1
