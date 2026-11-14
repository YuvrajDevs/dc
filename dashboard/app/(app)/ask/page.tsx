"use client";

import { useEffect, useRef, useState } from "react";
import { Button, Card, CardTitle, Chip, EmptyState, ErrorState, PageHeader, cx } from "@/components/ui";
import { type AskResult, api, useApi } from "@/lib/api";

const FALLBACK = ["Which payouts are missing from the bank?", "How many open exceptions are there?", "Show the 10 largest fee variances"];

export default function AskPage() {
  const { data: ex } = useApi<{ examples: string[] }>("/api/ask/examples");
  const [q, setQ] = useState("");
  const [res, setRes] = useState<AskResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const out = useRef<HTMLDivElement>(null);

  useEffect(() => { if (res) out.current?.focus(); }, [res]);

  async function submit(question: string) {
    const text = question.trim();
    if (!text) return;
    setBusy(true); setErr(null); setCopied(false);
    try {
      setRes(await api<AskResult>("/api/ask", { method: "POST", body: JSON.stringify({ question: text, actor: localStorage.getItem("trueup.actor") || "analyst" }) }));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not reach the assistant.");
    } finally { setBusy(false); }
  }

  return (
    <>
      <PageHeader title="Ask" intro="Ask about your reconciliation in plain English. Every answer shows the exact query that produced it, and every query is checked to be read-only before it runs." />
      <Card>
        <form onSubmit={(e) => { e.preventDefault(); submit(q); }} className="flex flex-col gap-3 sm:flex-row">
          <label className="sr-only" htmlFor="question">Your question</label>
          <input id="question" value={q} onChange={(e) => setQ(e.target.value)} maxLength={400} autoComplete="off"
            placeholder="e.g. Which merchants have the most exceptions?"
            className="flex-1 rounded-2xl bg-white px-5 py-3.5 text-lead ring-1 ring-line" />
          <Button type="submit" variant="accent" disabled={busy || !q.trim()}>{busy ? "Thinking…" : "Ask"}</Button>
        </form>
        <div className="mt-4 flex flex-wrap gap-2" aria-label="Example questions">
          {(ex?.examples ?? FALLBACK).map((s) => (
            <button key={s} onClick={() => { setQ(s); submit(s); }} className="rounded-full bg-white px-4 py-2 text-body-sm ring-1 ring-ink/10 hover:bg-accent-soft">{s}</button>
          ))}
        </div>
      </Card>

      <div ref={out} tabIndex={-1} aria-live="polite" className="mt-4 outline-none">
        {err && <ErrorState message={err} />}
        {res && res.status === "ok" && (
          <Card>
            <CardTitle aside={<Chip tone="accent">{res.source === "llm" ? "Language model, checked" : "Built-in"} · {res.milliseconds} ms</Chip>}>{res.question}</CardTitle>
            {res.explanation && <p className="mb-4 text-body font-light text-muted">{res.explanation}</p>}
            {res.rows.length === 0 ? <EmptyState title="No rows" hint="The query ran and found nothing." /> : (
              <div className="overflow-x-auto rounded-2xl ring-1 ring-line">
                <table className="w-full text-left text-body-sm">
                  <caption className="sr-only">Answer</caption>
                  <thead className="bg-white"><tr>{res.columns.map((c) => <th key={c} scope="col" className={cx("px-4 py-2.5 font-medium", isNumeric(res.rows, res.columns.indexOf(c)) && "text-right")}>{columnLabel(c)}</th>)}</tr></thead>
                  <tbody className="divide-y divide-line">
                    {res.rows.map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j} className={cx("max-w-[420px] px-4 py-2.5 align-top tabular-nums", typeof v === "number" && "text-right")}>{formatCell(res.columns[j], v)}</td>)}</tr>)}
                  </tbody>
                </table>
              </div>
            )}
            {res.notes.map((n) => <p key={n} className="mt-3 text-caption text-muted">{n}</p>)}
            <details className="mt-4 rounded-2xl bg-white p-4">
              <summary className="cursor-pointer text-body-sm font-medium">Show the query that ran</summary>
              <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap text-caption leading-relaxed">{res.sql}</pre>
              <Button variant="ghost" className="mt-3 !py-1.5 !text-caption" onClick={() => { navigator.clipboard?.writeText(res.sql); setCopied(true); }}>{copied ? "Copied" : "Copy query"}</Button>
            </details>
          </Card>
        )}
        {res && res.status === "refused" && (
          <Card className="bg-warn-soft"><h2 className="text-lead font-medium text-warn">I can’t run that</h2><p className="mt-1 text-body">{res.reason}</p></Card>
        )}
        {res && res.status === "no_answer" && (
          <Card><h2 className="text-lead font-medium">I don’t know how to answer that yet</h2>
            <p className="mt-1 text-body font-light text-muted">Try one of these:</p>
            <div className="mt-3 flex flex-wrap gap-2">{res.examples.map((s) => <button key={s} onClick={() => { setQ(s); submit(s); }} className="rounded-full bg-white px-4 py-2 text-body-sm ring-1 ring-ink/10 hover:bg-accent-soft">{s}</button>)}</div>
          </Card>
        )}
        {res && res.status === "error" && <ErrorState message={res.reason} />}
      </div>
    </>
  );
}

/** Column names from SQL ("amount_usd") read as labels ("Amount (USD)"). */
function columnLabel(c: string): string {
  const words = c.replace(/_usd$/, "").replaceAll("_", " ").replace(/\bid\b/, "ID");
  const label = words.charAt(0).toUpperCase() + words.slice(1);
  return c.endsWith("_usd") ? `${label} (USD)` : label;
}

/** Money as money, counts with separators, everything else as given. */
function formatCell(column: string, v: unknown): string {
  if (v === null || v === undefined) return "–";
  if (typeof v === "number") {
    if (/(_usd|amount|cost|fee)/.test(column)) return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(v);
    return new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 }).format(v);
  }
  return String(v);
}

const isNumeric = (rows: unknown[][], j: number) => rows.length > 0 && typeof rows[0][j] === "number";
