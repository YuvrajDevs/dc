-- What each merchant's card acceptance costs, and who earns it, per month.
-- Processor fee revenue = interchange (issuer) + scheme fees (network) + processor margin.
with c as (
    select c.*, p.fee_minor as processor_fee_minor
    from {{ ref('fct_clearing') }} c
    left join {{ ref('fct_processor_txn') }} p on p.txn_id = c.txn_id
)
select
    merchant_id,
    currency,
    date_trunc('month', cleared_date)::date          as month,
    count(*)                                         as transactions,
    sum(amount_minor)                                as volume_minor,
    sum(processor_fee_minor)                         as processor_fee_minor,
    sum(interchange_minor)                           as interchange_minor,
    sum(scheme_fee_minor)                            as scheme_fee_minor,
    sum(processor_fee_minor) - sum(interchange_minor) - sum(scheme_fee_minor) as processor_margin_minor,
    sum(greatest(interchange_overcharge_minor, 0))   as interchange_leakage_minor,
    count(*) filter (where qualification = 'downgraded') as downgraded_transactions,
    round(10000.0 * sum(interchange_minor) / sum(amount_minor))::bigint as effective_interchange_bps
from c
group by all
