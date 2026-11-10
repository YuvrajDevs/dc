-- Why authorizations fail, by channel, with the share of each reason.
with d as (
    select response_code, response_label, soft_decline, channel, count(*) as declines
    from {{ ref('fct_authorization') }}
    where not approved
    group by all
)
select
    *,
    round(10000.0 * declines / sum(declines) over (partition by channel))::bigint as share_of_channel_bps
from d
