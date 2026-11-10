"""The card-network side of the synthetic world.

Every payment the processor captured is the end of a card transaction's life: an
authorization request, an issuer decision, clearing with interchange and scheme fees, and
sometimes a refund or a dispute. This module builds that history around the existing
payments, so authorizations join to processor transactions on ``order_ref``.

It also plants a handful of realistic incidents (an issuer outage, a card-testing attack,
interchange downgrades, a merchant whose dispute ratio breaches the monitoring threshold).
They are recorded in the manifest, never loaded, so tests can check that the analytics
surface them, the same way the answer key grades reconciliation.

Everything is deterministic, integer minor units, and drawn from its own random streams so
the reconciliation world is byte-identical with or without this module.

Codes and reason categories follow the public conventions of card networks (ISO 8583-style
response codes, Visa-style dispute reason codes). Rates, issuers and BINs are synthetic.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta

from trueup.synth import world

# ---- reference data ------------------------------------------------------------------------
# Public merchant category codes (ISO 18245). risk = relative dispute propensity.
MCCS: list[tuple[str, str, str, float, float]] = [
    # mcc, description, group, card-not-present share, dispute risk multiplier
    ("5411", "Grocery stores, supermarkets", "everyday", 0.05, 0.4),
    ("5812", "Eating places, restaurants", "everyday", 0.10, 0.5),
    ("5814", "Fast food restaurants", "everyday", 0.15, 0.4),
    ("5732", "Electronics stores", "retail", 0.55, 1.4),
    ("5691", "Men's and women's clothing stores", "retail", 0.60, 1.2),
    ("5999", "Miscellaneous and specialty retail", "retail", 0.50, 1.0),
    ("4121", "Taxicabs and limousines", "travel", 0.85, 0.9),
    ("4722", "Travel agencies and tour operators", "travel", 0.90, 1.6),
    ("7011", "Hotels, motels and resorts", "travel", 0.70, 1.1),
    ("5815", "Digital goods: media", "digital", 1.00, 1.3),
    ("5818", "Digital goods: large merchant", "digital", 1.00, 1.2),
    ("5967", "Direct marketing: inbound teleservices", "high_risk", 1.00, 3.0),
]
COUNTRY_BY_CCY = {"USD": "US", "EUR": "DE", "GBP": "GB", "INR": "IN"}
REGION = {
    "US": "NA",
    "DE": "EU",
    "FR": "EU",
    "NL": "EU",
    "GB": "EU",
    "IN": "AP",
    "SG": "AP",
    "BR": "LA",
}

PRODUCTS = [
    ("debit", 0.45),
    ("credit_classic", 0.30),
    ("credit_premium", 0.18),
    ("commercial", 0.07),
]
NETWORKS = [("visa", 0.68), ("mastercard", 0.32)]
ISSUER_COUNTRIES = [
    ("US", 0.36),
    ("GB", 0.14),
    ("DE", 0.12),
    ("FR", 0.06),
    ("NL", 0.04),
    ("IN", 0.16),
    ("SG", 0.06),
    ("BR", 0.06),
]

# ISO 8583-style response codes. soft = a retry can succeed.
RESPONSE_CODES: dict[str, tuple[str, bool]] = {
    "00": ("Approved", False),
    "05": ("Do not honor", True),
    "51": ("Insufficient funds", True),
    "54": ("Expired card", False),
    "14": ("Invalid card number", False),
    "59": ("Suspected fraud", False),
    "61": ("Exceeds withdrawal limit", True),
    "65": ("Exceeds frequency limit", True),
    "91": ("Issuer or switch unavailable", True),
    "N7": ("CVV2 mismatch", False),
}

# Dispute reasons: category -> (visa code, mastercard code, label, merchant win rate when contested)
DISPUTE_REASONS: dict[str, tuple[str, str, str, float]] = {
    "fraud_cnp": ("10.4", "4837", "Fraud: card-absent environment", 0.22),
    "not_received": ("13.1", "4855", "Merchandise or services not received", 0.48),
    "not_as_described": ("13.3", "4853", "Not as described or defective", 0.41),
    "credit_not_processed": ("13.6", "4860", "Credit not processed", 0.35),
    "duplicate": ("12.6.1", "4834", "Duplicate processing", 0.15),
    "cancelled_recurring": ("13.2", "4841", "Cancelled recurring transaction", 0.30),
}
DISPUTE_FEE_MINOR = 1500  # fee per dispute, in the merchant's minor units (scaled for INR)
RESPONSE_WINDOW_DAYS = 30

# Interchange (bps, fixed minor) by product and channel; regional and MCC adjustments below.
IC_BASE = {
    ("debit", "cp"): (50, 10),
    ("debit", "cnp"): (80, 15),
    ("credit_classic", "cp"): (151, 10),
    ("credit_classic", "cnp"): (180, 10),
    ("credit_premium", "cp"): (195, 10),
    ("credit_premium", "cnp"): (240, 10),
    ("commercial", "cp"): (205, 10),
    ("commercial", "cnp"): (265, 10),
}
EU_CAP_BPS = {"debit": 20, "credit_classic": 30, "credit_premium": 30, "commercial": 150}
CROSS_BORDER_IC_ADD = 70  # bps added for inter-regional transactions
EVERYDAY_IC_DISCOUNT = 25  # bps off for everyday merchant categories (not below the EU cap)
DOWNGRADE_ADD_BPS = 55  # charged on top when a transaction fails to qualify (missing data)
SCHEME_FEE_BPS = {"visa": 13, "mastercard": 14}
CROSS_BORDER_SCHEME_BPS = 60


@dataclass(frozen=True)
class NetworkConfig:
    cards: int = 9000
    decline_attempt_share: float = 0.085  # extra declined attempts per captured payment
    soft_retry_success: float = 0.55  # share of soft declines that retry and succeed
    refund_rate: float = 0.025
    dispute_base_cnp: float = 0.0045
    dispute_base_cp: float = 0.0010
    three_ds_share: float = 0.62  # share of card-not-present payments with 3-D Secure
    # Planted incidents
    outage_issuer: str = ""  # empty = the issuer with the most cards
    outage_day: int = 17  # day index into the window
    outage_hours: tuple[int, int] = (9, 15)
    card_testing_merchant: str = "m10"
    card_testing_day: int = 24
    card_testing_attempts: int = 420
    downgrade_merchant: str = "m05"  # a USD retailer with mostly online sales
    downgrade_share: float = 0.35
    excessive_dispute_merchant: str = "m12"
    excessive_dispute_multiplier: float = 1.0  # m12 is high-risk by category (MCC 5967)
    # Monitoring thresholds (modelled on card-network dispute programmes; counts are scaled to
    # the synthetic volume, real programmes use far larger minimum counts).
    monitor_warning_ratio_bps: int = 65  # 0.65%
    monitor_excessive_ratio_bps: int = 90  # 0.90%
    monitor_min_disputes: int = 10


def _rng(seed: int, stage: str) -> random.Random:
    digest = hashlib.sha256(f"{seed}:network:{stage}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _weighted(rng: random.Random, options: list[tuple[str, float]]) -> str:
    u = rng.random() * sum(w for _, w in options)
    acc = 0.0
    for name, w in options:
        acc += w
        if u < acc:
            return name
    return options[-1][0]


def _bps(amount: int, bps: int) -> int:
    return (amount * bps + 5000) // 10000  # round half up


def build_merchant_profiles(merchants: list[dict]) -> list[dict]:
    rows = []
    for i, m in enumerate(merchants):
        mcc, desc, group, cnp_share, risk = MCCS[i % len(MCCS)]
        country = COUNTRY_BY_CCY[m["currency"]]
        if m["currency"] == "EUR" and i % 3 == 1:
            country = "FR"
        rows.append(
            {
                "merchant_id": m["merchant_id"],
                "mcc": mcc,
                "mcc_description": desc,
                "mcc_group": group,
                "country": country,
                "region": REGION[country],
                "cnp_share_bps": int(cnp_share * 10000),
                "_risk": risk,
            }
        )
    return rows


def build_bins(rng: random.Random) -> list[dict]:
    """Issuers and their BIN ranges. 20 synthetic issuers, a few BINs each."""
    rows = []
    for i in range(1, 21):
        issuer = f"ISS{i:02d}"
        country = _weighted(rng, ISSUER_COUNTRIES)
        for _ in range(rng.randint(2, 4)):
            network = _weighted(rng, NETWORKS)
            first = "4" if network == "visa" else rng.choice(["51", "53", "55", "22"])
            bin_ = (first + "".join(str(rng.randint(0, 9)) for _ in range(6)))[:6]
            rows.append(
                {
                    "bin": bin_,
                    "network": network,
                    "product": _weighted(rng, PRODUCTS),
                    "issuer_id": issuer,
                    "issuer_name": f"Issuer {i:02d} Bank",
                    "issuer_country": country,
                    "issuer_region": REGION[country],
                }
            )
    seen: set[str] = set()
    unique = []
    for r in rows:
        if r["bin"] not in seen:
            seen.add(r["bin"])
            unique.append(r)
    return unique


def interchange_for(
    amount: int,
    product: str,
    channel: str,
    merchant_region: str,
    issuer_region: str,
    mcc_group: str,
) -> tuple[int, int]:
    """Return (rate bps, fee minor) the rate card says this transaction should pay."""
    bps, fixed = IC_BASE[(product, channel)]
    domestic_eu = merchant_region == "EU" and issuer_region == "EU"
    if mcc_group == "everyday":
        bps -= EVERYDAY_IC_DISCOUNT
    if domestic_eu:
        bps = min(bps, EU_CAP_BPS[product])
        fixed = 0
    elif merchant_region != issuer_region:
        bps += CROSS_BORDER_IC_ADD
    bps = max(bps, 0)
    return bps, _bps(amount, bps) + fixed


def interchange_schedule_rows(effective_from: date) -> list[dict]:
    """The published rate card, flattened so analysts can join and audit it in SQL."""
    rows = []
    for (product, channel), (bps, fixed) in sorted(IC_BASE.items()):
        rows.append(
            {
                "product": product,
                "channel": channel,
                "base_bps": bps,
                "fixed_minor": fixed,
                "eu_cap_bps": EU_CAP_BPS[product],
                "cross_border_add_bps": CROSS_BORDER_IC_ADD,
                "everyday_discount_bps": EVERYDAY_IC_DISCOUNT,
                "effective_from": effective_from.isoformat(),
            }
        )
    return rows


def build(
    cfg, ncfg: NetworkConfig, merchants: list[dict], payments: list[dict], processor: list[dict]
) -> dict:
    """Return card-network tables plus the planted incidents. ``payments`` and ``processor``
    are the reconciliation world's rows in the same order (row n is order ord_n)."""
    seed = cfg.seed
    profiles = build_merchant_profiles(merchants)
    prof = {p["merchant_id"]: p for p in profiles}

    # Small test worlds have fewer days and merchants: keep every planted incident inside them.
    ids = [m["merchant_id"] for m in merchants]

    def _merchant(wanted: str, fallback: int) -> str:
        return wanted if wanted in prof else ids[fallback % len(ids)]

    ncfg = replace(
        ncfg,
        outage_day=min(ncfg.outage_day, max(cfg.days - 2, 0)),
        card_testing_day=min(ncfg.card_testing_day, max(cfg.days - 1, 0)),
        card_testing_merchant=_merchant(ncfg.card_testing_merchant, -3),
        downgrade_merchant=_merchant(ncfg.downgrade_merchant, 4),
        excessive_dispute_merchant=_merchant(ncfg.excessive_dispute_merchant, -1),
    )
    bins = build_bins(_rng(seed, "bins"))
    by_bin = {b["bin"]: b for b in bins}

    # Cards: a token, a BIN and an expiry. Cardholders skew to their own region.
    card_rng = _rng(seed, "cards")
    cards = []
    for i in range(1, ncfg.cards + 1):
        b = card_rng.choice(bins)
        cards.append({"card_token": f"card_{i:06d}", "bin": b["bin"]})
    if not ncfg.outage_issuer:
        # The outage hits the issuer with the most expected traffic: cards weighted by how
        # many merchants sit in the card's region (78% of spend is domestic to the region).
        regions = [p["region"] for p in profiles]
        expected: dict[str, float] = {}
        for c in cards:
            b = by_bin[c["bin"]]
            share = regions.count(b["issuer_region"]) / len(regions)
            expected[b["issuer_id"]] = expected.get(b["issuer_id"], 0.0) + 0.22 + 0.78 * share
        ncfg = replace(ncfg, outage_issuer=max(sorted(expected), key=expected.get))
    cards_by_region: dict[str, list[dict]] = {}
    for c in cards:
        cards_by_region.setdefault(by_bin[c["bin"]]["issuer_region"], []).append(c)

    auth_rng = _rng(seed, "auth")
    end = cfg.start + timedelta(days=cfg.days)
    auths: list[dict] = []
    clearing: list[dict] = []
    n_auth = 0

    def new_auth(**row) -> dict:
        nonlocal n_auth
        n_auth += 1
        row = {"auth_id": f"auth_{n_auth:07d}", **row}
        auths.append(row)
        return row

    def pick_card(merchant_region: str) -> dict:
        # 78% of cards used at a merchant come from the merchant's own region.
        if auth_rng.random() < 0.78 and cards_by_region.get(merchant_region):
            return auth_rng.choice(cards_by_region[merchant_region])
        return auth_rng.choice(cards)

    def decline_code(product: str, cnp: bool, cross: bool, risk: float) -> str:
        weights = [
            ("51", 0.30 if product == "debit" else 0.12),
            ("05", 0.25 + (0.15 if cross else 0.0)),
            ("54", 0.06),
            ("14", 0.04),
            ("59", 0.08 * risk + (0.06 if cnp else 0.0)),
            ("61", 0.05 if product == "debit" else 0.02),
            ("N7", 0.08 if cnp else 0.0),
        ]
        return _weighted(auth_rng, [w for w in weights if w[1] > 0])

    def entry_mode(cnp: bool) -> str:
        if cnp:
            return "ecommerce"
        return _weighted(auth_rng, [("contactless", 0.55), ("chip", 0.40), ("magstripe", 0.05)])

    outage_start = datetime.combine(
        cfg.start + timedelta(days=ncfg.outage_day), datetime.min.time()
    )
    outage_window = (
        outage_start + timedelta(hours=ncfg.outage_hours[0]),
        outage_start + timedelta(hours=ncfg.outage_hours[1]),
    )

    # ---- approved payments: one approved authorization each, sometimes after a soft decline
    payment_cards: list[dict] = []
    for n, (p, txn) in enumerate(zip(payments, processor, strict=True), start=1):
        m = prof[p["merchant_id"]]
        cnp = auth_rng.random() < m["cnp_share_bps"] / 10000
        card = pick_card(m["region"])
        b = by_bin[card["bin"]]
        cross = b["issuer_region"] != m["region"]
        three_ds = cnp and auth_rng.random() < ncfg.three_ds_share
        auth_time = p["captured_at"] - timedelta(seconds=auth_rng.randint(2, 900))
        in_outage = (
            b["issuer_id"] == ncfg.outage_issuer
            and outage_window[0] <= auth_time < outage_window[1]
        )
        mode = entry_mode(cnp)
        base = {
            "order_ref": f"ord_{n:07d}",
            "merchant_id": p["merchant_id"],
            "card_token": card["card_token"],
            "bin": card["bin"],
            "currency": p["currency"],
            "amount_minor": p["amount_minor"],
            "entry_mode": mode,
            "card_present": "false" if cnp else "true",
            "three_ds": ("authenticated" if three_ds else "none") if cnp else "n/a",
        }
        retry_of = ""
        # An outage makes the issuer time out; the cardholder retries later and succeeds.
        if in_outage:
            failed = new_auth(
                **base,
                response_code="91",
                approved="false",
                requested_at=auth_time - timedelta(minutes=auth_rng.randint(1, 50)),
                retry_of="",
            )
            retry_of = failed["auth_id"]
            auth_time = outage_window[1] + timedelta(minutes=auth_rng.randint(1, 120))
        elif auth_rng.random() < 0.03:
            code = _weighted(auth_rng, [("51", 0.5), ("05", 0.3), ("61", 0.2)])
            failed = new_auth(
                **base,
                response_code=code,
                approved="false",
                requested_at=auth_time - timedelta(minutes=auth_rng.randint(1, 30)),
                retry_of="",
            )
            retry_of = failed["auth_id"]
        approved = new_auth(
            **base, response_code="00", approved="true", requested_at=auth_time, retry_of=retry_of
        )

        # Clearing: interchange per the rate card, plus planted downgrades at one merchant.
        channel = "cnp" if cnp else "cp"
        ic_bps, ic_fee = interchange_for(
            p["amount_minor"],
            b["product"],
            channel,
            m["region"],
            b["issuer_region"],
            m["mcc_group"],
        )
        downgraded = (
            p["merchant_id"] == ncfg.downgrade_merchant
            and cnp
            and auth_rng.random() < ncfg.downgrade_share
        )
        charged_bps = ic_bps + (DOWNGRADE_ADD_BPS if downgraded else 0)
        charged_fee = ic_fee + (_bps(p["amount_minor"], DOWNGRADE_ADD_BPS) if downgraded else 0)
        scheme = _bps(
            p["amount_minor"],
            SCHEME_FEE_BPS[b["network"]] + (CROSS_BORDER_SCHEME_BPS if cross else 0),
        )
        clearing.append(
            {
                "clearing_id": f"clr_{n:07d}",
                "auth_id": approved["auth_id"],
                "order_ref": base["order_ref"],
                "txn_id": txn["txn_id"],
                "merchant_id": p["merchant_id"],
                "network": b["network"],
                "currency": p["currency"],
                "amount_minor": p["amount_minor"],
                "interchange_bps": charged_bps,
                "interchange_minor": charged_fee,
                "scheme_fee_minor": scheme,
                "qualification": "downgraded" if downgraded else "standard",
                "cleared_at": p["captured_at"] + timedelta(hours=auth_rng.randint(2, 30)),
            }
        )
        payment_cards.append({"cnp": cnp, "three_ds": three_ds, "bin": b, "card": card})

    # ---- declined attempts that never became payments ----------------------------------
    for d in range(cfg.days):
        day = datetime.combine(cfg.start + timedelta(days=d), datetime.min.time())
        for _ in range(int(cfg.txns_per_day * ncfg.decline_attempt_share)):
            m = auth_rng.choice(profiles)
            cnp = auth_rng.random() < m["cnp_share_bps"] / 10000
            card = pick_card(m["region"])
            b = by_bin[card["bin"]]
            cross = b["issuer_region"] != m["region"]
            code = decline_code(b["product"], cnp, cross, m["_risk"])
            when = day + timedelta(seconds=auth_rng.randint(0, 86399))
            if b["issuer_id"] == ncfg.outage_issuer and outage_window[0] <= when < outage_window[1]:
                code = "91"
            ccy = next(x["currency"] for x in merchants if x["merchant_id"] == m["merchant_id"])
            minor = max(100, int(auth_rng.lognormvariate(3.4, 1.0) * 100)) * (
                80 if ccy == "INR" else 1
            )
            new_auth(
                order_ref="",
                merchant_id=m["merchant_id"],
                card_token=card["card_token"],
                bin=card["bin"],
                currency=ccy,
                amount_minor=minor,
                entry_mode=entry_mode(cnp),
                card_present="false" if cnp else "true",
                three_ds=("none" if cnp else "n/a"),
                response_code=code,
                approved="false",
                requested_at=when,
                retry_of="",
            )

    # ---- planted card-testing attack: many tiny CNP attempts on fresh cards in one hour --
    ct = prof[ncfg.card_testing_merchant]
    ct_ccy = next(x["currency"] for x in merchants if x["merchant_id"] == ct["merchant_id"])
    ct_start = datetime.combine(
        cfg.start + timedelta(days=ncfg.card_testing_day), datetime.min.time()
    ) + timedelta(hours=2)
    for i in range(ncfg.card_testing_attempts):
        b = auth_rng.choice(bins)
        code = _weighted(
            auth_rng, [("14", 0.45), ("N7", 0.25), ("54", 0.15), ("59", 0.10), ("00", 0.05)]
        )
        new_auth(
            order_ref="",
            merchant_id=ct["merchant_id"],
            card_token=f"tst_{i:05d}",
            bin=b["bin"],
            currency=ct_ccy,
            amount_minor=auth_rng.choice([100, 100, 150, 200]) * (80 if ct_ccy == "INR" else 1),
            entry_mode="ecommerce",
            card_present="false",
            three_ds="none",
            response_code=code,
            approved="true" if code == "00" else "false",
            requested_at=ct_start + timedelta(seconds=auth_rng.randint(0, 3600)),
            retry_of="",
        )

    auths.sort(key=lambda a: (a["requested_at"], a["auth_id"]))

    # ---- refunds ------------------------------------------------------------------------
    ref_rng = _rng(seed, "refunds")
    refunds = []
    refunded: set[str] = set()
    for n, p in enumerate(payments, start=1):
        if ref_rng.random() < ncfg.refund_rate:
            amount = (
                p["amount_minor"]
                if ref_rng.random() < 0.7
                else max(1, p["amount_minor"] * ref_rng.randint(20, 80) // 100)
            )
            refunds.append(
                {
                    "refund_id": f"rfd_{len(refunds) + 1:06d}",
                    "order_ref": f"ord_{n:07d}",
                    "merchant_id": p["merchant_id"],
                    "currency": p["currency"],
                    "amount_minor": amount,
                    "refunded_at": p["captured_at"]
                    + timedelta(days=ref_rng.randint(1, 20), seconds=ref_rng.randint(0, 86399)),
                }
            )
            refunded.add(f"ord_{n:07d}")

    # ---- disputes -------------------------------------------------------------------------
    dis_rng = _rng(seed, "disputes")
    as_of = end + timedelta(days=45)
    disputes = []
    for n, (p, pc) in enumerate(zip(payments, payment_cards, strict=True), start=1):
        m = prof[p["merchant_id"]]
        rate = (ncfg.dispute_base_cnp if pc["cnp"] else ncfg.dispute_base_cp) * m["_risk"]
        if p["merchant_id"] == ncfg.excessive_dispute_merchant:
            rate *= ncfg.excessive_dispute_multiplier
        order = f"ord_{n:07d}"
        if dis_rng.random() >= rate:
            continue
        options = [
            ("not_received", 0.28),
            ("not_as_described", 0.22),
            ("duplicate", 0.06),
            ("cancelled_recurring", 0.08 if m["mcc_group"] in ("digital", "high_risk") else 0.01),
        ]
        if pc["cnp"]:
            options.append(("fraud_cnp", 0.40))
        if order in refunded:
            options = [("credit_not_processed", 0.2), *options]
        reason = _weighted(dis_rng, options)
        lag = dis_rng.randint(8, 70) if reason == "fraud_cnp" else dis_rng.randint(5, 45)
        opened = p["captured_at"] + timedelta(days=lag, seconds=dis_rng.randint(0, 86399))
        if opened.date() > as_of:
            continue
        visa_code, mc_code, label, win_rate = DISPUTE_REASONS[reason]
        network = pc["bin"]["network"]
        due = opened.date() + timedelta(days=RESPONSE_WINDOW_DAYS)
        liability_shift = reason == "fraud_cnp" and pc["three_ds"]
        # Outcome as of the as-of date.
        if liability_shift:
            status, responded, outcome = "closed", "", "reversed_liability_shift"
        elif due > as_of and dis_rng.random() < 0.5:
            status, responded, outcome = "open", "", "pending"
        elif dis_rng.random() < 0.30:
            status, responded, outcome = "closed", "", "accepted"
        else:
            responded = (
                (opened + timedelta(days=dis_rng.randint(3, RESPONSE_WINDOW_DAYS - 2)))
                .date()
                .isoformat()
            )
            won = dis_rng.random() < win_rate
            status, outcome = "closed", "won" if won else "lost"
        fee = DISPUTE_FEE_MINOR * (80 if p["currency"] == "INR" else 1)
        disputes.append(
            {
                "dispute_id": f"dsp_{len(disputes) + 1:05d}",
                "order_ref": order,
                "merchant_id": p["merchant_id"],
                "network": network,
                "reason_category": reason,
                "reason_code": visa_code if network == "visa" else mc_code,
                "reason_label": label,
                "currency": p["currency"],
                "amount_minor": p["amount_minor"],
                "fee_minor": fee,
                "opened_at": opened,
                "response_due": due.isoformat(),
                "responded_on": responded,
                "status": status,
                "outcome": outcome,
            }
        )

    incidents = [
        {
            "kind": "issuer_outage",
            "issuer_id": ncfg.outage_issuer,
            "date": (cfg.start + timedelta(days=ncfg.outage_day)).isoformat(),
            "hours_utc": list(ncfg.outage_hours),
            "response_code": "91",
        },
        {
            "kind": "card_testing",
            "merchant_id": ncfg.card_testing_merchant,
            "date": (cfg.start + timedelta(days=ncfg.card_testing_day)).isoformat(),
            "attempts": ncfg.card_testing_attempts,
        },
        {
            "kind": "interchange_downgrade",
            "merchant_id": ncfg.downgrade_merchant,
            "added_bps": DOWNGRADE_ADD_BPS,
        },
        {"kind": "excessive_disputes", "merchant_id": ncfg.excessive_dispute_merchant},
    ]

    return {
        "merchant_profiles": profiles,
        "card_bins": bins,
        "authorizations": auths,
        "clearing_records": clearing,
        "refunds": refunds,
        "disputes": disputes,
        "interchange_schedule": interchange_schedule_rows(cfg.start),
        "_incidents": incidents,
        "_as_of": as_of.isoformat(),
        "_monitoring": {
            "warning_ratio_bps": ncfg.monitor_warning_ratio_bps,
            "excessive_ratio_bps": ncfg.monitor_excessive_ratio_bps,
            "min_disputes": ncfg.monitor_min_disputes,
        },
    }


def iso(v: datetime) -> str:
    return world.iso(v)
