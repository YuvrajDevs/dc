"""The dashboard's API. One long-lived connection, locked down, one cursor per request.

The warehouse file is single-writer: stop the API while the pipeline runs, or point the API at a
copy. There is no authentication in this build; it is meant to run on a trusted network or behind a
proxy that adds it.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import time
from datetime import date
from pathlib import Path
from typing import Literal

import duckdb
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from trueup.api import network as network_api
from trueup.api import queries
from trueup.ask import service as ask_service
from trueup.ask.execute import lock_down
from trueup.ask.provider import SQLProvider, default_provider
from trueup.ops import freshness, lineage
from trueup.recon import queue as xq
from trueup.warehouse import Warehouse

BENCH_DIR = Path(__file__).resolve().parents[3] / "benchmarks"


class StatusUpdate(BaseModel):
    status: Literal["open", "explained", "resolved"]
    note: str = Field(default="", max_length=2000)
    actor: str = Field(min_length=1, max_length=80)


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=400)
    actor: str = Field(default="analyst", max_length=80)


def _rows(cur: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> list[dict]:
    res = cur.execute(sql, params or [])
    cols = [d[0] for d in res.description]
    out = []
    for row in res.fetchall():
        out.append({c: (v.isoformat() if isinstance(v, (date,)) or hasattr(v, "isoformat") else v)
                    for c, v in zip(cols, row, strict=True)})  # fmt: skip
    return out


class _Handle:
    """Lets the queue helpers (which take a Warehouse) work on a cursor."""

    def __init__(self, cur):
        self.con = cur


log = logging.getLogger("trueup.api")


def create_app(
    db_path: str | Path,
    bench_dir: Path | None = None,
    provider: SQLProvider | None = None,
    allow_origins: list[str] | None = None,
) -> FastAPI:
    app = FastAPI(title="TrueUp", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins or ["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["content-type"],
    )

    @app.middleware("http")
    async def access_log(request, call_next):
        # one structured line per request: method, path, status, milliseconds (no query text, no bodies)
        t0 = time.perf_counter()
        response = await call_next(request)
        log.info(
            json.dumps(
                {
                    "event": "request",
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "ms": round((time.perf_counter() - t0) * 1000),
                }
            )
        )
        return response

    bench = bench_dir or BENCH_DIR
    wh = Warehouse(db_path)
    xq.ensure_tables(wh)
    ask_service.ensure_log(wh.con)
    lock_down(wh.con)  # from here on this process can never read or write files through SQL
    llm = provider if provider is not None else default_provider()
    app.state.wh = wh

    def cur():
        return wh.con.cursor()

    @app.get("/api/health")
    def health():
        c = cur()
        n = c.execute("SELECT count(*) FROM ops.exceptions").fetchone()[0]
        return {
            "status": "ok",
            "exceptions": n,
            "assistant": "language model" if llm else "built-in",
        }

    # -- overview ----------------------------------------------------------------------
    @app.get("/api/overview")
    def overview():
        c = cur()
        info = c.execute("SELECT as_of FROM recon.run_info").fetchone()
        as_of = info[0] if info else None
        kpi = _rows(
            c,
            queries.EXCEPTIONS
            + """
            SELECT
              count(*) FILTER (WHERE category = 'error' AND status = 'open') AS open_errors,
              coalesce(sum(amount_usd) FILTER (WHERE category = 'error' AND status = 'open'), 0) AS open_amount_usd,
              count(*) FILTER (WHERE category = 'error' AND status = 'resolved') AS resolved,
              count(*) FILTER (WHERE category = 'error' AND status = 'explained') AS explained_errors,
              count(*) FILTER (WHERE category = 'benign') AS benign_explained
            FROM x""",
        )[0]
        counts = _rows(
            c,
            """SELECT
              (SELECT count(*) FROM marts.fct_ledger_entry) AS ledger_entries,
              (SELECT count(*) FROM marts.fct_processor_txn) AS transactions,
              (SELECT count(*) FROM marts.fct_payout) AS payouts,
              (SELECT count(*) FROM marts.fct_bank_line) AS bank_lines,
              (SELECT count(*) FROM recon.pending_items) AS pending_payouts""",
        )[0]
        flow = _rows(
            c,
            "WITH "
            + queries.FX
            + """
            SELECT
              (SELECT round(sum(l.amount_minor * coalesce(fx.micro, 1000000) / 100000000.0), 2)
                 FROM marts.fct_ledger_entry l LEFT JOIN fx ON fx.currency = l.currency) AS booked_usd,
              (SELECT round(sum(b.amount_minor * coalesce(fx.micro, 1000000) / 100000000.0), 2)
                 FROM marts.fct_bank_line b LEFT JOIN fx ON fx.currency = b.currency) AS received_usd""",
        )[0]
        flow["difference_usd"] = round((flow["booked_usd"] or 0) - (flow["received_usd"] or 0), 2)
        by_class = _rows(
            c,
            queries.EXCEPTIONS
            + """
            SELECT class, count(*) AS findings, round(sum(amount_usd), 2) AS amount_usd
            FROM x WHERE category = 'error' AND status = 'open' GROUP BY 1 ORDER BY 3 DESC""",
        )
        trend = _rows(
            c,
            queries.EXCEPTIONS
            + """
            SELECT occurred_on AS day,
                   count(*) FILTER (WHERE category = 'error') AS errors,
                   count(*) FILTER (WHERE category = 'benign') AS benign
            FROM x WHERE occurred_on IS NOT NULL GROUP BY 1 ORDER BY 1 DESC LIMIT 30""",
        )[::-1]
        top = _rows(
            c,
            queries.EXCEPTIONS
            + """
            SELECT finding_id, class, merchant_id, occurred_on, amount_usd, currency, reason
            FROM x WHERE category = 'error' AND status = 'open' ORDER BY amount_usd DESC LIMIT 5""",
        )
        runs = (
            _rows(
                c,
                "SELECT run_id, status, started_at FROM ops.runs ORDER BY started_at DESC LIMIT 1",
            )
            if _table_exists(c, "ops", "runs")
            else []
        )
        return {"as_of": str(as_of) if as_of else None, "kpi": kpi, "flow": flow, "counts": counts,
                "by_class": by_class, "trend": trend, "top": top, "last_run": runs[0] if runs else None}  # fmt: skip

    # -- exceptions --------------------------------------------------------------------
    def _filters(status, category, cls, merchant, q, min_amount):
        where, params = [], []
        if status:
            where.append("status = ?")
            params.append(status)
        if category:
            where.append("category = ?")
            params.append(category)
        if cls:
            where.append("class = ?")
            params.append(cls)
        if merchant:
            where.append("merchant_id = ?")
            params.append(merchant)
        if q:
            where.append("(lower(reason) LIKE ? OR finding_id = ?)")
            params += [f"%{q.lower()}%", q]
        if min_amount is not None:
            where.append("amount_usd >= ?")
            params.append(min_amount)
        return (" WHERE " + " AND ".join(where)) if where else "", params

    @app.get("/api/exceptions")
    def exceptions(
        status: Literal["open", "explained", "resolved", "auto_cleared"] | None = None,
        category: Literal["error", "benign"] | None = "error",
        cls: str | None = Query(None, alias="class", max_length=40),
        merchant: str | None = Query(None, max_length=10),
        q: str | None = Query(None, max_length=80),
        min_amount: float | None = None,
        sort: Literal["amount", "date", "class", "status"] = "amount",
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ):
        c = cur()
        where, params = _filters(status, category, cls, merchant, q, min_amount)
        total = c.execute(queries.EXCEPTIONS + f"SELECT count(*) FROM x{where}", params).fetchone()[
            0
        ]
        items = _rows(
            c,
            queries.EXCEPTIONS
            + "SELECT finding_id, class, category, status, merchant_id, occurred_on, amount_usd, "
            "currency, amount_at_stake_minor, confidence, reason, note, updated_by "
            f"FROM x{where} ORDER BY {queries.SORTS[sort]} LIMIT ? OFFSET ?",
            [*params, limit, offset],
        )
        facets = _rows(
            c,
            queries.EXCEPTIONS
            + "SELECT class, category, count(*) AS n FROM x GROUP BY 1, 2 ORDER BY 3 DESC",
        )
        merchants = [
            r["merchant_id"]
            for r in _rows(c, "SELECT merchant_id FROM marts.dim_merchant ORDER BY 1")
        ]
        return {"total": total, "items": items, "facets": facets, "merchants": merchants}

    @app.get("/api/exceptions.csv", response_class=PlainTextResponse)
    def exceptions_csv(
        status: str | None = None, category: str | None = "error",
        cls: str | None = Query(None, alias="class"), merchant: str | None = None,
        q: str | None = None, min_amount: float | None = None,
    ):  # fmt: skip
        c = cur()
        where, params = _filters(status, category, cls, merchant, q, min_amount)
        rows = _rows(
            c,
            queries.EXCEPTIONS
            + "SELECT finding_id, class, category, status, merchant_id, occurred_on, amount_usd, "
            f"currency, amount_at_stake_minor, confidence, reason, note, updated_by FROM x{where} "
            "ORDER BY amount_usd DESC LIMIT 20000",
            params,
        )
        buf = io.StringIO()
        fields = list(rows[0]) if rows else ["finding_id"]
        w = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if v is None else v) for k, v in r.items()})
        return PlainTextResponse(
            buf.getvalue(), media_type="text/csv; charset=utf-8",
            headers={"content-disposition": 'attachment; filename="exceptions.csv"'},
        )  # fmt: skip

    @app.get("/api/exceptions/{finding_id}")
    def exception_detail(finding_id: str):
        c = cur()
        base = _rows(c, queries.EXCEPTIONS + "SELECT * FROM x WHERE finding_id = ?", [finding_id])
        if not base:
            raise HTTPException(404, "No such exception")
        item = base[0]
        finding = _rows(
            c, "SELECT entities, detail FROM recon.findings WHERE finding_id = ?", [finding_id]
        )
        entities = json.loads(finding[0]["entities"]) if finding else []
        records = []
        for e in entities:
            spec = queries.ENTITY_TABLES.get(e["source"])
            if not spec:
                continue
            table, key = spec
            row = _rows(c, f"SELECT * FROM {table} WHERE {key} = ?", [e["id"]])
            records.append(
                {"source": e["source"], "id": e["id"], "record": row[0] if row else None}
            )
        for r in records:
            if r["source"] == "processor_payout":
                r["links"] = _rows(
                    c,
                    "SELECT bank_line_id, method, confidence FROM recon.payout_links WHERE payout_id = ?",
                    [r["id"]],
                )
            if r["source"] == "ledger":
                r["links"] = _rows(
                    c,
                    "SELECT txn_id AS linked_id, method, confidence FROM recon.txn_links WHERE ledger_id = ?",
                    [r["id"]],
                )
        item["detail"] = (
            json.loads(finding[0]["detail"]) if finding and finding[0]["detail"] else {}
        )
        return {
            "exception": item,
            "records": records,
            "history": xq.history(_Handle(c), finding_id),
        }

    @app.patch("/api/exceptions/{finding_id}")
    def update_exception(finding_id: str, body: StatusUpdate):
        c = cur()
        try:
            xq.set_status(_Handle(c), finding_id, body.status, body.actor, body.note)
        except KeyError:
            raise HTTPException(404, "No such exception") from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        return {"ok": True, "history": xq.history(_Handle(c), finding_id)}

    # -- payouts -----------------------------------------------------------------------
    @app.get("/api/payouts")
    def payouts(
        status: str | None = Query(None, max_length=30),
        merchant: str | None = Query(None, max_length=10),
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ):
        c = cur()
        where, params = [], []
        if status:
            where.append("status = ?")
            params.append(status)
        if merchant:
            where.append("merchant_id = ?")
            params.append(merchant)
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        total = c.execute(f"SELECT count(*) FROM ({queries.PAYOUTS}) q{clause}", params).fetchone()[
            0
        ]
        items = _rows(
            c,
            f"SELECT * FROM ({queries.PAYOUTS}) q{clause} ORDER BY payout_date DESC, payout_id LIMIT ? OFFSET ?",
            [*params, limit, offset],
        )
        facets = _rows(
            c, f"SELECT status, count(*) AS n FROM ({queries.PAYOUTS}) q GROUP BY 1 ORDER BY 2 DESC"
        )
        return {"total": total, "items": items, "facets": facets}

    # -- scorecard ---------------------------------------------------------------------
    @app.get("/api/scorecard")
    def scorecard():
        out: dict = {"profiles": {}}
        for f in sorted(bench.glob("scorecard-*.json")):
            out["profiles"][f.stem.replace("scorecard-", "")] = json.loads(f.read_text())
        for name, key in (("baseline-v0-naive-tiers.json", "baseline"), ("floors.json", "floors")):
            p = bench / name
            if p.exists():
                out[key] = json.loads(p.read_text())
        scale = bench / "results" / "scale-hard.json"
        if scale.exists():
            out["scale"] = [
                {"rows": r["rows"]["ledger_entries"], "reconcile_s": r["seconds"]["reconcile"],
                 "rows_per_second": r["ledger_rows_per_second"], "peak_memory_mb": r["peak_memory_mb"],
                 "precision": r["scorecard"]["summary"]["error_micro_precision"],
                 "recall": r["scorecard"]["summary"]["error_micro_recall"]}
                for r in json.loads(scale.read_text())
            ]  # fmt: skip
        return out

    # -- runs and health ---------------------------------------------------------------
    @app.get("/api/runs")
    def runs():
        c = cur()
        ledger_rows = (
            _rows(
                c,
                "SELECT run_id, kind, partition_start, partition_end, status, started_at, finished_at, error FROM ops.runs ORDER BY started_at DESC LIMIT 20",
            )
            if _table_exists(c, "ops", "runs")
            else []
        )
        for r in ledger_rows:
            r["steps"] = _rows(
                c,
                "SELECT step, status, attempt, round(seconds, 2) AS seconds FROM ops.run_steps WHERE run_id = ? ORDER BY rowid",
                [r["run_id"]],
            )
        alerts = (
            _rows(
                c,
                "SELECT raised_at, severity, kind, message FROM ops.alerts ORDER BY raised_at DESC LIMIT 30",
            )
            if _table_exists(c, "ops", "alerts")
            else []
        )
        as_of = c.execute("SELECT as_of FROM recon.run_info").fetchone()
        fresh = []
        if as_of:
            d = date.fromisoformat(str(as_of[0]))
            fresh = [
                f.__dict__ | {"latest": str(f.latest) if f.latest else None}
                for f in freshness.check(_Handle(c), d)
            ]
        edges = [list(e) for e in lineage.edges()]
        return {"runs": ledger_rows, "alerts": alerts, "freshness": fresh, "lineage": edges}

    # -- ask ---------------------------------------------------------------------------
    @app.get("/api/ask/examples")
    def examples():
        return {"examples": ask_service.EXAMPLES}

    @app.post("/api/ask")
    def ask(body: Question):
        res = ask_service.ask(cur(), body.question, llm, actor=body.actor)
        return res.__dict__

    network_api.register(app, cur, _rows)

    @app.get("/api/ask/log")
    def ask_log(limit: int = Query(20, ge=1, le=100)):
        return {
            "items": _rows(
                cur(),
                "SELECT asked_at, actor, question, source, status, code, row_count, milliseconds FROM ops.ask_log ORDER BY asked_at DESC LIMIT ?",
                [limit],
            )
        }

    return app


def _table_exists(c, schema: str, name: str) -> bool:
    return bool(c.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = ? AND table_name = ?",
        [schema, name],
    ).fetchone()[0])  # fmt: skip
