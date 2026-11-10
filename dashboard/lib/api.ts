"use client";

import { useCallback, useEffect, useState } from "react";

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { ...init, headers: { "content-type": "application/json", ...init?.headers } });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {}
    throw new ApiError(detail || "Request failed", res.status);
  }
  return res.json() as Promise<T>;
}

export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!path) return;
    const ctrl = new AbortController();
    setLoading(true);
    api<T>(path, { signal: ctrl.signal })
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message ?? "Something went wrong");
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoading(false);
      });
    return () => ctrl.abort();
  }, [path, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}

/* ---- types ---- */
export type Overview = {
  as_of: string | null;
  kpi: { open_errors: number; open_amount_usd: number; resolved: number; explained_errors: number; benign_explained: number };
  flow: { booked_usd: number; received_usd: number; difference_usd: number };
  counts: { ledger_entries: number; transactions: number; payouts: number; bank_lines: number; pending_payouts: number };
  by_class: { class: string; findings: number; amount_usd: number }[];
  trend: { day: string; errors: number; benign: number }[];
  top: { finding_id: string; class: string; merchant_id: string | null; occurred_on: string; amount_usd: number; currency: string; reason: string }[];
  last_run: { run_id: string; status: string; started_at: string } | null;
};

export type ExceptionRow = {
  finding_id: string; class: string; category: string; status: string; merchant_id: string | null;
  occurred_on: string | null; amount_usd: number; currency: string; amount_at_stake_minor: number;
  confidence: number | null; reason: string; note: string | null; updated_by: string | null;
};
export type ExceptionList = {
  total: number; items: ExceptionRow[]; facets: { class: string; category: string; n: number }[]; merchants: string[];
};
export type ExceptionDetail = {
  exception: ExceptionRow & { detail: Record<string, unknown> };
  records: { source: string; id: string; record: Record<string, unknown> | null; links?: Record<string, unknown>[] }[];
  history: { occurred_at?: string; at?: string; actor: string; from: string | null; to: string; note: string }[];
};
export type PayoutRow = {
  payout_id: string; merchant_id: string; currency: string; payout_date: string; net_minor_total: number;
  n_lines: number; bank_total: number; first_value_date: string | null; status: string;
};
export type PayoutList = { total: number; items: PayoutRow[]; facets: { status: string; n: number }[] };
export type ClassScore = { class: string; category: string; support: number; tp: number; fp: number; fn: number; precision: number; recall: number; f1: number };
export type Scorecard = {
  profiles: Record<string, { meta: Record<string, unknown>; summary: Record<string, number>; classes: ClassScore[]; links: Record<string, { precision: number; recall: number; expected: number; found: number }> }>;
  baseline?: { summary: Record<string, number>; links: Record<string, { precision: number; recall: number }> };
  floors?: Record<string, Record<string, number>>;
  scale?: { rows: number; reconcile_s: number; rows_per_second: number; peak_memory_mb: number; precision: number; recall: number }[];
};
export type Runs = {
  runs: { run_id: string; kind: string; status: string; started_at: string; finished_at: string | null; error: string | null; steps: { step: string; status: string; attempt: number; seconds: number }[] }[];
  alerts: { raised_at: string; severity: string; kind: string; message: string }[];
  freshness: { source: string; latest: string | null; lag_days: number | null; allowed_days: number; status: string }[];
  lineage: [string, string][];
};
export type AskResult = {
  question: string; status: "ok" | "refused" | "no_answer" | "error"; source: string; sql: string; explanation: string;
  columns: string[]; rows: (string | number | null)[][]; truncated: boolean; notes: string[]; reason: string; code: string;
  milliseconds: number; examples: string[];
};

/* ---- card network ---- */
export type Insight = { kind: string; severity: "high" | "medium" | "low"; title: string; detail: string; href: string };
export type NetworkSummary = {
  kpi: {
    attempts: number; approvals: number; soft_declines: number; recovered: number; cleared: number;
    volume_usd: number; interchange_usd: number; scheme_usd: number; margin_usd: number; leakage_usd: number;
    disputes: number; disputes_won: number; disputes_lost: number; disputes_open: number; dispute_loss_usd: number;
    approval_rate: number; retry_recovery_rate: number; dispute_rate: number; dispute_win_rate: number;
    effective_interchange_bps: number;
  };
  daily: { day: string; attempts: number; approvals: number; approval_rate_bps: number }[];
  insights: Insight[];
};
export type Approvals = {
  dim: string;
  breakdown: { key: string; label: string; attempts: number; approvals: number; soft_declines: number; hard_declines: number; approval_rate_bps: number; approved_usd: number }[];
  declines: { code: string; label: string; soft: boolean; declines: number; online: number }[];
  daily: { day: string; attempts: number; approval_rate_bps: number }[];
};
export type Disputes = {
  monitoring: { merchant_id: string; month: string; cleared_txns: number; disputes: number; dispute_ratio_bps: number; cohort_dispute_ratio_bps: number; programme_status: "ok" | "warning" | "excessive" }[];
  by_reason: { category: string; label: string; disputes: number; won: number; lost: number; accepted: number; liability_shift: number; open: number; median_days: number; loss_usd: number }[];
  open: { dispute_id: string; merchant_id: string; reason_code: string; reason_label: string; network: string; opened_date: string; response_due: string; deadline_state: string; amount_usd: number }[];
  cohort: { cohort_month: string; day_bucket: number; cumulative_dispute_rate_bps: number }[];
};
export type Fees = {
  by_merchant: { merchant_id: string; category: string; region: string; transactions: number; volume_usd: number; processor_fee_usd: number; interchange_usd: number; scheme_usd: number; margin_usd: number; leakage_usd: number; downgraded: number; effective_ic_bps: number }[];
  by_segment: { product: string; channel: string; cross_border: boolean; transactions: number; overpaid_usd: number; effective_ic_bps: number; rate_card_bps: number }[];
};
