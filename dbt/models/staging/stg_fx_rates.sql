with ranked as (
    select *, row_number() over (
        partition by rate_date, currency order by _batch_seq desc, _row_number desc
    ) as _rn
    from {{ source('raw', 'fx_rates') }}
)
select
    cast(rate_date as date)               as rate_date,
    currency,
    cast(usd_micro_per_unit as bigint)    as usd_micro_per_unit
from ranked
where _rn = 1
