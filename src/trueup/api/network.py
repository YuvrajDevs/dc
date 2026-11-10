"""Card-network analytics endpoints: approvals, declines, disputes, fees and the insights
drawn from them. Everything reads the dbt marts; amounts are converted to USD at the latest
FX rate so merchants in different currencies can be compared."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query

FX = """fx AS (
  SELECT currency, CASE WHEN currency = 'USD' THEN 1000000 ELSE usd_micro_per_unit END AS micro
  FROM marts.dim_fx_rate WHERE rate_date = (SELECT max(rate_date) FROM marts.dim_fx_rate)
)"""


def usd(expr: str) -> str:
    """SQL for a minor-unit amount in the row's currency, as USD (joined to ``fx``)."""
    return f"({expr}) * coalesce(fx.micro, 1000000) / 100000000.0"


DIMENSIONS = {
    "issuer": ("issuer_id", "issuer_name"),
    "network": ("network", "network"),
    "product": ("product", "product"),
    "channel": ("channel", "channel"),
    "merchant": ("merchant_id", "merchant_id"),
    "mcc_group": ("mcc_group", "mcc_group"),
    "issuer_region": ("issuer_region", "issuer_region"),
    "cross_border": ("cross_border::varchar", "cross_border::varchar"),
}


def register(app: FastAPI, cur, rows) -> None:
    def has_network(c) -> bool:
        return bool(
            c.execute(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'marts' AND table_name = 'fct_authorization'"
            ).fetchone()[0]
        )

    def need(c):
        if not has_network(c):
            raise HTTPException(404, "This warehouse has no card-network data")

    def where(merchant: str | None, issuer: str | None, alias: str = "") -> tuple[str, list]:
        p = f"{alias}." if alias else ""
        clauses, params = [], []
        if merchant:
            clauses.append(f"{p}merchant_id = ?")
            params.append(merchant)
        if issuer:
            clauses.append(f"{p}issuer_id = ?")
            params.append(issuer)
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", params

    # -- summary + insights -----------------------------------------------------------------
    @app.get("/api/network/summary")
    def summary():
        c = cur()
        need(c)
        kpi = rows(
            c,
            f"""WITH {FX}
            SELECT
              (SELECT count(*) FROM marts.fct_authorization) AS attempts,
              (SELECT count(*) FILTER (WHERE approved) FROM marts.fct_authorization) AS approvals,
              (SELECT count(*) FILTER (WHERE soft_decline) FROM marts.fct_authorization) AS soft_declines,
              (SELECT count(*) FILTER (WHERE recovered_by_retry) FROM marts.fct_authorization) AS recovered,
              (SELECT count(*) FROM marts.fct_clearing) AS cleared,
              (SELECT round(sum({usd("c.amount_minor")}), 2) FROM marts.fct_clearing c LEFT JOIN fx USING (currency)) AS volume_usd,
              (SELECT round(sum({usd("c.interchange_minor")}), 2) FROM marts.fct_clearing c LEFT JOIN fx USING (currency)) AS interchange_usd,
              (SELECT round(sum({usd("c.scheme_fee_minor")}), 2) FROM marts.fct_clearing c LEFT JOIN fx USING (currency)) AS scheme_usd,
              (SELECT round(sum({usd("e.processor_margin_minor")}), 2) FROM marts.mart_fee_economics e LEFT JOIN fx USING (currency)) AS margin_usd,
              (SELECT round(sum({usd("e.interchange_leakage_minor")}), 2) FROM marts.mart_fee_economics e LEFT JOIN fx USING (currency)) AS leakage_usd,
              (SELECT count(*) FROM marts.fct_dispute) AS disputes,
              (SELECT count(*) FILTER (WHERE outcome = 'won') FROM marts.fct_dispute) AS disputes_won,
              (SELECT count(*) FILTER (WHERE outcome = 'lost') FROM marts.fct_dispute) AS disputes_lost,
              (SELECT count(*) FILTER (WHERE status = 'open') FROM marts.fct_dispute) AS disputes_open,
              (SELECT round(sum({usd("d.merchant_loss_minor")}), 2) FROM marts.fct_dispute d LEFT JOIN fx USING (currency)) AS dispute_loss_usd
            """,
        )[0]
        a = kpi["attempts"] or 1
        kpi["approval_rate"] = round(kpi["approvals"] / a, 4)
        kpi["retry_recovery_rate"] = (
            round(kpi["recovered"] / kpi["soft_declines"], 4) if kpi["soft_declines"] else 0
        )
        kpi["dispute_rate"] = round(kpi["disputes"] / kpi["cleared"], 4) if kpi["cleared"] else 0
        decided = kpi["disputes_won"] + kpi["disputes_lost"]
        kpi["dispute_win_rate"] = round(kpi["disputes_won"] / decided, 4) if decided else 0
        kpi["effective_interchange_bps"] = (
            round(10000 * kpi["interchange_usd"] / kpi["volume_usd"]) if kpi["volume_usd"] else 0
        )
        daily = rows(
            c,
            f"""WITH {FX}
            SELECT requested_date AS day, sum(attempts) AS attempts, sum(approvals) AS approvals,
                   round(10000.0 * sum(approvals) / sum(attempts))::bigint AS approval_rate_bps
            FROM marts.mart_auth_daily GROUP BY 1 ORDER BY 1""",
        )
        return {"kpi": kpi, "daily": daily, "insights": insights(c)}

    def insights(c) -> list[dict]:
        out: list[dict] = []
        for r in rows(
            c,
            """SELECT issuer_id, issuer_name, requested_date, attempts, unavailable, approval_rate_bps,
                      strftime(first_unavailable_at, '%H:%M') AS t0, strftime(last_unavailable_at, '%H:%M') AS t1,
                      (SELECT round(10000.0 * sum(approvals) / sum(attempts))::bigint
                         FROM marts.mart_issuer_health b WHERE b.issuer_id = h.issuer_id) AS usual_bps
               FROM marts.mart_issuer_health h WHERE outage_suspected ORDER BY requested_date""",
        ):
            out.append(
                {
                    "kind": "issuer_outage",
                    "severity": "high",
                    "title": f"{r['issuer_name']} stopped answering",
                    "detail": f"{r['unavailable']} 'issuer unavailable' timeouts on {r['requested_date']} between "
                    f"{r['t0']} and {r['t1']} UTC. Approval fell to {r['approval_rate_bps'] / 100:.0f}% "
                    f"(usually {r['usual_bps'] / 100:.0f}%).",
                    "href": f"/approvals?dim=issuer&issuer={r['issuer_id']}",
                }
            )
        for r in rows(
            c,
            """SELECT merchant_id, strftime(hour, '%Y-%m-%d') AS day, strftime(hour, '%H:00') AS h,
                      attempts, distinct_cards, approval_rate_bps, attempts_zscore
               FROM marts.mart_auth_anomalies WHERE flagged ORDER BY hour""",
        ):
            out.append(
                {
                    "kind": "card_testing",
                    "severity": "high",
                    "title": f"Card testing at {r['merchant_id']}",
                    "detail": f"{r['attempts']} small card-not-present attempts on {r['distinct_cards']} cards in the "
                    f"{r['h']} hour of {r['day']} ({r['attempts_zscore']:.0f}σ above normal); "
                    f"only {r['approval_rate_bps'] / 100:.0f}% approved.",
                    "href": f"/approvals?dim=merchant&merchant={r['merchant_id']}",
                }
            )
        for r in rows(
            c,
            f"""WITH {FX}
            SELECT e.merchant_id, sum(e.downgraded_transactions) AS n,
                   round(sum({usd("e.interchange_leakage_minor")}), 2) AS usd
            FROM marts.mart_fee_economics e LEFT JOIN fx USING (currency)
            GROUP BY 1 HAVING sum(e.interchange_leakage_minor) > 0 ORDER BY 3 DESC""",
        ):
            out.append(
                {
                    "kind": "interchange_leakage",
                    "severity": "medium",
                    "title": f"{r['merchant_id']} overpaid interchange",
                    "detail": f"${r['usd']:,.0f} above the rate card on {r['n']} downgraded transactions: "
                    "card-not-present payments that did not qualify for the standard rate.",
                    "href": f"/fees?merchant={r['merchant_id']}",
                }
            )
        for r in rows(
            c,
            """SELECT merchant_id, strftime(month, '%b %Y') AS month, disputes, dispute_ratio_bps
               FROM marts.mart_dispute_monitoring WHERE programme_status = 'excessive'
               QUALIFY row_number() OVER (PARTITION BY merchant_id ORDER BY month DESC) = 1
               ORDER BY dispute_ratio_bps DESC""",
        ):
            out.append(
                {
                    "kind": "excessive_disputes",
                    "severity": "high" if r["dispute_ratio_bps"] >= 120 else "medium",
                    "title": f"{r['merchant_id']} over the dispute threshold",
                    "detail": f"{r['disputes']} disputes in {r['month']}: a {r['dispute_ratio_bps'] / 100:.2f}% ratio "
                    "against a 0.90% monitoring threshold.",
                    "href": f"/disputes?merchant={r['merchant_id']}",
                }
            )
        for r in rows(
            c,
            f"""WITH {FX}
            SELECT e.merchant_id, any_value(p.mcc_description) AS category,
                   round(sum({usd("e.processor_margin_minor")}), 2) AS margin_usd,
                   round(10000.0 * sum(e.interchange_minor) / sum(e.volume_minor))::bigint AS ic_bps
            FROM marts.mart_fee_economics e LEFT JOIN fx USING (currency)
            LEFT JOIN staging.stg_merchant_profiles p ON p.merchant_id = e.merchant_id
            GROUP BY 1 HAVING sum(e.processor_margin_minor) < 0 ORDER BY 3""",
        ):
            out.append(
                {
                    "kind": "negative_margin",
                    "severity": "medium",
                    "title": f"Losing money on {r['merchant_id']}",
                    "detail": f"Fees charged do not cover network costs: ${-r['margin_usd']:,.0f} lost. "
                    f"Interchange runs at {r['ic_bps'] / 100:.2f}% for this {r['category'].lower()} merchant, "
                    "so its pricing tier needs a review.",
                    "href": f"/fees?merchant={r['merchant_id']}",
                }
            )
        seg = rows(
            c,
            """SELECT channel, cross_border, round(10000.0 * sum(approvals) / sum(attempts))::bigint AS bps
               FROM marts.mart_auth_daily GROUP BY 1, 2 ORDER BY bps""",
        )
        if len(seg) >= 2:
            worst, best = seg[0], seg[-1]
            out.append(
                {
                    "kind": "segment_gap",
                    "severity": "low",
                    "title": "Cross-border online payments approve least",
                    "detail": f"{'Online' if worst['channel'] == 'cnp' else 'In-person'}"
                    f"{', cross-border' if worst['cross_border'] else ''} approves at {worst['bps'] / 100:.1f}% "
                    f"against {best['bps'] / 100:.1f}% for the best segment.",
                    "href": "/approvals?dim=cross_border",
                }
            )
        return out

    # -- approvals ----------------------------------------------------------------------
    @app.get("/api/network/approvals")
    def approvals(
        dim: str = Query("issuer"),
        merchant: str | None = Query(None, max_length=20),
        issuer: str | None = Query(None, max_length=20),
    ):
        c = cur()
        need(c)
        if dim not in DIMENSIONS:
            raise HTTPException(400, f"dim must be one of {', '.join(DIMENSIONS)}")
        key, label = DIMENSIONS[dim]
        w, params = where(merchant, issuer)
        breakdown = rows(
            c,
            f"""WITH {FX}
            SELECT {key} AS key, any_value({label}) AS label, count(*) AS attempts,
                   count(*) FILTER (WHERE approved) AS approvals,
                   count(*) FILTER (WHERE soft_decline) AS soft_declines,
                   count(*) FILTER (WHERE hard_decline) AS hard_declines,
                   round(10000.0 * count(*) FILTER (WHERE approved) / count(*))::bigint AS approval_rate_bps,
                   round(sum({usd("a.amount_minor")}) FILTER (WHERE approved), 2) AS approved_usd
            FROM marts.fct_authorization a LEFT JOIN fx USING (currency){w}
            GROUP BY 1 ORDER BY attempts DESC""",
            params,
        )
        declines = rows(
            c,
            f"""SELECT response_code AS code, any_value(response_label) AS label, any_value(soft_decline) AS soft,
                       count(*) AS declines,
                       count(*) FILTER (WHERE channel = 'cnp') AS online
            FROM marts.fct_authorization{w}{" AND" if w else " WHERE"} NOT approved
            GROUP BY 1 ORDER BY declines DESC""",
            params,
        )
        daily = rows(
            c,
            f"""SELECT requested_date AS day, count(*) AS attempts,
                   round(10000.0 * count(*) FILTER (WHERE approved) / count(*))::bigint AS approval_rate_bps
            FROM marts.fct_authorization{w} GROUP BY 1 ORDER BY 1""",
            params,
        )
        return {"dim": dim, "breakdown": breakdown, "declines": declines, "daily": daily}

    # -- disputes ------------------------------------------------------------------------
    @app.get("/api/network/disputes")
    def disputes(merchant: str | None = Query(None, max_length=20)):
        c = cur()
        need(c)
        w, params = where(merchant, None)
        monitoring = rows(
            c,
            f"""SELECT merchant_id, month, cleared_txns, disputes, dispute_ratio_bps,
                       cohort_dispute_ratio_bps, programme_status
            FROM marts.mart_dispute_monitoring{w} ORDER BY merchant_id, month""",
            params,
        )
        by_reason = rows(
            c,
            f"""WITH {FX}
            SELECT reason_category AS category, any_value(reason_label) AS label, count(*) AS disputes,
                   count(*) FILTER (WHERE outcome = 'won') AS won,
                   count(*) FILTER (WHERE outcome = 'lost') AS lost,
                   count(*) FILTER (WHERE outcome = 'accepted') AS accepted,
                   count(*) FILTER (WHERE outcome = 'reversed_liability_shift') AS liability_shift,
                   count(*) FILTER (WHERE status = 'open') AS open,
                   round(median(days_to_dispute)) AS median_days,
                   round(sum({usd("d.merchant_loss_minor")}), 2) AS loss_usd
            FROM marts.fct_dispute d LEFT JOIN fx USING (currency){w}
            GROUP BY 1 ORDER BY disputes DESC""",
            params,
        )
        open_items = rows(
            c,
            f"""WITH {FX}
            SELECT dispute_id, merchant_id, reason_code, reason_label, network, opened_date,
                   response_due, deadline_state, round({usd("d.amount_minor")}, 2) AS amount_usd
            FROM marts.fct_dispute d LEFT JOIN fx USING (currency)
            {w}{" AND" if w else " WHERE"} status = 'open' ORDER BY response_due LIMIT 50""",
            params,
        )
        cohort = rows(
            c,
            "SELECT cohort_month, day_bucket, cumulative_dispute_rate_bps FROM marts.mart_dispute_cohort "
            "ORDER BY cohort_month, day_bucket",
        )
        return {
            "monitoring": monitoring,
            "by_reason": by_reason,
            "open": open_items,
            "cohort": cohort,
        }

    # -- fees ----------------------------------------------------------------------------
    @app.get("/api/network/fees")
    def fees(merchant: str | None = Query(None, max_length=20)):
        c = cur()
        need(c)
        w, params = where(merchant, None, "e")
        by_merchant = rows(
            c,
            f"""WITH {FX}
            SELECT e.merchant_id, any_value(p.mcc_description) AS category, any_value(p.region) AS region,
                   sum(e.transactions) AS transactions,
                   round(sum({usd("e.volume_minor")}), 2) AS volume_usd,
                   round(sum({usd("e.processor_fee_minor")}), 2) AS processor_fee_usd,
                   round(sum({usd("e.interchange_minor")}), 2) AS interchange_usd,
                   round(sum({usd("e.scheme_fee_minor")}), 2) AS scheme_usd,
                   round(sum({usd("e.processor_margin_minor")}), 2) AS margin_usd,
                   round(sum({usd("e.interchange_leakage_minor")}), 2) AS leakage_usd,
                   sum(e.downgraded_transactions) AS downgraded,
                   round(10000.0 * sum(e.interchange_minor) / sum(e.volume_minor))::bigint AS effective_ic_bps
            FROM marts.mart_fee_economics e LEFT JOIN fx USING (currency)
            LEFT JOIN staging.stg_merchant_profiles p ON p.merchant_id = e.merchant_id{w}
            GROUP BY 1 ORDER BY volume_usd DESC""",
            params,
        )
        by_segment = rows(
            c,
            f"""WITH {FX}
            SELECT product, channel, cross_border, count(*) AS transactions,
                   round(sum({usd("greatest(interchange_overcharge_minor, 0)")}), 2) AS overpaid_usd,
                   round(10000.0 * sum(interchange_minor) / sum(amount_minor))::bigint AS effective_ic_bps,
                   round(10000.0 * sum(expected_interchange_minor) / sum(amount_minor))::bigint AS rate_card_bps
            FROM marts.fct_clearing LEFT JOIN fx USING (currency){w.replace("e.", "")}
            GROUP BY 1, 2, 3 ORDER BY 1, 2, 3""",
            params,
        )
        return {"by_merchant": by_merchant, "by_segment": by_segment}

    # -- reference --------------------------------------------------------------------------
    @app.get("/api/network/merchants")
    def merchants():
        c = cur()
        need(c)
        return {
            "items": rows(
                c,
                "SELECT merchant_id, mcc, mcc_description, mcc_group, country, region "
                "FROM staging.stg_merchant_profiles ORDER BY merchant_id",
            )
        }
