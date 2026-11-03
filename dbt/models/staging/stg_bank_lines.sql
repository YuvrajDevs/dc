with ranked as (
    select *, row_number() over (
        partition by bank_line_id order by _batch_seq desc, _row_number desc
    ) as _rn
    from {{ source('raw', 'bank_lines') }}
)
select
    bank_line_id,
    nullif(trim(reference), '')      as reference,
    currency,
    cast(amount_minor as bigint)     as amount_minor,
    cast(value_date as date)         as value_date,
    description,
    _batch_id
from ranked
where _rn = 1
