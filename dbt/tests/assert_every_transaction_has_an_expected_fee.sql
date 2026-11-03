-- Every transaction must find a fee-schedule version that covers its capture date.
select txn_id from {{ ref('fct_processor_txn') }} where expected_fee_minor is null
