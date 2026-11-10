with ranked as (
    select *, row_number() over (
        partition by merchant_id order by _batch_seq desc, _row_number desc
    ) as _rn
    from {{ source('raw', 'merchant_profiles') }}
)
select
    merchant_id,
    mcc,
    mcc_description,
    mcc_group,
    country,
    region,
    cast(cnp_share_bps as bigint) as cnp_share_bps
from ranked
where _rn = 1
