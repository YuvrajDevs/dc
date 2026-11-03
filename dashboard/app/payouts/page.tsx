"use client";

import { useState } from "react";
import { Meter } from "@/components/charts";
import { Button, Card, CardSkeleton, Chip, EmptyState, ErrorState, PageHeader } from "@/components/ui";
import { type PayoutList, useApi } from "@/lib/api";
import { day, label, money, num } from "@/lib/format";

const PAGE = 25;
const tone = (s: string) => (s === "matched" ? "lime" : s === "pending" || s === "payout_late" || s === "payout_split" ? "neutral" : "bad") as "lime" | "neutral" | "bad";
const text = (s: string) => (s === "matched" ? "Matched" : s === "pending" ? "Not due yet" : label(s));

export default function PayoutsPage() {
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(0);
  const qs = new URLSearchParams({ limit: String(PAGE), offset: String(page * PAGE) });
  if (status) qs.set("status", status);
  const { data, error, loading, reload } = useApi<PayoutList>(`/api/payouts?${qs}`);
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE)) : 1;

  return (
    <>
      <PageHeader title="Payouts" intro="Each payout is the sum of many transactions. Here is what the processor said it paid against what the bank received." />
      {error ? <ErrorState message={error} onRetry={reload} /> : (
        <>
          <div role="group" aria-label="Filter by status" className="mb-4 flex flex-wrap gap-2">
            {[{ status: "", n: data?.facets.reduce((a, f) => a + f.n, 0) ?? 0 }, ...(data?.facets ?? [])].map((f) => (
              <button key={f.status || "all"} aria-pressed={status === f.status} onClick={() => { setStatus(f.status); setPage(0); }}
                className={`rounded-full px-4 py-2 text-[13px] font-medium transition ${status === f.status ? "bg-teal text-white" : "bg-card text-ink hover:bg-white/70"}`}>
                {f.status === "" ? "All" : text(f.status)} <span className="font-light opacity-70">({num(f.n)})</span>
              </button>
            ))}
          </div>
          {loading && !data ? <CardSkeleton lines={6} /> : (
            <Card className="p-2 sm:p-3">
              {data && data.items.length === 0 ? <EmptyState title="No payouts here" hint="Try another status." /> : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[640px] text-left text-[13px]">
                    <caption className="sr-only">Payouts with expected and received amounts</caption>
                    <thead>
                      <tr className="text-[12px] font-light text-muted">
                        <th scope="col" className="px-4 py-3 font-light">Payout</th>
                        <th scope="col" className="px-2 py-3 font-light">Merchant</th>
                        <th scope="col" className="px-2 py-3 font-light">Due</th>
                        <th scope="col" className="px-2 py-3 text-right font-light">Expected</th>
                        <th scope="col" className="px-2 py-3 font-light">Received</th>
                        <th scope="col" className="px-4 py-3 font-light">Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line" aria-busy={loading}>
                      {data?.items.map((p) => (
                        <tr key={p.payout_id} className="hover:bg-lime-soft/40">
                          <th scope="row" className="px-4 py-3 font-medium">{p.payout_id}</th>
                          <td className="px-2 py-3">{p.merchant_id}</td>
                          <td className="px-2 py-3">{day(p.payout_date)}</td>
                          <td className="px-2 py-3 text-right tabular-nums">{money(p.net_minor_total, p.currency)}</td>
                          <td className="w-44 px-2 py-3">
                            <div className="mb-1 tabular-nums">{p.n_lines ? money(p.bank_total, p.currency) : "–"}{p.n_lines > 1 && <span className="font-light text-muted"> · {p.n_lines} lines</span>}</div>
                            <Meter value={p.bank_total} max={p.net_minor_total} />
                          </td>
                          <td className="px-4 py-3"><Chip tone={tone(p.status)}>{text(p.status)}</Chip></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
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
        </>
      )}
    </>
  );
}
