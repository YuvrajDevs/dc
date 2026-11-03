-- Each payout beside what its transactions actually add up to.
select
    p.payout_id,
    p.merchant_id,
    p.currency,
    p.payout_date,
    p.txn_count,
    p.net_minor_total,
    coalesce(t.txn_count_actual, 0)  as txn_count_actual,
    coalesce(t.net_minor_actual, 0)  as net_minor_actual,
    p.net_minor_total - coalesce(t.net_minor_actual, 0) as net_minor_delta
from {{ ref('stg_processor_payouts') }} p
left join (
    select payout_id, count(*) as txn_count_actual, sum(net_minor) as net_minor_actual
    from {{ ref('stg_processor_txns') }}
    group by payout_id
) t on t.payout_id = p.payout_id
