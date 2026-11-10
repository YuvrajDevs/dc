"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Bars } from "@/components/charts";
import { ArrowLink, Card, CardTitle, DarkCard, ErrorState, Pills, Ring, Skeleton, Stat, cx } from "@/components/ui";
import { type Insight, type NetworkSummary, type Overview, useApi } from "@/lib/api";
import { bps, compactUsd, day, num, pct, usd } from "@/lib/format";

type Topic = "all" | "approvals" | "disputes" | "fees";
const TOPIC_OF: Record<string, Topic> = {
  issuer_outage: "approvals",
  card_testing: "approvals",
  segment_gap: "approvals",
  excessive_disputes: "disputes",
  interchange_leakage: "fees",
  negative_margin: "fees",
};
const SEVERITY = { high: "bg-[#f08c7a]", medium: "bg-[#e9c46a]", low: "bg-lime" } as const;

export default function DashboardPage() {
  const net = useApi<NetworkSummary>("/api/network/summary");
  const rec = useApi<Overview>("/api/overview");
  const [topic, setTopic] = useState<Topic>("all");
  const [selectedDay, setSelectedDay] = useState<string | null>(null);

  const outageDays = useMemo(() => {
    const s = new Set<string>();
    net.data?.insights.forEach((i) => {
      const m = i.detail.match(/on (\d{4}-\d{2}-\d{2})/);
      if (m && (i.kind === "issuer_outage" || i.kind === "card_testing")) s.add(m[1]);
    });
    return s;
  }, [net.data]);

  if (net.error || rec.error)
    return <ErrorState message={(net.error ?? rec.error)!} onRetry={() => (net.reload(), rec.reload())} />;

  const k = net.data?.kpi;
  const insights = (net.data?.insights ?? []).filter((i) => topic === "all" || TOPIC_OF[i.kind] === topic);
  const day1 = net.data?.daily.find((d) => d.day === selectedDay);

  return (
    <>
      {/* Header row: title, ring, three big numbers */}
      <section className="grid grid-cols-2 items-end gap-x-4 gap-y-6 lg:grid-cols-[1.2fr_auto_1fr_1fr_1fr] lg:gap-6">
        <h1 className="col-span-2 text-[40px] font-semibold leading-[1.02] tracking-tight text-ink sm:text-[52px] lg:col-span-1">
          Card
          <br />
          payments
        </h1>
        {k ? <Ring value={k.approval_rate} label="Approval rate" /> : <Skeleton className="h-24 w-24 rounded-full" />}
        {k && rec.data ? (
          <>
            <Stat label="Approved volume" value={compactUsd(k.volume_usd).replace("$", "")} unit="$" hint={`${num(k.cleared)} cleared payments`} />
            <Stat
              label="Open reconciliation errors"
              value={compactUsd(rec.data.kpi.open_amount_usd).replace("$", "")}
              unit="$"
              hint={`${num(rec.data.kpi.open_errors)} findings to decide`}
            />
            <Stat label="Dispute ratio" value={(k.dispute_rate * 100).toFixed(2)} unit="%" hint={`${k.disputes} disputes · ${k.disputes_open} open`} />
          </>
        ) : (
          [0, 1, 2].map((i) => <Skeleton key={i} className="h-20" />)
        )}
      </section>

      <div className="mt-7 flex flex-wrap items-center justify-between gap-3">
        <Pills<Topic>
          label="Topic"
          value={topic}
          onChange={setTopic}
          options={[
            { value: "all", label: "All" },
            { value: "approvals", label: "Approvals" },
            { value: "disputes", label: "Disputes" },
            { value: "fees", label: "Fees" },
          ]}
        />
        <Link href="/ask" className="rounded-full bg-lime px-4 py-2 text-[14px] font-semibold text-ink hover:brightness-95">
          Ask a question in plain English →
        </Link>
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-12">
        {/* What needs attention */}
        <DarkCard className="lg:col-span-8">
          <CardTitle dark aside={<span className="text-[12px] text-on-dark-muted">{insights.length} found in the data</span>}>
            What needs attention
          </CardTitle>
          {!net.data ? (
            <div className="space-y-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-14" />)}</div>
          ) : (
            <ul className="divide-y divide-white/10">
              {insights.map((i: Insight) => (
                <li key={i.title}>
                  <Link href={i.href} className="group flex items-start gap-3 rounded-xl px-2 py-3 hover:bg-white/5">
                    <span className={cx("mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full", SEVERITY[i.severity])} aria-label={`${i.severity} severity`} />
                    <span className="min-w-0 flex-1">
                      <span className="block text-[15px] font-semibold">{i.title}</span>
                      <span className="block text-[13.5px] leading-snug text-on-dark-muted">{i.detail}</span>
                    </span>
                    <span aria-hidden className="mt-1 text-on-dark-muted transition group-hover:translate-x-0.5 group-hover:text-lime">→</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
          {k && (
            <dl className="mt-5 grid grid-cols-2 gap-4 border-t border-white/10 pt-5 sm:grid-cols-4">
              {[
                ["Soft declines recovered", pct(k.retry_recovery_rate, 0), "by a retry"],
                ["Disputes won", pct(k.dispute_win_rate, 0), "of contested"],
                ["Effective interchange", bps(k.effective_interchange_bps), "of volume"],
                ["Processor margin", compactUsd(k.margin_usd), "after network costs"],
              ].map(([a, b, c]) => (
                <div key={a}>
                  <dt className="text-[12.5px] text-on-dark-muted">{a}</dt>
                  <dd className="num mt-1 text-[28px] font-light leading-none">{b}</dd>
                  <dd className="mt-1 text-[12px] text-on-dark-muted">{c}</dd>
                </div>
              ))}
            </dl>
          )}
        </DarkCard>

        {/* Side cards */}
        <div className="grid content-start gap-4 lg:col-span-4">
          <Card>
            <CardTitle aside={<ArrowLink href="/exceptions">Review</ArrowLink>}>Reconciliation</CardTitle>
            {rec.data ? (
              <>
                <p className="text-[13px] text-muted">Ledger vs processor vs bank</p>
                <p className="num mt-1 text-[40px] font-light leading-none">{num(rec.data.kpi.open_errors)}</p>
                <p className="mt-1 text-[13px] text-muted">open errors · {usd(rec.data.kpi.open_amount_usd)} at stake</p>
                <p className="mt-3 rounded-2xl bg-lime-soft px-3 py-2 text-[12.5px]">
                  {num(rec.data.kpi.benign_explained)} look-alikes explained automatically, not raised.
                </p>
              </>
            ) : (
              <Skeleton className="h-24" />
            )}
          </Card>
          <Card>
            <CardTitle aside={<ArrowLink href="/disputes">Open</ArrowLink>}>Disputes</CardTitle>
            {k ? (
              <>
                <p className="text-[13px] text-muted">Lost or accepted, plus fees</p>
                <p className="num mt-1 text-[40px] font-light leading-none">{usd(k.dispute_loss_usd)}</p>
                <p className="mt-1 text-[13px] text-muted">
                  {k.disputes_won} won · {k.disputes_lost} lost · {k.disputes_open} awaiting a response
                </p>
              </>
            ) : (
              <Skeleton className="h-24" />
            )}
          </Card>
          <Card>
            <CardTitle aside={<ArrowLink href="/fees">Audit</ArrowLink>}>Fees</CardTitle>
            {k ? (
              <>
                <p className="text-[13px] text-muted">Interchange paid to issuers</p>
                <p className="num mt-1 text-[40px] font-light leading-none">{bps(k.effective_interchange_bps)}</p>
                <p className="mt-1 text-[13px] text-muted">
                  of volume · {usd(k.leakage_usd)} charged above the rate card
                </p>
              </>
            ) : (
              <Skeleton className="h-24" />
            )}
          </Card>
        </div>

        {/* Daily approval rate */}
        <DarkCard className="lg:col-span-12">
          <CardTitle
            dark
            aside={
              <span className="text-[12px] text-on-dark-muted">
                <i className="mr-1 inline-block h-2 w-2 rounded-full bg-[#f08c7a]" /> incident day
              </span>
            }
          >
            Approval rate by day
          </CardTitle>
          {net.data ? (
            <Bars
              label="Approval rate by day"
              data={net.data.daily.map((d) => ({ key: d.day, label: day(d.day), value: d.approval_rate_bps / 10000 }))}
              format={(v) => pct(v, 1)}
              min={0.8}
              highlight={outageDays}
              selected={selectedDay}
              onSelect={setSelectedDay}
            />
          ) : (
            <Skeleton className="h-40" />
          )}
          {day1 && (
            <p className="rise mt-4 text-[13.5px] text-on-dark-muted">
              {day(day1.day)}: {num(day1.attempts)} attempts, {num(day1.approvals)} approved.{" "}
              <Link className="font-semibold text-lime hover:underline" href="/approvals?dim=issuer">
                Break down by issuer →
              </Link>
            </p>
          )}
        </DarkCard>
      </div>
    </>
  );
}
