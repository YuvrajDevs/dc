"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ExceptionDrawer } from "@/components/exception-drawer";
import { Button, Card, CardSkeleton, Chip, EmptyState, ErrorState, PageHeader, statusTone } from "@/components/ui";
import { type ExceptionList, useApi } from "@/lib/api";
import { CLASS_LABELS, day, label, num, usd } from "@/lib/format";

const PAGE = 25;
const STATUSES = [
  { value: "open", text: "Open" },
  { value: "explained", text: "Explained" },
  { value: "resolved", text: "Resolved" },
  { value: "", text: "All" },
];

function ExceptionsInner() {
  const params = useSearchParams();
  const [status, setStatus] = useState("open");
  const [cls, setCls] = useState(params.get("class") ?? "");
  const [merchant, setMerchant] = useState("");
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [min, setMin] = useState("");
  const [sort, setSort] = useState("amount");
  const [page, setPage] = useState(0);
  const [focus, setFocus] = useState<string | null>(params.get("focus"));

  useEffect(() => {
    const t = setTimeout(() => { setDebounced(q.trim()); setPage(0); }, 250);
    return () => clearTimeout(t);
  }, [q]);

  const qs = new URLSearchParams({ sort, limit: String(PAGE), offset: String(page * PAGE) });
  if (status) qs.set("status", status);
  if (cls) qs.set("class", cls);
  if (merchant) qs.set("merchant", merchant);
  if (debounced) qs.set("q", debounced);
  if (min && !Number.isNaN(Number(min))) qs.set("min_amount", min);
  const { data, error, loading, reload } = useApi<ExceptionList>(`/api/exceptions?${qs}`);

  const exportHref = (() => {
    const e = new URLSearchParams();
    if (status) e.set("status", status);
    if (cls) e.set("class", cls);
    if (merchant) e.set("merchant", merchant);
    if (debounced) e.set("q", debounced);
    if (min && !Number.isNaN(Number(min))) e.set("min_amount", min);
    return `/api/exceptions.csv?${e}`;
  })();

  const classes = (data?.facets ?? []).filter((f) => f.category === "error");
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE)) : 1;
  const filtered = Boolean(cls || merchant || debounced || min);

  return (
    <>
      <PageHeader
        title="Exceptions"
        intro="Every disagreement between your ledger, the processor and the bank. Open one to see exactly what was matched, then explain or resolve it."
        actions={<a href={exportHref} download><Button variant="ghost">Export CSV</Button></a>}
      />

      <Card className="mb-4 p-4 sm:p-5">
        <div role="group" aria-label="Status" className="mb-4 flex flex-wrap gap-2">
          {STATUSES.map((s) => (
            <button key={s.text} onClick={() => { setStatus(s.value); setPage(0); }} aria-pressed={status === s.value}
              className={`rounded-full px-4 py-2 text-[13px] font-medium transition ${status === s.value ? "bg-teal text-white" : "bg-page/70 text-ink hover:bg-line"}`}>
              {s.text}
            </button>
          ))}
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <label className="block text-[12px] font-light text-muted lg:col-span-2">Search
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Reason text or exception ID"
              className="mt-1 w-full rounded-2xl bg-page/60 px-4 py-2.5 text-[14px] text-ink ring-1 ring-line" />
          </label>
          <label className="block text-[12px] font-light text-muted">Kind
            <select value={cls} onChange={(e) => { setCls(e.target.value); setPage(0); }} className="mt-1 w-full rounded-2xl bg-page/60 px-3 py-2.5 text-[14px] text-ink ring-1 ring-line">
              <option value="">All kinds</option>
              {classes.map((f) => <option key={f.class} value={f.class}>{CLASS_LABELS[f.class] ?? f.class} ({f.n})</option>)}
            </select>
          </label>
          <label className="block text-[12px] font-light text-muted">Merchant
            <select value={merchant} onChange={(e) => { setMerchant(e.target.value); setPage(0); }} className="mt-1 w-full rounded-2xl bg-page/60 px-3 py-2.5 text-[14px] text-ink ring-1 ring-line">
              <option value="">All merchants</option>
              {(data?.merchants ?? []).map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-[12px] font-light text-muted">Min. USD
              <input inputMode="decimal" value={min} onChange={(e) => { setMin(e.target.value); setPage(0); }} placeholder="0"
                className="mt-1 w-full rounded-2xl bg-page/60 px-3 py-2.5 text-[14px] text-ink ring-1 ring-line" />
            </label>
            <label className="block text-[12px] font-light text-muted">Sort
              <select value={sort} onChange={(e) => setSort(e.target.value)} className="mt-1 w-full rounded-2xl bg-page/60 px-3 py-2.5 text-[14px] text-ink ring-1 ring-line">
                <option value="amount">Amount</option><option value="date">Newest</option><option value="class">Kind</option><option value="status">Status</option>
              </select>
            </label>
          </div>
        </div>
      </Card>

      {error ? <ErrorState message={error} onRetry={reload} /> : loading && !data ? <CardSkeleton lines={6} /> : (
        <Card className="p-2 sm:p-3">
          <p className="px-4 pb-2 pt-3 text-[13px] font-light text-muted" aria-live="polite">
            {data ? `${num(data.total)} ${data.total === 1 ? "exception" : "exceptions"}` : ""}
            {filtered && " match your filters"}
          </p>
          {data && data.items.length === 0 ? (
            <EmptyState
              title={filtered ? "Nothing matches those filters" : status === "open" ? "No open exceptions" : "No exceptions here"}
              hint={filtered ? "Try removing a filter." : "Everything in this view has been dealt with."}
              action={filtered ? <Button variant="ghost" onClick={() => { setCls(""); setMerchant(""); setQ(""); setMin(""); }}>Clear filters</Button> : undefined}
            />
          ) : (
            <ul className="divide-y divide-line" aria-busy={loading}>
              {data?.items.map((e) => (
                <li key={e.finding_id}>
                  <button onClick={() => setFocus(e.finding_id)} className="grid w-full grid-cols-[1fr_auto] items-center gap-x-4 gap-y-1 rounded-2xl px-4 py-3.5 text-left transition hover:bg-lime-soft/50 sm:grid-cols-[170px_1fr_auto_110px]">
                    <span className="flex items-center gap-2 sm:block">
                      <span className="block text-[14px] font-medium">{label(e.class)}</span>
                      <Chip tone={statusTone(e.status)} className="mt-0.5 sm:mt-1">{e.status.replace("_", " ")}</Chip>
                    </span>
                    <span className="order-3 col-span-2 min-w-0 text-[13px] font-light leading-snug text-muted sm:order-none sm:col-span-1">
                      <span className="line-clamp-2">{e.reason}</span>
                    </span>
                    <span className="hidden text-right text-[12px] font-light text-muted sm:block">
                      {e.merchant_id ?? "Bank"}<br />{day(e.occurred_on)}
                    </span>
                    <span className="text-right text-[15px] font-medium tabular-nums">{usd(e.amount_usd, 2)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {data && data.total > PAGE && (
            <nav aria-label="Pages" className="flex items-center justify-between px-4 py-3">
              <Button variant="ghost" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>Previous</Button>
              <span className="text-[13px] text-muted">Page {page + 1} of {pages}</span>
              <Button variant="ghost" disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}>Next</Button>
            </nav>
          )}
        </Card>
      )}

      {focus && <ExceptionDrawer id={focus} onClose={() => setFocus(null)} onChanged={reload} />}
    </>
  );
}

export default function ExceptionsPage() {
  return <Suspense fallback={<CardSkeleton lines={6} />}><ExceptionsInner /></Suspense>;
}
