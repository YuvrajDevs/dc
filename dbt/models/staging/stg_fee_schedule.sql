with ranked as (
    select *, row_number() over (
        partition by fee_tier, currency, effective_from
        order by _batch_seq desc, _row_number desc
    ) as _rn
    from {{ source('raw', 'fee_schedule') }}
)
select
    fee_tier,
    currency,
    cast(bps as bigint)                as bps,
    cast(fixed_minor as bigint)        as fixed_minor,
    cast(effective_from as date)       as effective_from
from ranked
where _rn = 1
