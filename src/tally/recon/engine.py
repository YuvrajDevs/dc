"""The reconciliation engine, written as a sequence of SQL steps over the marts.

Matching works in tiers, strongest evidence first, and only unmatched records move down:

  ledger <-> processor transaction
    1. exact order reference
    2. normalised reference (trimmed, upper-cased)
    3. reference with the ``ord_`` prefix stripped
    4. attributes: same merchant, currency and amount, booked within a time window

  processor payout <-> bank lines
    1. exact payout reference on the bank line
    2. attributes: same currency and amount, value date inside the expected window

Every disagreement becomes a *finding* with a class, the records involved, the amount at stake,
a confidence and a plain-language reason. Benign look-alikes are classified, not alarmed.
Nothing here reads the answer key.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import date

from tally.warehouse import Warehouse

ERROR, BENIGN = "error", "benign"


@dataclass(frozen=True)
class ReconConfig:
    as_of: date | None = (
        None  # the date "today" is; a payout is only missing once its window passed
    )
    grace_days: int = 3  # how many days late a payout may be before it counts as missing
    fx_tolerance_minor: int = 2  # base-currency rounding difference that is benign
    fee_tolerance_minor: int = 0  # fee difference allowed before it is a variance
    attr_before_minutes: int = 5  # attribute matching: ledger may be booked this early
    attr_after_hours: int = 26  # ... and this late (covers a booking after midnight)
    fuzzy_amount_pct: int = 12  # fuzzy tier: amounts may differ by up to this percentage
    fuzzy_after_minutes: int = 10  # fuzzy tier: tighter time window, since the amount is loose
    bank_fuzzy_pct: int = 22  # bank fuzzy tier: bank may be up to this percent short


@dataclass
class ReconSummary:
    as_of: date
    findings: dict[str, int] = field(default_factory=dict)
    links: dict[str, int] = field(default_factory=dict)
    match_methods: dict[str, int] = field(default_factory=dict)
    pending_payouts: int = 0
    step_seconds: dict[str, float] = field(default_factory=dict)

    @property
    def total_seconds(self) -> float:
        return sum(self.step_seconds.values())


def ent(source: str, id_expr: str) -> str:
    """SQL fragment for one entity reference, as JSON text."""
    return f'\'{{"source":"{source}","id":"\' || {id_expr} || \'"}}\''


def money(amount_expr: str, ccy_expr: str) -> str:
    return f"printf('%.2f %s', ({amount_expr}) / 100.0, {ccy_expr})"


FINDING_COLS = (
    "finding_id, class, category, level, entities, amount_at_stake_minor, currency, "
    "confidence, reason, detail"
)


def finding_sql(
    cls: str,
    category: str,
    level: str,
    entities: str,
    amount: str,
    currency: str,
    confidence: str,
    reason: str,
    detail: str,
    source: str,
) -> str:
    return f"""
    INSERT INTO recon._findings
    SELECT 'f_' || substr(md5('{cls}|' || ({entities})), 1, 12) AS finding_id,
           '{cls}' AS class, '{category}' AS category, '{level}' AS level,
           ({entities}) AS entities,
           CAST({amount} AS BIGINT) AS amount_at_stake_minor,
           {currency} AS currency,
           CAST({confidence} AS DOUBLE) AS confidence,
           {reason} AS reason,
           CAST({detail} AS VARCHAR) AS detail
    FROM {source}
    """


def steps(cfg: ReconConfig, as_of: date) -> list[tuple[str, str]]:
    g = cfg.grace_days
    s: list[tuple[str, str]] = []

    # ---- ledger <-> transaction ------------------------------------------------------------
    # A reference match is only believable if the records also agree on who and when:
    # same merchant, same currency, booked close to the capture. This stops a mistyped
    # reference that happens to name a different real order from being accepted.
    identity = f"""l.merchant_id = t.merchant_id AND l.currency = t.currency
              AND l.booked_at BETWEEN t.captured_at - INTERVAL '{cfg.attr_before_minutes} minutes'
                                  AND t.captured_at + INTERVAL '{cfg.attr_after_hours} hours'"""
    s.append(
        (
            "match_references",
            f"""
        CREATE OR REPLACE TABLE recon.ref_candidates AS
        SELECT l.ledger_id, t.txn_id, 'exact' AS method, 1.00 AS confidence,
               l.amount_minor = t.gross_minor AS strong
        FROM marts.fct_ledger_entry l
        JOIN marts.fct_processor_txn t ON l.order_ref_raw = t.order_ref_raw AND {identity}
        UNION ALL
        SELECT l.ledger_id, t.txn_id, 'normalised', 0.99, l.amount_minor = t.gross_minor
        FROM marts.fct_ledger_entry l
        JOIN marts.fct_processor_txn t ON l.order_ref_norm = t.order_ref_norm AND {identity}
        WHERE l.order_ref_norm IS NOT NULL AND l.order_ref_raw IS DISTINCT FROM t.order_ref_raw
        UNION ALL
        SELECT l.ledger_id, t.txn_id, 'prefix_stripped', 0.97, l.amount_minor = t.gross_minor
        FROM marts.fct_ledger_entry l
        JOIN marts.fct_processor_txn t
          ON regexp_replace(l.order_ref_norm, '^ORD_', '') = regexp_replace(t.order_ref_norm, '^ORD_', '')
         AND {identity}
        WHERE l.order_ref_norm IS NOT NULL AND l.order_ref_norm <> t.order_ref_norm;

        -- Strong evidence first: reference AND amount agree. The earliest booking is primary;
        -- any further strong entry for the same transaction is a duplicate booking.
        CREATE OR REPLACE TABLE recon._strong_ranked AS
        SELECT c.ledger_id, c.txn_id, c.method, c.confidence,
               row_number() OVER (PARTITION BY c.txn_id ORDER BY l.booked_at, c.ledger_id) AS rn
        FROM recon.ref_candidates c JOIN marts.fct_ledger_entry l USING (ledger_id)
        WHERE c.strong;

        CREATE OR REPLACE TABLE recon.strong_links AS
        SELECT ledger_id, txn_id, method, confidence FROM recon._strong_ranked WHERE rn = 1;

        CREATE OR REPLACE TABLE recon.duplicate_entries AS
        SELECT ledger_id, txn_id FROM recon._strong_ranked WHERE rn > 1
        """,
        )
    )
    unmatched = """
        WITH ul AS (
            SELECT * FROM marts.fct_ledger_entry l
            WHERE NOT EXISTS (SELECT 1 FROM recon.strong_links s WHERE s.ledger_id = l.ledger_id)
              AND NOT EXISTS (SELECT 1 FROM recon.duplicate_entries d WHERE d.ledger_id = l.ledger_id)
        ), ut AS (
            SELECT * FROM marts.fct_processor_txn t
            WHERE NOT EXISTS (SELECT 1 FROM recon.strong_links s WHERE s.txn_id = t.txn_id)
        )"""
    s.append(
        (
            "match_attributes",
            f"""
        -- Tier 4: same merchant, currency and amount, booked inside the time window.
        CREATE OR REPLACE TABLE recon.attr_candidates AS
        {unmatched}
        SELECT ul.ledger_id, ut.txn_id,
               abs(epoch(ul.booked_at) - epoch(ut.captured_at)) AS dt
        FROM ul JOIN ut
          ON ul.merchant_id = ut.merchant_id AND ul.currency = ut.currency
         AND ul.amount_minor = ut.gross_minor
         AND ul.booked_at BETWEEN ut.captured_at - INTERVAL '{cfg.attr_before_minutes} minutes'
                              AND ut.captured_at + INTERVAL '{cfg.attr_after_hours} hours';

        CREATE OR REPLACE TABLE recon.attr_links AS
        WITH r1 AS (
            SELECT *, row_number() OVER (PARTITION BY ledger_id ORDER BY dt, txn_id) AS rn_l,
                   count(*) OVER (PARTITION BY ledger_id) AS n_l
            FROM recon.attr_candidates
        ), r2 AS (
            SELECT *, row_number() OVER (PARTITION BY txn_id ORDER BY dt, ledger_id) AS rn_t
            FROM r1 WHERE rn_l = 1
        )
        SELECT ledger_id, txn_id, 'attribute' AS method,
               CASE WHEN n_l = 1 THEN 0.90 ELSE 0.75 END AS confidence
        FROM r2 WHERE rn_t = 1;

        -- Tier 5 (fuzzy): amount differs by up to {cfg.fuzzy_amount_pct}% but the payment is the only
        -- one that close in time for that merchant, from both sides. Low confidence.
        CREATE OR REPLACE TABLE recon.fuzzy_candidates AS
        WITH ul AS (
            SELECT * FROM marts.fct_ledger_entry l
            WHERE NOT EXISTS (SELECT 1 FROM recon.strong_links s WHERE s.ledger_id = l.ledger_id)
              AND NOT EXISTS (SELECT 1 FROM recon.duplicate_entries d WHERE d.ledger_id = l.ledger_id)
              AND NOT EXISTS (SELECT 1 FROM recon.attr_links a WHERE a.ledger_id = l.ledger_id)
        ), ut AS (
            SELECT * FROM marts.fct_processor_txn t
            WHERE NOT EXISTS (SELECT 1 FROM recon.strong_links s WHERE s.txn_id = t.txn_id)
              AND NOT EXISTS (SELECT 1 FROM recon.attr_links a WHERE a.txn_id = t.txn_id)
        )
        SELECT ul.ledger_id, ut.txn_id
        FROM ul JOIN ut
          ON ul.merchant_id = ut.merchant_id AND ul.currency = ut.currency
         AND abs(ul.amount_minor - ut.gross_minor) * 100 <= {cfg.fuzzy_amount_pct} * ut.gross_minor
         AND ul.booked_at BETWEEN ut.captured_at - INTERVAL '{cfg.attr_before_minutes} minutes'
                              AND ut.captured_at + INTERVAL '{cfg.fuzzy_after_minutes} minutes';

        CREATE OR REPLACE TABLE recon.fuzzy_links AS
        SELECT ledger_id, txn_id, 'attribute_fuzzy' AS method, 0.60 AS confidence
        FROM recon.fuzzy_candidates
        QUALIFY count(*) OVER (PARTITION BY ledger_id) = 1 AND count(*) OVER (PARTITION BY txn_id) = 1
        """,
        )
    )
    s.append(
        (
            "resolve_links",
            """
        -- Last resort: a reference-only match (amount differs) between two records nothing else claimed.
        CREATE OR REPLACE TABLE recon.weak_links AS
        WITH weak AS MATERIALIZED (
            SELECT * FROM recon.ref_candidates WHERE NOT strong
        ), free AS (
            SELECT c.* FROM weak c
            WHERE NOT EXISTS (SELECT 1 FROM recon.strong_links s WHERE s.ledger_id = c.ledger_id)
              AND NOT EXISTS (SELECT 1 FROM recon.strong_links s WHERE s.txn_id = c.txn_id)
              AND NOT EXISTS (SELECT 1 FROM recon.duplicate_entries d WHERE d.ledger_id = c.ledger_id)
              AND NOT EXISTS (SELECT 1 FROM recon.attr_links a WHERE a.ledger_id = c.ledger_id)
              AND NOT EXISTS (SELECT 1 FROM recon.attr_links a WHERE a.txn_id = c.txn_id)
              AND NOT EXISTS (SELECT 1 FROM recon.fuzzy_links f WHERE f.ledger_id = c.ledger_id)
              AND NOT EXISTS (SELECT 1 FROM recon.fuzzy_links f WHERE f.txn_id = c.txn_id)
        ), ranked AS (
            SELECT *, row_number() OVER (PARTITION BY txn_id ORDER BY ledger_id) AS rn_t FROM free
        ), ranked2 AS (
            SELECT *, row_number() OVER (PARTITION BY ledger_id ORDER BY txn_id) AS rn_l FROM ranked WHERE rn_t = 1
        )
        SELECT ledger_id, txn_id, 'reference_only' AS method, 0.80 AS confidence
        FROM ranked2 WHERE rn_l = 1;

        CREATE OR REPLACE TABLE recon.txn_links AS
        SELECT ledger_id, txn_id, method, confidence FROM recon.strong_links
        UNION ALL SELECT ledger_id, txn_id, method, confidence FROM recon.attr_links
        UNION ALL SELECT ledger_id, txn_id, method, confidence FROM recon.fuzzy_links
        UNION ALL SELECT ledger_id, txn_id, method, confidence FROM recon.weak_links
        """,
        )
    )

    # ---- payout <-> bank -------------------------------------------------------------------
    s.append(
        (
            "match_bank",
            f"""
        CREATE OR REPLACE TABLE recon.bank_by_reference AS
        SELECT b.bank_line_id, p.payout_id, 'reference' AS method, 1.00 AS confidence
        FROM marts.fct_bank_line b JOIN marts.fct_payout p ON upper(b.reference) = upper(p.payout_id);

        CREATE OR REPLACE TABLE recon.bank_attr_candidates AS
        WITH ub AS (
            SELECT * FROM marts.fct_bank_line b
            WHERE NOT EXISTS (SELECT 1 FROM recon.bank_by_reference r WHERE r.bank_line_id = b.bank_line_id)
        ), up AS (
            SELECT * FROM marts.fct_payout p
            WHERE NOT EXISTS (SELECT 1 FROM recon.bank_by_reference r WHERE r.payout_id = p.payout_id)
        )
        SELECT ub.bank_line_id, up.payout_id,
               abs(date_diff('day', up.payout_date + 1, ub.value_date)) AS dd
        FROM ub JOIN up
          ON ub.currency = up.currency AND ub.amount_minor = up.net_minor_total
         AND ub.value_date BETWEEN up.payout_date AND up.payout_date + {g + 2};

        CREATE OR REPLACE TABLE recon.bank_attr_links AS
        WITH r1 AS (
            SELECT *, row_number() OVER (PARTITION BY bank_line_id ORDER BY dd, payout_id) AS rn_b,
                   count(*) OVER (PARTITION BY bank_line_id) AS n_b
            FROM recon.bank_attr_candidates
        ), r2 AS (
            SELECT *, row_number() OVER (PARTITION BY payout_id ORDER BY dd, bank_line_id) AS rn_p
            FROM r1 WHERE rn_b = 1
        )
        SELECT bank_line_id, payout_id, 'attribute' AS method,
               CASE WHEN n_b = 1 THEN 0.85 ELSE 0.70 END AS confidence
        FROM r2 WHERE rn_p = 1;

        -- Fuzzy: no reference and the amount is short, but it is the only candidate from both sides.
        CREATE OR REPLACE TABLE recon.bank_fuzzy_links AS
        WITH ub AS (
            SELECT * FROM marts.fct_bank_line b
            WHERE NOT EXISTS (SELECT 1 FROM recon.bank_by_reference r WHERE r.bank_line_id = b.bank_line_id)
              AND NOT EXISTS (SELECT 1 FROM recon.bank_attr_links a WHERE a.bank_line_id = b.bank_line_id)
        ), up AS (
            SELECT * FROM marts.fct_payout p
            WHERE NOT EXISTS (SELECT 1 FROM recon.bank_by_reference r WHERE r.payout_id = p.payout_id)
              AND NOT EXISTS (SELECT 1 FROM recon.bank_attr_links a WHERE a.payout_id = p.payout_id)
        ), cand AS (
            SELECT ub.bank_line_id, up.payout_id
            FROM ub JOIN up
              ON ub.currency = up.currency
             AND ub.amount_minor < up.net_minor_total
             AND (up.net_minor_total - ub.amount_minor) * 100 <= {cfg.bank_fuzzy_pct} * up.net_minor_total
             AND ub.value_date BETWEEN up.payout_date AND up.payout_date + {g + 2}
        )
        SELECT bank_line_id, payout_id, 'attribute_fuzzy' AS method, 0.60 AS confidence
        FROM cand
        QUALIFY count(*) OVER (PARTITION BY bank_line_id) = 1 AND count(*) OVER (PARTITION BY payout_id) = 1;

        CREATE OR REPLACE TABLE recon.payout_links AS
        SELECT payout_id, bank_line_id, method, confidence FROM recon.bank_by_reference
        UNION ALL
        SELECT payout_id, bank_line_id, method, confidence FROM recon.bank_attr_links
        UNION ALL
        SELECT payout_id, bank_line_id, method, confidence FROM recon.bank_fuzzy_links;

        CREATE OR REPLACE TABLE recon.payout_summary AS
        SELECT p.payout_id, p.merchant_id, p.currency, p.payout_date, p.net_minor_total,
               count(b.bank_line_id) AS n_lines,
               coalesce(sum(b.amount_minor), 0) AS bank_total,
               min(b.value_date) AS first_value_date,
               max(b.value_date) AS last_value_date,
               coalesce(string_agg(b.bank_line_id, ',' ORDER BY b.bank_line_id), '') AS line_ids,
               coalesce('[' || string_agg('{{"source":"bank","id":"' || b.bank_line_id || '"}}', ','
                        ORDER BY b.bank_line_id) || ']', '[]') AS bank_entities,
               min(pl.confidence) AS confidence
        FROM marts.fct_payout p
        LEFT JOIN recon.payout_links pl ON pl.payout_id = p.payout_id
        LEFT JOIN marts.fct_bank_line b ON b.bank_line_id = pl.bank_line_id
        GROUP BY ALL
        """,
        )
    )

    # ---- findings --------------------------------------------------------------------------
    s.append(
        (
            "init_findings",
            """
        CREATE OR REPLACE TABLE recon._findings (
            finding_id VARCHAR, class VARCHAR, category VARCHAR, level VARCHAR, entities VARCHAR,
            amount_at_stake_minor BIGINT, currency VARCHAR, confidence DOUBLE,
            reason VARCHAR, detail VARCHAR)
        """,
        )
    )
    pair = """recon.txn_links k
        JOIN marts.fct_ledger_entry l ON l.ledger_id = k.ledger_id
        JOIN marts.fct_processor_txn t ON t.txn_id = k.txn_id"""
    two = f"'[' || {ent('ledger', 'l.ledger_id')} || ',' || {ent('processor', 't.txn_id')} || ']'"

    s.append(
        (
            "findings_duplicates",
            finding_sql(
                "duplicate_ledger", ERROR, "txn",
                f"'[' || {ent('ledger', 'k.ledger_id')} || ',' || {ent('ledger', 'd.ledger_id')} || ']'",
                "d.amount_minor", "d.currency", "least(k.confidence, 0.99)",
                f"'The ledger booked order ' || coalesce(d.order_ref_raw, '(no reference)') || ' twice ('"
                f" || {money('d.amount_minor', 'd.currency')} || ')'",
                "json_object('order_ref', d.order_ref_raw)",
                """recon.duplicate_entries dup
                   JOIN recon.txn_links k ON k.txn_id = dup.txn_id
                   JOIN marts.fct_ledger_entry d ON d.ledger_id = dup.ledger_id""",
            ),
        )
    )  # fmt: skip
    s.append(
        (
            "findings_missing",
            finding_sql(
                "missing_in_ledger", ERROR, "txn", f"'[' || {ent('processor', 't.txn_id')} || ']'",
                "t.gross_minor", "t.currency", "1.0",
                f"'The processor captured ' || {money('t.gross_minor', 't.currency')} || ' (' || t.txn_id"
                " || ') but no ledger entry matches it'",
                "json_object('txn_id', t.txn_id)",
                """marts.fct_processor_txn t WHERE NOT EXISTS
                   (SELECT 1 FROM recon.txn_links a WHERE a.txn_id = t.txn_id)""",
            )
            + ";"
            + finding_sql(
                "missing_in_processor", ERROR, "txn", f"'[' || {ent('ledger', 'l.ledger_id')} || ']'",
                "l.amount_minor", "l.currency", "1.0",
                f"'The ledger booked ' || {money('l.amount_minor', 'l.currency')} || ' (' || l.ledger_id"
                " || ') but the processor has no matching capture'",
                "json_object('ledger_id', l.ledger_id)",
                """marts.fct_ledger_entry l
                   WHERE NOT EXISTS (SELECT 1 FROM recon.txn_links a WHERE a.ledger_id = l.ledger_id)
                     AND NOT EXISTS (SELECT 1 FROM recon.duplicate_entries d WHERE d.ledger_id = l.ledger_id)""",
            ),
        )
    )  # fmt: skip
    s.append(
        (
            "findings_amounts",
            finding_sql(
                "amount_mismatch", ERROR, "txn", two, "abs(l.amount_minor - t.gross_minor)", "t.currency",
                "k.confidence",
                f"'Ledger says ' || {money('l.amount_minor', 't.currency')} || ' but the processor captured '"
                f" || {money('t.gross_minor', 't.currency')}",
                "json_object('delta_minor', l.amount_minor - t.gross_minor)",
                pair + " WHERE l.amount_minor <> t.gross_minor",
            )
            + ";"
            + finding_sql(
                "fee_variance", ERROR, "txn", f"'[' || {ent('processor', 't.txn_id')} || ']'",
                "abs(t.fee_delta_minor)", "t.currency", "1.0",
                f"'Fee charged was ' || {money('t.fee_minor', 't.currency')} || ' but the schedule says '"
                f" || {money('t.expected_fee_minor', 't.currency')}",
                "json_object('expected_fee_minor', t.expected_fee_minor, 'actual_fee_minor', t.fee_minor)",
                f"marts.fct_processor_txn t WHERE abs(t.fee_delta_minor) > {cfg.fee_tolerance_minor}",
            ),
        )
    )  # fmt: skip
    fx_source = f"""(SELECT k.ledger_id, k.txn_id, k.confidence,
               l.amount_base_minor - (l.amount_minor * r.usd_micro_per_unit + 500000) // 1000000 AS diff,
               l.currency, l.amount_base_minor
            FROM {pair}
            JOIN marts.dim_fx_rate r ON r.rate_date = t.captured_date AND r.currency = t.currency
            WHERE t.currency <> 'USD') q
        JOIN marts.fct_ledger_entry l ON l.ledger_id = q.ledger_id
        JOIN marts.fct_processor_txn t ON t.txn_id = q.txn_id"""
    s.append(
        (
            "findings_fx",
            finding_sql(
                "fx_rounding", BENIGN, "txn", two, "abs(q.diff)", "q.currency", "q.confidence",
                "'Base-currency amount is off by ' || q.diff || ' minor unit(s), within rounding tolerance'",
                "json_object('delta_base_minor', q.diff)",
                fx_source + f" WHERE q.diff <> 0 AND abs(q.diff) <= {cfg.fx_tolerance_minor}",
            )
            + ";"
            + finding_sql(
                "fx_mismatch", ERROR, "txn", two, "abs(q.diff)", "q.currency", "q.confidence",
                "'Base-currency amount is off by ' || q.diff || ' minor unit(s), beyond rounding tolerance'",
                "json_object('delta_base_minor', q.diff)",
                fx_source + f" WHERE abs(q.diff) > {cfg.fx_tolerance_minor}",
            ),
        )
    )  # fmt: skip
    s.append(
        (
            "findings_timing_and_refs",
            finding_sql(
                "cutoff_timing", BENIGN, "txn", two, "0", "t.currency", "k.confidence",
                "'Booked on ' || l.booked_date || ' but captured on ' || t.captured_date"
                " || ' (just after midnight), so the dates differ but it is the same payment'",
                "json_object('days', date_diff('day', t.captured_date, l.booked_date))",
                pair + " WHERE l.booked_date <> t.captured_date",
            )
            + ";"
            + finding_sql(
                "ref_noise", BENIGN, "txn", two, "0", "t.currency", "k.confidence",
                "'Ledger reference ''' || coalesce(l.order_ref_raw, '') || ''' was matched to ''' || "
                "t.order_ref_raw || ''' by ' || k.method || ' matching'",
                "json_object('ledger_ref', l.order_ref_raw, 'processor_ref', t.order_ref_raw, "
                "'method', k.method)",
                pair + " WHERE l.order_ref_raw IS DISTINCT FROM t.order_ref_raw",
            ),
        )
    )  # fmt: skip

    # payouts
    po = "'[' || " + ent("processor_payout", "s.payout_id")
    expected = "s.payout_date + 1"
    s.append(
        (
            "findings_payouts",
            finding_sql(
                "payout_missing", ERROR, "payout", po + " || ']'", "s.net_minor_total", "s.currency", "1.0",
                f"'Payout ' || s.payout_id || ' (' || {money('s.net_minor_total', 's.currency')} || "
                f"') was due on ' || ({expected}) || ' and has not reached the bank'",
                "json_object('expected_value_date', CAST(" + expected + " AS VARCHAR))",
                f"recon.payout_summary s WHERE s.n_lines = 0 AND DATE '{as_of}' > s.payout_date + 1 + {g}",
            )
            + ";"
            + finding_sql(
                "payout_short", ERROR, "payout", f"{po} || ',' || substr(s.bank_entities, 2)",
                "s.net_minor_total - s.bank_total", "s.currency", "coalesce(s.confidence, 1.0)",
                f"'Bank received ' || {money('s.bank_total', 's.currency')} || ' but payout ' || s.payout_id"
                f" || ' was ' || {money('s.net_minor_total', 's.currency')}",
                "json_object('short_by_minor', s.net_minor_total - s.bank_total)",
                "recon.payout_summary s WHERE s.n_lines > 0 AND s.bank_total < s.net_minor_total",
            )
            + ";"
            + finding_sql(
                "payout_over", ERROR, "payout", f"{po} || ',' || substr(s.bank_entities, 2)",
                "s.bank_total - s.net_minor_total", "s.currency", "coalesce(s.confidence, 1.0)",
                f"'Bank received ' || {money('s.bank_total', 's.currency')} || ', more than payout '"
                f" || s.payout_id || ' (' || {money('s.net_minor_total', 's.currency')} || ')'",
                "json_object('over_by_minor', s.bank_total - s.net_minor_total)",
                "recon.payout_summary s WHERE s.bank_total > s.net_minor_total",
            )
            + ";"
            + finding_sql(
                "payout_split", BENIGN, "payout", f"{po} || ',' || substr(s.bank_entities, 2)",
                "0", "s.currency", "coalesce(s.confidence, 1.0)",
                "'Payout ' || s.payout_id || ' arrived as ' || s.n_lines || ' bank lines that add up exactly'",
                "json_object('lines', s.n_lines)",
                "recon.payout_summary s WHERE s.n_lines > 1 AND s.bank_total = s.net_minor_total",
            )
            + ";"
            + finding_sql(
                "payout_late", BENIGN, "payout", f"{po} || ',' || substr(s.bank_entities, 2)",
                "0", "s.currency", "coalesce(s.confidence, 1.0)",
                "'Payout ' || s.payout_id || ' arrived ' || date_diff('day', " + expected
                + ", s.first_value_date) || ' day(s) after the expected date'",
                "json_object('days_late', date_diff('day', " + expected + ", s.first_value_date))",
                "recon.payout_summary s WHERE s.n_lines = 1 AND s.bank_total = s.net_minor_total "
                f"AND s.first_value_date > {expected}",
            ),
        )
    )  # fmt: skip
    s.append(
        (
            "findings_bank_orphans",
            finding_sql(
                "bank_orphan", ERROR, "bank", f"'[' || {ent('bank', 'b.bank_line_id')} || ']'",
                "b.amount_minor", "b.currency", "1.0",
                f"'Bank line ' || b.bank_line_id || ' (' || {money('b.amount_minor', 'b.currency')} || "
                "') does not belong to any payout'",
                "json_object('description', b.description)",
                """marts.fct_bank_line b WHERE NOT EXISTS
                   (SELECT 1 FROM recon.payout_links p WHERE p.bank_line_id = b.bank_line_id)""",
            )
            + ";"
            + finding_sql(
                "bank_ref_missing", BENIGN, "payout",
                f"{po} || ',' || {ent('bank', 'pl.bank_line_id')} || ']'",
                "0", "s.currency", "pl.confidence",
                "'Bank line ' || pl.bank_line_id || ' carried no payout reference and was matched to ' "
                "|| s.payout_id || ' by ' || pl.method || ' matching'",
                "json_object('method', pl.method)",
                "recon.payout_links pl JOIN recon.payout_summary s ON s.payout_id = pl.payout_id "
                "WHERE pl.method <> 'reference'",
            )
            + ";"
            + finding_sql(
                "payout_composition_mismatch", ERROR, "payout", po + " || ']'",
                "abs(p.net_minor_delta)", "p.currency", "1.0",
                "'Payout ' || p.payout_id || ' says ' || p.net_minor_total || ' but its transactions add up to '"
                " || p.net_minor_actual",
                "json_object('delta_minor', p.net_minor_delta)",
                "marts.fct_payout p JOIN recon.payout_summary s ON s.payout_id = p.payout_id "
                "WHERE p.net_minor_delta <> 0",
            ),
        )
    )  # fmt: skip

    s.append(
        (
            "publish",
            f"""
        CREATE OR REPLACE TABLE recon.findings AS
        SELECT finding_id, class, category, level, entities, amount_at_stake_minor, currency,
               round(confidence, 3) AS confidence, reason, detail,
               CASE WHEN category = 'benign' THEN 'explained' ELSE 'open' END AS status
        FROM recon._findings ORDER BY class, finding_id;

        CREATE OR REPLACE TABLE recon.links AS
        SELECT 'ledger_txn' AS link_type, ledger_id AS left_id, txn_id AS right_id, method, confidence
        FROM recon.txn_links
        UNION ALL
        SELECT 'payout_bank', payout_id, bank_line_id, method, confidence FROM recon.payout_links
        ORDER BY 1, 2, 3;

        CREATE OR REPLACE TABLE recon.pending_items AS
        SELECT payout_id, payout_date, net_minor_total, currency,
               payout_date + 1 + {g} AS considered_missing_after
        FROM recon.payout_summary
        WHERE n_lines = 0 AND DATE '{as_of}' <= payout_date + 1 + {g};

        DROP TABLE recon._findings
        """,
        )
    )
    return s


def default_as_of(wh: Warehouse) -> date:
    (d,) = wh.con.execute(
        "SELECT greatest("
        "(SELECT max(value_date) FROM marts.fct_bank_line), "
        "(SELECT max(payout_date) FROM marts.fct_payout), "
        "(SELECT max(booked_date) FROM marts.fct_ledger_entry))"
    ).fetchone()
    return d


def reconcile(wh: Warehouse, cfg: ReconConfig | None = None) -> ReconSummary:
    cfg = cfg or ReconConfig()
    as_of = cfg.as_of or default_as_of(wh)
    wh.con.execute("CREATE SCHEMA IF NOT EXISTS recon")
    summary = ReconSummary(as_of=as_of)
    for name, sql in steps(cfg, as_of):
        t0 = time.perf_counter()
        for statement in [x for x in sql.split(";\n") if x.strip()]:
            wh.con.execute(statement)
        summary.step_seconds[name] = round(time.perf_counter() - t0, 4)

    summary.findings = dict(
        wh.con.execute(
            "SELECT class, count(*) FROM recon.findings GROUP BY 1 ORDER BY 1"
        ).fetchall()
    )
    summary.links = dict(
        wh.con.execute("SELECT link_type, count(*) FROM recon.links GROUP BY 1").fetchall()
    )
    summary.match_methods = dict(
        wh.con.execute("SELECT method, count(*) FROM recon.links GROUP BY 1 ORDER BY 1").fetchall()
    )
    summary.pending_payouts = wh.con.execute("SELECT count(*) FROM recon.pending_items").fetchone()[
        0
    ]
    wh.con.execute(
        "CREATE OR REPLACE TABLE recon.run_info AS SELECT ? AS as_of, ? AS config, ? AS findings",
        [
            str(as_of),
            json.dumps(asdict(cfg), default=str, sort_keys=True),
            json.dumps(summary.findings),
        ],
    )
    return summary
