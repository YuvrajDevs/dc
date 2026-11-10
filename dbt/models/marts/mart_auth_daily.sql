-- Approval performance by day and the dimensions analysts slice on.
select
    requested_date,
    merchant_id,
    mcc_group,
    network,
    product,
    issuer_id,
    issuer_region,
    channel,
    cross_border,
    count(*)                                         as attempts,
    count(*) filter (where approved)                 as approvals,
    count(*) filter (where soft_decline)             as soft_declines,
    count(*) filter (where hard_decline)             as hard_declines,
    count(*) filter (where recovered_by_retry)       as recovered_by_retry,
    sum(amount_minor) filter (where approved)        as approved_amount_minor,
    round(10000.0 * count(*) filter (where approved) / count(*))::bigint as approval_rate_bps
from {{ ref('fct_authorization') }}
group by all
