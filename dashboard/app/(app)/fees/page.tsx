"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { Card, CardTitle, Chip, DarkCard, ErrorState, PageHeader, PanelNote, Skeleton, Stat, cx } from "@/components/ui";
import { type Fees, useApi } from "@/lib/api";
import { PRODUCT_LABELS, bps, compactUsd, num, usd } from "@/lib/format";

function View() {
  const sp = useSearchParams();
  const router = useRouter();
  const merchant = sp.get("merchant");
  const { data, error, reload } = useApi<Fees>("/api/network/fees");
  if (error) return <ErrorState message={error} onRetry={reload} />;

  const rows = data?.by_merchant ?? [];
  const t = rows.reduce(
    (a, r) => ({
      vol: a.vol + r.volume_usd, fee: a.fee + r.processor_fee_usd, ic: a.ic + r.interchange_usd,
      sch: a.sch + r.scheme_usd, mar: a.mar + r.margin_usd, leak: a.leak + r.leakage_usd,
    }),
    { vol: 0, fee: 0, ic: 0, sch: 0, mar: 0, leak: 0 },
  );
  const focus = (m: string | null) => router.replace(m ? `/fees?merchant=${m}` : "/fees", { scroll: false });

  return (
    <>
      <PageHeader title="Fees" intro="Where every dollar of card fees goes, and where a merchant paid more than the rate card says." />
      <div className="mb-6 grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-4 sm:gap-6">
        <Stat label="Card volume" value={data ? compactUsd(t.vol).replace("$", "") : "–"} unit="$" />
        <Stat label="Effective interchange" value={data ? (100 * t.ic / t.vol).toFixed(2) : "–"} unit="%" hint="paid to issuers" />
        <Stat label="Processor margin" value={data ? compactUsd(t.mar).replace("$", "") : "–"} unit="$" hint={data ? `${(100 * t.mar / t.fee).toFixed(0)}% of fees charged` : ""} />
        <Stat label="Overpaid interchange" value={data ? usd(t.leak).replace("$", "") : "–"} unit="$" hint="above the rate card" />
      </div>

      <div className="grid gap-4 lg:grid-cols-12 lg:items-start">
        <DarkCard className="lg:col-span-7">
          <CardTitle dark>Where the fees go, per merchant</CardTitle>
          {!data ? (
            <Skeleton className="h-64" />
          ) : (
            <>
              <ul className="space-y-2.5">
                {rows.map((r) => {
                  const total = r.processor_fee_usd || 1;
                  const seg = [
                    { v: r.interchange_usd, c: "bg-lime", n: "Interchange" },
                    { v: r.scheme_usd, c: "bg-white", n: "Scheme" },
                    { v: Math.max(0, r.margin_usd), c: "bg-[#6b7d5c]", n: "Margin" },
                  ];
                  return (
                    <li key={r.merchant_id}>
                      <button
                        type="button"
                        onClick={() => focus(merchant === r.merchant_id ? null : r.merchant_id)}
                        className={cx("grid w-full grid-cols-[3rem_1fr_4.5rem] items-center gap-3 rounded-lg py-0.5 text-left hover:bg-white/5", merchant && merchant !== r.merchant_id && "opacity-40")}
                        aria-pressed={merchant === r.merchant_id}
                      >
                        <span className="text-[13px] font-semibold">{r.merchant_id}</span>
                        <span className="flex h-3 overflow-hidden rounded-full bg-white/10" aria-label={seg.map((s) => `${s.n} ${usd(s.v)}`).join(", ")}>
                          {seg.map((s) => (
                            <span key={s.n} className={s.c} style={{ width: `${(100 * s.v) / total}%`, transition: "width 700ms cubic-bezier(.22,1,.36,1)" }} />
                          ))}
                        </span>
                        <span className="num text-right text-[13px]">{bps(r.effective_ic_bps)}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
              <p className="mt-4 flex flex-wrap gap-4 text-[12px] text-on-dark-muted">
                <span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-lime" />Interchange (issuer)</span>
                <span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-white" />Scheme fees (network)</span>
                <span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-[#6b7d5c]" />Processor margin</span>
                <span>Right column: effective interchange rate</span>
              </p>
            </>
          )}
        </DarkCard>

        <Card className="lg:col-span-5">
          <CardTitle>Rate card vs what was charged</CardTitle>
          {!data ? (
            <Skeleton className="h-64" />
          ) : (
            <table className="w-full text-[13px]">
              <thead>
                <tr className="text-left text-[12px] text-muted">
                  <th scope="col" className="py-2 font-medium">Segment</th>
                  <th scope="col" className="py-2 text-right font-medium">Rate card</th>
                  <th scope="col" className="py-2 text-right font-medium">Charged</th>
                  <th scope="col" className="py-2 text-right font-medium">Overpaid</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {data.by_segment
                  .filter((s) => s.transactions > 50)
                  .map((s) => {
                    const over = s.overpaid_usd > 0;
                    return (
                      <tr key={`${s.product}-${s.channel}-${s.cross_border}`}>
                        <td className="py-2">
                          {PRODUCT_LABELS[s.product]} · {s.channel === "cnp" ? "online" : "in person"}
                          {s.cross_border && " · cross-border"}
                        </td>
                        <td className="num py-2 text-right">{bps(s.rate_card_bps)}</td>
                        <td className="num py-2 text-right font-semibold">{bps(s.effective_ic_bps)}</td>
                        <td className={cx("num py-2 text-right", over ? "font-semibold text-bad" : "text-muted")}>{over ? usd(s.overpaid_usd) : "–"}</td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          )}
        </Card>

        <Card className="lg:col-span-12">
          <CardTitle>Merchant economics{merchant ? ` · ${merchant}` : ""}</CardTitle>
          {!data ? (
            <Skeleton className="h-48" />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-[13.5px]">
                <thead>
                  <tr className="text-left text-[12px] text-muted">
                    <th scope="col" className="py-2 font-medium">Merchant</th>
                    <th scope="col" className="py-2 font-medium">Category</th>
                    <th scope="col" className="py-2 text-right font-medium">Volume</th>
                    <th scope="col" className="py-2 text-right font-medium">Fees charged</th>
                    <th scope="col" className="py-2 text-right font-medium">Interchange</th>
                    <th scope="col" className="py-2 text-right font-medium">Scheme</th>
                    <th scope="col" className="py-2 text-right font-medium">Margin</th>
                    <th scope="col" className="py-2 text-right font-medium">Overpaid</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {rows
                    .filter((r) => !merchant || r.merchant_id === merchant)
                    .map((r) => (
                      <tr key={r.merchant_id}>
                        <td className="py-2.5 font-semibold">{r.merchant_id}</td>
                        <td className="py-2.5 text-muted">{r.category} · {r.region}</td>
                        <td className="num py-2.5 text-right">{compactUsd(r.volume_usd)}</td>
                        <td className="num py-2.5 text-right">{usd(r.processor_fee_usd)}</td>
                        <td className="num py-2.5 text-right">{usd(r.interchange_usd)}</td>
                        <td className="num py-2.5 text-right">{usd(r.scheme_usd)}</td>
                        <td className={cx("num py-2.5 text-right", r.margin_usd < 0 && "text-bad")}>{usd(r.margin_usd)}</td>
                        <td className="num py-2.5 text-right">
                          {r.leakage_usd > 0 ? (
                            <Chip tone="bad">{usd(r.leakage_usd)} · {num(r.downgraded)} txns</Chip>
                          ) : (
                            <span className="text-muted">–</span>
                          )}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
      <PanelNote className="mt-4">
        The rate card is re-derived in SQL (regional caps, cross-border add-ons, category discounts); a dbt test proves it reproduces every standard charge exactly, so any difference is real.
      </PanelNote>
    </>
  );
}

export default function FeesPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96" />}>
      <View />
    </Suspense>
  );
}
