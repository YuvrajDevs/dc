-- Each cleared transaction with the interchange the rate card says it should have paid.
-- The rate card logic (regional caps, cross-border add-ons, category discounts) is
-- re-derived here in SQL, so any charge above it shows up as leakage to investigate.
with c as (select * from {{ ref('stg_clearing_records') }}),
x as (
    select
        c.*,
        a.channel,
        a.product,
        a.issuer_id,
        a.issuer_region,
        a.merchant_region,
        a.mcc_group,
        a.cross_border,
        a.three_ds,
        s.base_bps
            - case when a.mcc_group = 'everyday' then s.everyday_discount_bps else 0 end as bps_after_discount,
        s.fixed_minor,
        s.eu_cap_bps,
        s.cross_border_add_bps,
        a.merchant_region = 'EU' and a.issuer_region = 'EU' as domestic_eu
    from c
    join {{ ref('fct_authorization') }} a on a.auth_id = c.auth_id
    join {{ ref('stg_interchange_schedule') }} s on s.product = a.product and s.channel = a.channel
),
expected as (
    select
        *,
        greatest(
            case
                when domestic_eu then least(bps_after_discount, eu_cap_bps)
                when merchant_region <> issuer_region then bps_after_discount + cross_border_add_bps
                else bps_after_discount
            end, 0
        ) as expected_bps
    from x
)
select
    clearing_id, auth_id, order_ref, txn_id, merchant_id, network, product, channel,
    issuer_id, issuer_region, merchant_region, mcc_group, cross_border, three_ds, currency,
    amount_minor, interchange_bps, interchange_minor, scheme_fee_minor, qualification,
    cleared_at, cleared_date,
    expected_bps,
    (amount_minor * expected_bps + 5000) // 10000 + case when domestic_eu then 0 else fixed_minor end
        as expected_interchange_minor,
    interchange_minor - ((amount_minor * expected_bps + 5000) // 10000
        + case when domestic_eu then 0 else fixed_minor end) as interchange_overcharge_minor
from expected
