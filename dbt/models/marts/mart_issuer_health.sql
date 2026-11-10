-- Issuer health per day: approval rate, and "issuer unavailable" (91) answers, which
-- normally never happen. A day with a burst of 91s is a suspected outage; the first and last
-- timeout give the window to report to the issuer.
select
    issuer_id,
    issuer_name,
    requested_date,
    count(*)                                             as attempts,
    count(*) filter (where approved)                     as approvals,
    count(*) filter (where response_code = '91')         as unavailable,
    min(requested_at) filter (where response_code = '91') as first_unavailable_at,
    max(requested_at) filter (where response_code = '91') as last_unavailable_at,
    round(10000.0 * count(*) filter (where approved) / count(*))::bigint as approval_rate_bps,
    count(*) filter (where response_code = '91') >= 3
        and 10 * count(*) filter (where response_code = '91') >= count(*) as outage_suspected
from {{ ref('fct_authorization') }}
group by all
