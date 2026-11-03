select bank_line_id, reference, currency, amount_minor, value_date, description
from {{ ref('stg_bank_lines') }}
