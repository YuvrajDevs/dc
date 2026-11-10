-- Dispute curve: of the transactions cleared in a month, the cumulative share disputed
-- after N days. Analysts use it to see how long a month's disputes keep arriving.
with cohort as (
    select date_trunc('month', cleared_date)::date as cohort_month, count(*) as transactions
    from {{ ref('fct_clearing') }}
    group by 1
),
bucket as (select unnest([7, 14, 30, 45, 60, 90]) as day_bucket),
d as (
    select date_trunc('month', transaction_date)::date as cohort_month, days_to_dispute
    from {{ ref('fct_dispute') }}
    where transaction_date is not null
)
select
    c.cohort_month,
    b.day_bucket,
    c.transactions,
    count(d.days_to_dispute)                                         as disputes_by_day,
    round(10000.0 * count(d.days_to_dispute) / c.transactions)::bigint as cumulative_dispute_rate_bps
from cohort c
cross join bucket b
left join d on d.cohort_month = c.cohort_month and d.days_to_dispute <= b.day_bucket
group by c.cohort_month, b.day_bucket, c.transactions
