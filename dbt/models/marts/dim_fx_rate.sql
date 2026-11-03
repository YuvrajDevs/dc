select rate_date, currency, usd_micro_per_unit
from {{ ref('stg_fx_rates') }}
