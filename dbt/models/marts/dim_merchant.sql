select merchant_id, name, currency, fee_tier
from {{ ref('stg_merchants') }}
