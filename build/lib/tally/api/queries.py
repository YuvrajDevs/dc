"""SQL the dashboard needs. Parameters are always bound, never pasted into the text."""

from __future__ import annotations

FX = """fx AS (
  SELECT currency, CASE WHEN currency = 'USD' THEN 1000000 ELSE usd_micro_per_unit END AS micro
  FROM marts.dim_fx_rate WHERE rate_date = (SELECT max(rate_date) FROM marts.dim_fx_rate)
)"""

# one row per exception with merchant, date and a USD amount
EXCEPTIONS = f"""
WITH {FX}, ex AS (
  SELECT e.finding_id, e.class, e.category, e.level, e.status, e.note, e.updated_by, e.updated_at,
         e.reason, e.amount_at_stake_minor, e.currency, f.confidence,
         json_extract_string(e.entities, '$[0].source') AS src,
         json_extract_string(e.entities, '$[0].id') AS ent_id
  FROM ops.exceptions e LEFT JOIN recon.findings f ON f.finding_id = e.finding_id
), x AS (
  SELECT ex.*,
         coalesce(l.merchant_id, t.merchant_id, p.merchant_id) AS merchant_id,
         coalesce(l.booked_date, t.captured_date, p.payout_date, b.value_date) AS occurred_on,
         round(ex.amount_at_stake_minor * coalesce(fx.micro, 1000000) / 100000000.0, 2) AS amount_usd
  FROM ex
  LEFT JOIN marts.fct_ledger_entry l ON ex.src = 'ledger' AND l.ledger_id = ex.ent_id
  LEFT JOIN marts.fct_processor_txn t ON ex.src = 'processor' AND t.txn_id = ex.ent_id
  LEFT JOIN marts.fct_payout p ON ex.src = 'processor_payout' AND p.payout_id = ex.ent_id
  LEFT JOIN marts.fct_bank_line b ON ex.src = 'bank' AND b.bank_line_id = ex.ent_id
  LEFT JOIN fx ON fx.currency = ex.currency
)
"""

SORTS = {
    "amount": "amount_usd DESC, finding_id",
    "date": "occurred_on DESC, finding_id",
    "class": "class, amount_usd DESC",
    "status": "status, amount_usd DESC",
}

ENTITY_TABLES = {
    "ledger": ("marts.fct_ledger_entry", "ledger_id"),
    "processor": ("marts.fct_processor_txn", "txn_id"),
    "processor_payout": ("marts.fct_payout", "payout_id"),
    "bank": ("marts.fct_bank_line", "bank_line_id"),
}

PAYOUTS = """
WITH pf AS (
  SELECT json_extract_string(entities, '$[0].id') AS payout_id, class, finding_id
  FROM recon.findings WHERE level = 'payout' AND class <> 'bank_ref_missing'
), ps AS (
  SELECT s.payout_id, s.merchant_id, s.currency, s.payout_date, s.net_minor_total, s.n_lines,
         s.bank_total, s.first_value_date,
         pf.class AS finding_class, pf.finding_id,
         CASE
           WHEN pf.class IS NOT NULL THEN pf.class
           WHEN s.n_lines = 0 THEN 'pending'
           ELSE 'matched'
         END AS status
  FROM recon.payout_summary s LEFT JOIN pf ON pf.payout_id = s.payout_id
)
SELECT * FROM ps
"""
