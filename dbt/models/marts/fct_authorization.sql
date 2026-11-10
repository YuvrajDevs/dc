-- Every authorization attempt, enriched with the card, the merchant and the decision.
with a as (select * from {{ ref('stg_authorizations') }}),
retried as (
    -- An attempt that a later retry on the same order turned into an approval.
    select retry_of as auth_id from a where retry_of is not null and approved
)
select
    a.auth_id,
    a.order_ref,
    a.merchant_id,
    p.mcc,
    p.mcc_group,
    p.region                                         as merchant_region,
    a.card_token,
    a.bin,
    b.network,
    b.product,
    b.issuer_id,
    b.issuer_name,
    b.issuer_region,
    b.issuer_region <> p.region                      as cross_border,
    a.currency,
    a.amount_minor,
    a.entry_mode,
    a.card_present,
    case when a.card_present then 'cp' else 'cnp' end as channel,
    a.three_ds,
    a.response_code,
    r.label                                          as response_label,
    a.approved,
    coalesce(r.soft, false) and not a.approved       as soft_decline,
    not coalesce(r.soft, false) and not a.approved   as hard_decline,
    a.retry_of is not null                           as is_retry,
    rt.auth_id is not null                           as recovered_by_retry,
    a.requested_at,
    a.requested_date,
    extract(hour from a.requested_at)                as requested_hour
from a
left join {{ ref('stg_merchant_profiles') }} p on p.merchant_id = a.merchant_id
left join {{ ref('dim_card_bin') }} b on b.bin = a.bin
left join {{ ref('response_codes') }} r on r.code = a.response_code
left join retried rt on rt.auth_id = a.auth_id
