-- Disputes with the transaction they challenge and where they stand.
with as_of as (select max(opened_date) as as_of_date from {{ ref('stg_disputes') }})
select
    d.dispute_id,
    d.order_ref,
    d.merchant_id,
    c.clearing_id,
    c.channel,
    c.product,
    c.three_ds,
    d.network,
    d.reason_category,
    d.reason_code,
    d.reason_label,
    d.currency,
    d.amount_minor,
    d.fee_minor,
    d.opened_at,
    d.opened_date,
    c.cleared_date                                   as transaction_date,
    date_diff('day', c.cleared_date, d.opened_date)  as days_to_dispute,
    d.response_due,
    d.responded_on,
    d.status,
    d.outcome,
    case
        when d.status = 'open' and d.response_due < as_of.as_of_date then 'overdue'
        when d.status = 'open' and d.response_due <= as_of.as_of_date + 7 then 'due_in_7_days'
        when d.status = 'open' then 'open'
        else 'closed'
    end                                              as deadline_state,
    -- What the merchant loses: the amount when the dispute is lost or accepted, plus the fee.
    case when d.outcome in ('lost', 'accepted') then d.amount_minor else 0 end + d.fee_minor
                                                     as merchant_loss_minor
from {{ ref('stg_disputes') }} d
cross join as_of
left join {{ ref('fct_clearing') }} c on c.order_ref = d.order_ref
