"""Turn a plain-English question into SQL, deterministically.

The planner composes a query from parts (filters, a measure, a grouping) so many phrasings work.
No text from the question is ever pasted into SQL: only values from fixed vocabularies (classes,
statuses), validated ids (merchant m03) and capped integers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CLASS_WORDS: list[tuple[str, str]] = [
    (r"duplicate|booked twice|double[- ]?booked|twice", "duplicate_ledger"),
    (
        r"captured but not booked|missing (in|from) (the )?ledger|not (in|booked in) (the )?ledger|unbooked",
        "missing_in_ledger",
    ),
    (
        r"booked but not captured|missing (in|from) (the )?processor|no processor|not captured",
        "missing_in_processor",
    ),
    (r"amount mismatch|wrong amount|amounts? differ|mismatched amount", "amount_mismatch"),
    (
        r"fee variance|fee overcharge|overcharg|wrong fee|fee (difference|problem|issue)",
        "fee_variance",
    ),
    (
        r"missing payout|payouts? (that )?(are |is |were )?(still )?missing|not (reached|arrived|received).{0,20}bank|missing from the bank|payouts? .{0,20}missing",
        "payout_missing",
    ),
    (
        r"short[- ]?paid|underpaid|payouts? .{0,15}short|short payout|less than (the )?payout",
        "payout_short",
    ),
    (r"late payout|payouts? .{0,15}late|delayed payout|arrived late", "payout_late"),
    (r"split payout|payouts? .{0,15}split|arrived in (two|2|several)", "payout_split"),
    (
        r"orphan|unmatched bank|unknown bank|bank lines? (without|with no) (a )?payout|no payout",
        "bank_orphan",
    ),
    (r"without (a )?reference|missing reference|no reference|bank ref", "bank_ref_missing"),
    (r"rounding", "fx_rounding"),
    (r"midnight|cut[- ]?off", "cutoff_timing"),
    (r"mangled|mistyped|reference noise|typo", "ref_noise"),
]
STATUS_WORDS = [
    (r"\bopen\b|\bunresolved\b", "open"),
    (r"\bresolved\b", "resolved"),
    (r"\bexplained\b", "explained"),
]

CLASS_LABEL = {
    "duplicate_ledger": "duplicate ledger bookings", "missing_in_ledger": "payments missing from the ledger",
    "missing_in_processor": "ledger entries missing from the processor", "amount_mismatch": "amount mismatches",
    "fee_variance": "fee variances", "payout_missing": "missing payouts", "payout_short": "short-paid payouts",
    "payout_late": "late payouts", "payout_split": "split payouts", "bank_orphan": "orphan bank lines",
    "bank_ref_missing": "bank lines without a reference", "fx_rounding": "rounding differences",
    "cutoff_timing": "midnight cut-off differences", "ref_noise": "mangled references",
}  # fmt: skip

BASE = """WITH fx AS (
  SELECT currency, CASE WHEN currency = 'USD' THEN 1000000 ELSE usd_micro_per_unit END AS micro
  FROM marts.dim_fx_rate
  WHERE rate_date = (SELECT max(rate_date) FROM marts.dim_fx_rate)
), f AS (
  SELECT fi.finding_id, fi.class, fi.category, fi.amount_at_stake_minor, fi.currency, fi.reason,
         coalesce(e.status, fi.status) AS status,
         json_extract_string(fi.entities, '$[0].source') AS src,
         json_extract_string(fi.entities, '$[0].id') AS ent_id
  FROM recon.findings fi LEFT JOIN ops.exceptions e ON e.finding_id = fi.finding_id
), fm AS (
  SELECT f.finding_id, f.class, f.category, f.status, f.currency, f.reason,
         coalesce(l.merchant_id, t.merchant_id, p.merchant_id) AS merchant_id,
         coalesce(l.booked_date, t.captured_date, p.payout_date, b.value_date) AS occurred_on,
         f.amount_at_stake_minor * coalesce(x.micro, 1000000) / 100000000.0 AS amount_usd
  FROM f
  LEFT JOIN marts.fct_ledger_entry l ON f.src = 'ledger' AND l.ledger_id = f.ent_id
  LEFT JOIN marts.fct_processor_txn t ON f.src = 'processor' AND t.txn_id = f.ent_id
  LEFT JOIN marts.fct_payout p ON f.src = 'processor_payout' AND p.payout_id = f.ent_id
  LEFT JOIN marts.fct_bank_line b ON f.src = 'bank' AND b.bank_line_id = f.ent_id
  LEFT JOIN fx x ON x.currency = f.currency
)
"""


@dataclass
class Plan:
    sql: str
    explanation: str
    intent: str
    filters: list[str] = field(default_factory=list)


def _int(text: str, default: int = 10) -> int:
    m = re.search(r"\b(?:top|first|biggest|largest|worst)\s+(\d{1,3})\b", text) or re.search(
        r"\b(\d{1,3})\s+(?:largest|biggest|worst|merchants|exceptions|payouts)\b", text
    )
    return min(int(m.group(1)), 100) if m else default


def _merchant(text: str) -> str | None:
    m = re.search(r"\bmerchant\s*#?\s*0*(\d{1,3})\b", text) or re.search(r"\bm0*(\d{1,3})\b", text)
    return f"m{int(m.group(1)):02d}" if m else None


def _days(text: str) -> int | None:
    m = re.search(r"(?:last|past|previous)\s+(\d{1,3})\s+days?", text)
    if m:
        return min(int(m.group(1)), 400)
    if re.search(r"this week|past week|last week", text):
        return 7
    if re.search(r"this month|past month|last month", text):
        return 30
    if re.search(r"yesterday|today", text):
        return 1
    return None


def plan(question: str) -> Plan | None:
    q = " ".join(question.lower().split())
    if not q or len(q) > 400:
        return None

    # -- simple lookups that are not about findings
    if re.search(r"\bpending payouts?\b|not yet due|payouts? (are |is )?(still )?pending", q):
        return Plan(
            "SELECT payout_id, payout_date, net_minor_total, currency, considered_missing_after "
            "FROM recon.pending_items ORDER BY payout_date, payout_id",
            "Payouts that are not yet due, so not yet counted as missing.", "pending_payouts",
        )  # fmt: skip
    m = re.search(r"\b(f_[0-9a-f]{12})\b", q)
    if m:
        return Plan(
            f"SELECT finding_id, class, category, status, amount_at_stake_minor, currency, confidence, reason "
            f"FROM recon.findings WHERE finding_id = '{m.group(1)}'",
            f"Details of finding {m.group(1)}.", "finding_lookup",
        )  # fmt: skip
    about_findings = any(re.search(pattern, q) for pattern, _ in CLASS_WORDS) or re.search(
        r"exception|error|issue|problem|finding|mismatch|discrepanc|alert|at stake|exposure", q
    )
    if not about_findings and re.search(
        r"how many (ledger entries|transactions|payouts|bank lines)", q
    ):
        table = {"ledger entries": "fct_ledger_entry", "transactions": "fct_processor_txn",
                 "payouts": "fct_payout", "bank lines": "fct_bank_line"}[re.search(r"how many (ledger entries|transactions|payouts|bank lines)", q).group(1)]  # fmt: skip
        merch = _merchant(q)
        where = f" WHERE merchant_id = '{merch}'" if merch and table != "fct_bank_line" else ""
        return Plan(
            f"SELECT count(*) AS n FROM marts.{table}{where}",
            f"Row count of {table}.",
            "table_count",
        )
    if re.search(
        r"\blist (all )?merchants\b|\bwhich merchants exist\b|\ball merchants\b", q
    ) and not re.search(r"exception|error|fee|payout", q):
        return Plan("SELECT merchant_id, name, currency, fee_tier FROM marts.dim_merchant ORDER BY merchant_id", "All merchants.", "merchants")  # fmt: skip

    # -- findings: filters
    classes = [c for pattern, c in CLASS_WORDS if re.search(pattern, q)]
    statuses = [s for pattern, s in STATUS_WORDS if re.search(pattern, q)]
    merchant = _merchant(q)
    days = _days(q)
    benign = bool(re.search(r"benign|look-?alike|explained automatically", q))
    errorish = bool(
        re.search(
            r"exception|error|issue|problem|finding|mismatch|discrepanc|alert|at stake|exposure|owed|leak",
            q,
        )
    )
    if not (classes or statuses or errorish or benign):
        return None

    where: list[str] = []
    notes: list[str] = []
    if classes:
        listed = ", ".join(f"'{c}'" for c in dict.fromkeys(classes))
        where.append(f"class IN ({listed})")
        notes.append(" and ".join(CLASS_LABEL[c] for c in dict.fromkeys(classes)))
    elif benign:
        where.append("category = 'benign'")
        notes.append("benign look-alikes")
    else:
        where.append("category = 'error'")
        notes.append("real errors")
    if statuses:
        where.append(f"status = '{statuses[0]}'")
        notes.append(f"status {statuses[0]}")
    if merchant:
        where.append(f"merchant_id = '{merchant}'")
        notes.append(f"merchant {merchant}")
    if days:
        where.append(f"occurred_on > (SELECT max(occurred_on) FROM fm) - {days}")
        notes.append(f"the last {days} day(s) of data")
    clause = " WHERE " + " AND ".join(where)
    n = _int(q)

    # -- findings: shape
    group = None
    if re.search(r"\bby class\b|per class|each class|which classes", q):
        group = "class"
    elif re.search(
        r"by merchant|per merchant|each merchant|which merchants?|top .{0,12}merchants|merchants? (with|having)",
        q,
    ):
        group = "merchant_id"
    elif re.search(r"by status|per status", q):
        group = "status"
    elif re.search(r"by currency|per currency", q):
        group = "currency"
    elif re.search(r"by (day|date)|per day|each day|daily", q):
        group = "occurred_on"

    desc = ", ".join(notes)
    if group == "merchant_id":
        where.append("merchant_id IS NOT NULL")
        clause = " WHERE " + " AND ".join(where)
    if group:
        order = (
            "ORDER BY occurred_on"
            if group == "occurred_on"
            else "ORDER BY round(sum(amount_usd), 2) DESC, findings DESC"
        )
        sql = (f"{BASE}SELECT {group} AS {group}, count(*) AS findings, round(sum(amount_usd), 2) AS amount_usd "
               f"FROM fm{clause} GROUP BY 1 {order} LIMIT {n if group != 'occurred_on' else 400}")  # fmt: skip
        return Plan(
            sql, f"Findings grouped by {group.replace('_', ' ')}: {desc}.", "grouped", where
        )
    if re.search(r"how many|number of|count", q):
        return Plan(
            f"{BASE}SELECT count(*) AS findings FROM fm{clause}",
            f"Number of findings: {desc}.",
            "count",
            where,
        )
    if re.search(r"how much|total|sum|at stake|worth|value|exposure|amount of money", q):
        return Plan(
            f"{BASE}SELECT count(*) AS findings, round(coalesce(sum(amount_usd), 0), 2) AS amount_usd FROM fm{clause}",
            f"Total amount at stake in USD: {desc}.", "sum", where,
        )  # fmt: skip
    order = (
        "amount_usd DESC"
        if re.search(r"largest|biggest|top|worst|most", q)
        else "occurred_on DESC, finding_id"
    )
    return Plan(
        f"{BASE}SELECT finding_id, class, merchant_id, occurred_on, round(amount_usd, 2) AS amount_usd, currency, status, reason "
        f"FROM fm{clause} ORDER BY {order} LIMIT {n if re.search(r'top|largest|biggest|worst|first', q) else 50}",
        f"Findings: {desc}.", "list", where,
    )  # fmt: skip
