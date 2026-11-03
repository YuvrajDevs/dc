with ranked as (
    select *, row_number() over (
        partition by merchant_id order by _batch_seq desc, _row_number desc
    ) as _rn
    from {{ source('raw', 'merchants') }}
)
select merchant_id, name, currency, fee_tier
from ranked
where _rn = 1
