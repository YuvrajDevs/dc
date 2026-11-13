"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { Lines } from "@/components/charts";
import { Card, CardTitle, Chip, DarkCard, EmptyState, ErrorState, PageHeader, PanelNote, Skeleton, Stat, cx } from "@/components/ui";
import { type Disputes, useApi } from "@/lib/api";
import { bps, day, month, num, pct, usd } from "@/lib/format";

const STATUS_STYLE = {
  ok: "bg-white/[0.06] text-on-dark-muted",
  warning: "bg-caution text-ink",
  excessive: "bg-alert text-ink",
} as const;

function View() {
  const sp = useSearchParams();
  const router = useRouter();
  const merchant = sp.get("merchant");
  const { data, error, reload } = useApi<Disputes>(`/api/network/disputes${merchant ? `?merchant=${merchant}` : ""}`);
  const all = useApi<Disputes>(merchant ? "/api/network/disputes" : null);
  const grid = (merchant ? all.data : data)?.monitoring ?? [];
  const setMerchant = (m: string | null) => router.replace(m ? `/disputes?merchant=${m}` : "/disputes", { scroll: false });

  if (error) return <ErrorState message={error} onRetry={reload} />;
  const months = [...new Set(grid.map((r) => r.month))].sort();
  const merchants = [...new Set(grid.map((r) => r.merchant_id))].sort();
  const cell = new Map(grid.map((r) => [`${r.merchant_id}|${r.month}`, r]));
  const totals = data?.by_reason.reduce(
    (a, r) => ({ n: a.n + r.disputes, won: a.won + r.won, lost: a.lost + r.lost, loss: a.loss + r.loss_usd, open: a.open + r.open }),
    { n: 0, won: 0, lost: 0, loss: 0, open: 0 },
  );
  const cohorts = [...new Set((data?.cohort ?? []).map((c) => c.cohort_month))].sort();
  const buckets = [...new Set((data?.cohort ?? []).map((c) => c.day_bucket))].sort((a, b) => a - b);

  return (
    <>
      <PageHeader
        title="Disputes"
        intro="Chargebacks by merchant and month against the monitoring thresholds, why they happen, and which ones need a response."
      />
      <div className="mb-6 grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-4 sm:gap-6">
        <Stat label="Disputes" value={totals ? num(totals.n) : "–"} hint={merchant ?? "all merchants"} />
        <Stat label="Win rate" value={totals && totals.won + totals.lost ? (100 * totals.won / (totals.won + totals.lost)).toFixed(0) : "–"} suffix="%" hint="of contested disputes" />
        <Stat label="Lost to disputes" value={totals ? usd(totals.loss) : "–"} hint="amounts plus fees" />
        <Stat label="Awaiting response" value={totals ? num(totals.open) : "–"} hint="before the 30-day deadline" />
      </div>

      <div className="grid gap-4 lg:grid-cols-12">
        <DarkCard className="lg:col-span-8">
          <CardTitle
            dark
            aside={
              merchant ? (
                <button type="button" onClick={() => setMerchant(null)} className="rounded-full bg-accent px-3 py-1 text-body-sm font-semibold text-ink">
                  {merchant} ✕
                </button>
              ) : (
                <span className="text-caption text-on-dark-muted">Click a merchant to filter</span>
              )
            }
          >
            Monthly dispute ratio vs thresholds
          </CardTitle>
          {!grid.length ? (
            <Skeleton className="h-56" />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[420px] border-separate border-spacing-1 text-body-sm">
                <thead>
                  <tr className="text-on-dark-muted">
                    <th scope="col" className="text-left font-medium">Merchant</th>
                    {months.map((m) => (
                      <th key={m} scope="col" className="font-medium">{month(m)}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {merchants.map((m) => (
                    <tr key={m} className={cx(merchant && merchant !== m && "opacity-40")}>
                      <th scope="row" className="pr-2 text-left font-semibold">
                        <button type="button" onClick={() => setMerchant(merchant === m ? null : m)} className="hover:text-accent">
                          {m}
                        </button>
                      </th>
                      {months.map((mo) => {
                        const r = cell.get(`${m}|${mo}`);
                        return (
                          <td key={mo} className={cx("num rounded-lg px-2 py-1.5 text-center font-semibold", r ? STATUS_STYLE[r.programme_status] : "")}
                            title={r ? `${r.disputes} disputes / ${r.cleared_txns} sales` : ""}>
                            {r ? bps(r.dispute_ratio_bps) : "–"}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-3 flex flex-wrap gap-4 text-caption text-on-dark-muted">
                <span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-caution" />warning ≥ 0.65%</span>
                <span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-alert" />excessive ≥ 0.90% and ≥ 10 disputes</span>
                <span>Complete months only. Ratio = disputes opened in the month ÷ sales cleared in it.</span>
              </p>
            </div>
          )}
        </DarkCard>

        <Card className="lg:col-span-4">
          <CardTitle>Needs a response</CardTitle>
          {!data ? (
            <Skeleton className="h-48" />
          ) : data.open.length === 0 ? (
            <EmptyState title="Nothing open" hint="Every dispute has been answered or closed." />
          ) : (
            <ul className="divide-y divide-line">
              {data.open.slice(0, 8).map((d) => (
                <li key={d.dispute_id} className="flex items-center gap-3 py-2.5">
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-body font-semibold">{d.merchant_id} · {d.reason_label}</span>
                    <span className="block text-caption text-muted">{d.network === "visa" ? "Visa" : "Mastercard"} {d.reason_code} · due {day(d.response_due)}</span>
                  </span>
                  <span className="text-right">
                    <span className="num block text-body font-semibold">{usd(d.amount_usd, 2)}</span>
                    <Chip tone={d.deadline_state === "overdue" ? "bad" : d.deadline_state === "due_in_7_days" ? "warn" : "neutral"}>
                      {d.deadline_state === "due_in_7_days" ? "due soon" : d.deadline_state}
                    </Chip>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="lg:col-span-7">
          <CardTitle>Why customers dispute</CardTitle>
          {!data ? (
            <Skeleton className="h-48" />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[520px] text-body">
                <thead>
                  <tr className="text-left text-caption text-muted">
                    <th scope="col" className="py-2 font-medium">Reason</th>
                    <th scope="col" className="py-2 text-right font-medium">Disputes</th>
                    <th scope="col" className="py-2 text-right font-medium">Win rate</th>
                    <th scope="col" className="py-2 text-right font-medium">3DS shift</th>
                    <th scope="col" className="py-2 text-right font-medium">Median days</th>
                    <th scope="col" className="py-2 text-right font-medium">Lost</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {data.by_reason.map((r) => (
                    <tr key={r.category}>
                      <td className="py-2.5 font-medium">{r.label}</td>
                      <td className="num py-2.5 text-right">{num(r.disputes)}</td>
                      <td className="num py-2.5 text-right">{r.won + r.lost ? pct(r.won / (r.won + r.lost), 0) : "–"}</td>
                      <td className="num py-2.5 text-right">{r.liability_shift || "–"}</td>
                      <td className="num py-2.5 text-right">{r.median_days}</td>
                      <td className="num py-2.5 text-right">{usd(r.loss_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-3 text-caption text-muted">
                3DS shift: online fraud disputes on 3-D Secure payments move liability to the issuer, so the merchant does not lose them.
              </p>
            </div>
          )}
        </Card>

        <DarkCard className="lg:col-span-5">
          <CardTitle dark>How long disputes keep arriving</CardTitle>
          {!data ? (
            <Skeleton className="h-40" />
          ) : (
            <Lines
              label="Cumulative dispute rate by days since the sale, per sales month"
              xLabels={buckets.map((b) => `${b}d`)}
              format={(v) => bps(v)}
              series={cohorts.slice(0, 4).map((c) => ({
                name: month(c),
                values: buckets.map((b) => data.cohort.find((x) => x.cohort_month === c && x.day_bucket === b)?.cumulative_dispute_rate_bps ?? 0),
              }))}
            />
          )}
          <p className="mt-3 text-body-sm text-on-dark-muted">
            A month&apos;s sales keep drawing disputes for 60 to 90 days, so a young month always looks cleaner than it is.
          </p>
        </DarkCard>
      </div>
      <PanelNote className="mt-4">Reason codes follow Visa and Mastercard conventions. Thresholds are modelled on network monitoring programmes and scaled to this synthetic volume.</PanelNote>
    </>
  );
}

export default function DisputesPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96" />}>
      <View />
    </Suspense>
  );
}
