-- Monthly dispute ratio per merchant against monitoring-programme thresholds.
-- Programme method: disputes opened in the month / transactions cleared in the same month.
-- Only complete months are rated: a month with a few days of sales and a full month of
-- incoming disputes would look alarming for every merchant.
with sales as (
    select merchant_id, date_trunc('month', cleared_date)::date as month,
           count(*) as cleared_txns, count(distinct cleared_date) as sales_days
    from {{ ref('fct_clearing') }}
    group by all
),
complete_months as (
    select month from sales group by month
    having max(sales_days) >= date_part('day', last_day(month)) - 1
),
disp as (
    select merchant_id, date_trunc('month', opened_date)::date as month, count(*) as disputes,
           count(*) filter (where reason_category = 'fraud_cnp') as fraud_disputes
    from {{ ref('fct_dispute') }}
    group by all
),
cohort as (
    -- Attribution method: disputes on the month's own transactions, whenever they arrive.
    select merchant_id, date_trunc('month', transaction_date)::date as month, count(*) as disputes_on_month
    from {{ ref('fct_dispute') }}
    where transaction_date is not null
    group by all
)
select
    s.merchant_id,
    s.month,
    s.cleared_txns,
    coalesce(d.disputes, 0)                                           as disputes,
    coalesce(d.fraud_disputes, 0)                                     as fraud_disputes,
    round(10000.0 * coalesce(d.disputes, 0) / s.cleared_txns)::bigint   as dispute_ratio_bps,
    round(10000.0 * coalesce(c.disputes_on_month, 0) / s.cleared_txns)::bigint as cohort_dispute_ratio_bps,
    case
        when coalesce(d.disputes, 0) >= {{ var('monitor_min_disputes') }}
         and 10000.0 * coalesce(d.disputes, 0) / s.cleared_txns >= {{ var('monitor_excessive_ratio_bps') }} then 'excessive'
        when 10000.0 * coalesce(d.disputes, 0) / s.cleared_txns >= {{ var('monitor_warning_ratio_bps') }} then 'warning'
        else 'ok'
    end                                                               as programme_status
from sales s
join complete_months using (month)
left join disp d using (merchant_id, month)
left join cohort c using (merchant_id, month)
