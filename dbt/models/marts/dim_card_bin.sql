-- Issuer, network and product for every BIN. One row per BIN.
select bin, network, product, issuer_id, issuer_name, issuer_country, issuer_region
from {{ ref('stg_card_bins') }}
