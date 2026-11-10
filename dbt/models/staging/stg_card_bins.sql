with ranked as (
    select *, row_number() over (
        partition by bin order by _batch_seq desc, _row_number desc
    ) as _rn
    from {{ source('raw', 'card_bins') }}
)
select
    bin,
    network,
    product,
    issuer_id,
    issuer_name,
    issuer_country,
    issuer_region
from ranked
where _rn = 1
