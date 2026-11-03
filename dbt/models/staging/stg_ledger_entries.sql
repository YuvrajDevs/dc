-- One row per ledger_id. A later delivery of the same id replaces an earlier one (a correction).
-- Two different ledger_ids with the same order_ref are kept: that is a real duplicate booking.
with ranked as (
    select *, row_number() over (
        partition by ledger_id order by _batch_seq desc, _row_number desc
    ) as _rn
    from {{ source('raw', 'ledger_entries') }}
)
select
    ledger_id,
    order_ref                                  as order_ref_raw,
    nullif(upper(trim(order_ref)), '')         as order_ref_norm,
    merchant_id,
    currency,
    cast(amount_minor as bigint)               as amount_minor,
    cast(amount_base_minor as bigint)          as amount_base_minor,
    cast(booked_at as timestamp)               as booked_at,
    cast(cast(booked_at as timestamp) as date) as booked_date,
    _batch_id
from ranked
where _rn = 1
