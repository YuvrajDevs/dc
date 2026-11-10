with ranked as (
    select *, row_number() over (
        partition by product, channel order by _batch_seq desc, _row_number desc
    ) as _rn
    from {{ source('raw', 'interchange_schedule') }}
)
select
    product,
    channel,
    cast(base_bps as bigint) as base_bps,
    cast(fixed_minor as bigint) as fixed_minor,
    cast(eu_cap_bps as bigint) as eu_cap_bps,
    cast(cross_border_add_bps as bigint) as cross_border_add_bps,
    cast(everyday_discount_bps as bigint) as everyday_discount_bps,
    cast(effective_from as date) as effective_from
from ranked
where _rn = 1
