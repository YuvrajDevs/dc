select txn_id from {{ ref('fct_processor_txn') }}
where net_minor <> gross_minor - fee_minor
