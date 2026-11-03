-- A versioned fee schedule: each row is valid from its effective date until the next version.
select
    fee_tier,
    currency,
    bps,
    fixed_minor,
    effective_from                                   as valid_from,
    coalesce(
        lead(effective_from) over (partition by fee_tier, currency order by effective_from),
        date '9999-12-31'
    )                                                as valid_to     -- exclusive
from {{ ref('stg_fee_schedule') }}
