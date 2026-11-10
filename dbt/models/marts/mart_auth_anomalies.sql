-- Hour-level authorization signals per merchant, scored against that merchant's own
-- baseline. A card-testing attack looks like a burst of small, card-not-present attempts on
-- many distinct cards with a collapsing approval rate.
with h as (
    select
        merchant_id,
        date_trunc('hour', requested_at)                 as hour,
        count(*)                                         as attempts,
        count(distinct card_token)                       as distinct_cards,
        count(*) filter (where approved)                 as approvals,
        median(amount_minor)                             as median_amount_minor,
        count(*) filter (where channel = 'cnp')          as cnp_attempts
    from {{ ref('fct_authorization') }}
    group by all
),
baseline as (
    select merchant_id, avg(attempts) as mean_attempts, stddev_pop(attempts) as sd_attempts
    from h
    group by 1
)
select
    h.*,
    round(10000.0 * h.approvals / h.attempts)::bigint    as approval_rate_bps,
    round((h.attempts - b.mean_attempts) / nullif(b.sd_attempts, 0), 2) as attempts_zscore,
    (h.attempts - b.mean_attempts) / nullif(b.sd_attempts, 0) >= 4
        and h.approvals * 2 < h.attempts                  as flagged
from h
join baseline b using (merchant_id)
