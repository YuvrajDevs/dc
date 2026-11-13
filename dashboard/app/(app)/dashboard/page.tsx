"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Bars, niceFloor } from "@/components/charts";
import { ArrowLink, Card, CardTitle, DarkCard, ErrorState, PageHeader, Pills, Skeleton, Stat, cx } from "@/components/ui";
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
const SEVERITY = { high: "bg-alert", medium: "bg-caution", low: "bg-accent" } as const;

export default function DashboardPage() {
  const net = useApi<NetworkSummary>("/api/network/summary");
  const rec = useApi<Overview>("/api/overview");
  const [topic, setTopic] = useState<Topic>("all");
  const [selectedDay, setSelectedDay] = useState<string | null>(null);

  const outageDays = useMemo(() => {
    const s = new Set<string>();
    net.data?.insights.forEach((i) => {
      const m = i.detail.match(/(\d{4}-\d{2}-\d{2})/);
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
      <PageHeader
        title="Card payments"
        intro="What needs a decision today across approvals, disputes, fees and reconciliation. Every finding links to the rows behind it."
      />
      {/* Same KPI row as every other page: four figures with where each comes from */}
      <section className="grid grid-cols-2 gap-x-4 gap-y-6 lg:grid-cols-4 lg:gap-6" aria-label="Key figures">
        {k && rec.data ? (
          <>
            <Stat label="Approval rate" value={(k.approval_rate * 100).toFixed(1)} suffix="%" hint="all traffic" />
            <Stat label="Approved volume" value={compactUsd(k.volume_usd)} hint={`${num(k.cleared)} cleared payments`} />
            <Stat label="Open reconciliation errors" value={compactUsd(rec.data.kpi.open_amount_usd)} hint={`${num(rec.data.kpi.open_errors)} findings to decide`} />
            <Stat label="Dispute ratio" value={(k.dispute_rate * 100).toFixed(2)} suffix="%" hint={`${k.disputes} disputes · ${k.disputes_open} open`} />
          </>
        ) : (
          [0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-24" />)
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
        <Link href="/lab" className="rounded-full bg-accent px-4 py-2 text-body font-semibold text-ink hover:brightness-95">
          Plant an attack in the lab →
        </Link>
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-12">
        {/* What needs attention */}
        <DarkCard className="lg:col-span-8">
          <CardTitle dark aside={<span className="text-caption text-on-dark-muted">{insights.length} found in the data</span>}>
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
                      <span className="block text-lead font-semibold">{i.title}</span>
                      <span className="block text-body leading-snug text-on-dark-muted">{i.detail}</span>
                    </span>
                    <span aria-hidden className="mt-1 text-on-dark-muted transition group-hover:translate-x-0.5 group-hover:text-accent">→</span>
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
                  <dt className="text-body-sm text-on-dark-muted">{a}</dt>
                  <dd className="num mt-1 text-section font-light leading-none">{b}</dd>
                  <dd className="mt-1 text-caption text-on-dark-muted">{c}</dd>
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
                <p className="text-body-sm text-muted">Ledger vs processor vs bank</p>
                <p className="num mt-1 text-stat font-light leading-none">{num(rec.data.kpi.open_errors)}</p>
                <p className="mt-1 text-body-sm text-muted">open errors · {usd(rec.data.kpi.open_amount_usd)} at stake</p>
                <p className="mt-3 rounded-2xl bg-accent-soft px-3 py-2 text-body-sm">
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
                <p className="text-body-sm text-muted">Lost or accepted, plus fees</p>
                <p className="num mt-1 text-stat font-light leading-none">{usd(k.dispute_loss_usd)}</p>
                <p className="mt-1 text-body-sm text-muted">
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
                <p className="text-body-sm text-muted">Interchange paid to issuers</p>
                <p className="num mt-1 text-stat font-light leading-none">{bps(k.effective_interchange_bps)}</p>
                <p className="mt-1 text-body-sm text-muted">
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
              <span className="text-caption text-on-dark-muted">
                <i className="mr-1 inline-block h-2 w-2 rounded-full bg-alert" /> incident day
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
              min={niceFloor(net.data.daily.map((d) => d.approval_rate_bps / 10000))}
              highlight={outageDays}
              selected={selectedDay}
              onSelect={setSelectedDay}
            />
          ) : (
            <Skeleton className="h-40" />
          )}
          {day1 && (
            <p className="rise mt-4 text-body text-on-dark-muted">
              {day(day1.day)}: {num(day1.attempts)} attempts, {num(day1.approvals)} approved.{" "}
              <Link className="font-semibold text-accent hover:underline" href="/approvals?dim=issuer">
                Break down by issuer →
              </Link>
            </p>
          )}
        </DarkCard>
      </div>
    </>
  );
}
