"use client";

import Link from "next/link";
import { DailyBars, Meter } from "@/components/charts";
import { Button, Card, CardSkeleton, CardTitle, Chip, EmptyState, ErrorState, Eyebrow, PageHeader } from "@/components/ui";
import { type Overview, useApi } from "@/lib/api";
import { CLASS_LABELS, day, label, num, usd, when } from "@/lib/format";

export default function OverviewPage() {
  const { data, error, loading, reload } = useApi<Overview>("/api/overview");

  if (error) return <><PageHeader title="Overview" /><ErrorState message={error} onRetry={reload} /></>;
  if (loading || !data)
    return (
      <>
        <PageHeader title="Overview" />
        <div className="grid gap-4 lg:grid-cols-12">
          <div className="lg:col-span-5"><CardSkeleton lines={5} /></div>
          <div className="lg:col-span-7"><CardSkeleton lines={5} /></div>
          <div className="lg:col-span-4"><CardSkeleton /></div>
          <div className="lg:col-span-8"><CardSkeleton /></div>
        </div>
      </>
    );

  const { kpi, counts, by_class, trend, top } = data;
  const totalErrors = kpi.open_errors + kpi.resolved + kpi.explained_errors;
  const cleared = kpi.resolved + kpi.explained_errors;
  const maxClass = Math.max(1, ...by_class.map((c) => c.amount_usd));

  return (
    <>
      <PageHeader
        title="Overview"
        intro={data.as_of ? `Reconciled as of ${day(data.as_of)}. Three sources, one picture: your ledger, the processor and the bank.` : undefined}
        actions={
          <div className="flex gap-2">
            <Link href="/exceptions"><Button variant="lime">Review exceptions</Button></Link>
            <Link href="/ask"><Button>Ask a question</Button></Link>
          </div>
        }
      />

      <div className="grid gap-4 lg:grid-cols-12">
        <Card className="lg:col-span-5">
          <CardTitle>Findings per day</CardTitle>
          {trend.length ? <DailyBars data={trend} /> : <EmptyState title="No findings yet" hint="Run the pipeline to see activity here." />}
        </Card>

        <section aria-labelledby="open-title" className="rounded-[28px] bg-lime p-6 lg:col-span-7">
          <div className="flex items-start justify-between gap-3">
            <div>
              <Eyebrow>Open errors, amount at stake</Eyebrow>
              <h2 id="open-title" className="sr-only">Open exceptions</h2>
              <p className="mt-1 text-[44px] font-medium leading-none tracking-tight text-teal-deep">{usd(kpi.open_amount_usd)}</p>
              <p className="mt-2 text-[13px] text-teal-deep/80">{num(kpi.open_errors)} open exceptions need a decision</p>
            </div>
            <Chip tone="teal">{num(kpi.benign_explained)} look-alikes explained</Chip>
          </div>
          <ul className="mt-5 divide-y divide-teal-deep/10 rounded-2xl bg-white">
            {top.length === 0 && <li><EmptyState title="Nothing open" hint="Every error has been explained or resolved." /></li>}
            {top.map((t) => (
              <li key={t.finding_id}>
                <Link href={`/exceptions?focus=${t.finding_id}`} className="flex items-center gap-3 px-4 py-3 hover:bg-lime-soft/50">
                  <span aria-hidden className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-lime-soft text-[13px] font-semibold text-teal-deep">
                    {label(t.class).slice(0, 1)}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[14px] font-medium">{label(t.class)}</span>
                    <span className="block truncate text-[12px] font-light text-muted">
                      {t.merchant_id ?? "Bank"} · {day(t.occurred_on)}
                    </span>
                  </span>
                  <span className="text-[14px] font-medium tabular-nums">{usd(t.amount_usd, 2)}</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>

        <Card className="lg:col-span-12">
          <CardTitle>Money flow</CardTitle>
          <dl className="grid gap-4 sm:grid-cols-3">
            {[["Expected (booked in the ledger)", data.flow.booked_usd], ["Received (landed at the bank)", data.flow.received_usd], ["Difference", data.flow.difference_usd]].map(([k, v]) => (
              <div key={k as string}>
                <dt className="text-[12px] font-light text-muted">{k}</dt>
                <dd className="text-[26px] font-medium tabular-nums">{usd(v as number)}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-3 text-[12px] font-light text-muted">
            The gap is mostly processor fees; the rest is timing and what the exceptions explain. Everything converted at the latest rate.
          </p>
        </Card>

        <Card className="lg:col-span-4">
          <CardTitle>What we reconciled</CardTitle>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-5">
            {[["Ledger entries", counts.ledger_entries], ["Transactions", counts.transactions], ["Payouts", counts.payouts], ["Bank lines", counts.bank_lines]].map(([k, v]) => (
              <div key={k as string}>
                <dt className="text-[12px] font-light text-muted">{k}</dt>
                <dd className="text-[22px] font-medium tabular-nums">{num(v as number)}</dd>
              </div>
            ))}
          </dl>
          {counts.pending_payouts > 0 && (
            <p className="mt-5 rounded-2xl bg-lime-soft px-4 py-3 text-[13px] text-teal-deep">
              {counts.pending_payouts} payouts are not due yet, so they are not counted as missing.
            </p>
          )}
        </Card>

        <section className="rounded-[28px] bg-teal p-6 text-white lg:col-span-3" aria-label="Progress">
          <p className="text-[13px] font-light text-white/70">Cleared so far</p>
          <p className="mt-2 text-[34px] font-medium leading-none tabular-nums">
            {cleared}<span className="text-white/50"> / {totalErrors}</span>
          </p>
          <p className="mt-1 text-[13px] text-white/70">errors explained or resolved</p>
          <div className="mt-5"><Meter value={cleared} max={totalErrors} tone="lime" /></div>
          <p className="mt-3 text-[12px] text-white/70">{totalErrors ? Math.round((cleared / totalErrors) * 100) : 0}% complete</p>
        </section>

        <Card className="lg:col-span-5">
          <CardTitle aside={<Link href="/exceptions" className="text-[13px] text-teal underline-offset-4 hover:underline">See all</Link>}>
            Open errors by kind
          </CardTitle>
          {by_class.length === 0 ? (
            <EmptyState title="All clear" hint="No open errors." />
          ) : (
            <ul className="space-y-3">
              {by_class.slice(0, 6).map((c) => (
                <li key={c.class}>
                  <Link href={`/exceptions?class=${c.class}`} className="block rounded-xl py-1 hover:bg-line/50">
                    <div className="mb-1 flex items-baseline justify-between text-[13px]">
                      <span className="font-medium">{CLASS_LABELS[c.class] ?? c.class}</span>
                      <span className="tabular-nums text-muted">{num(c.findings)} · {usd(c.amount_usd)}</span>
                    </div>
                    <Meter value={c.amount_usd} max={maxClass} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="lg:col-span-12">
          <CardTitle>Pipeline</CardTitle>
          <div className="flex flex-wrap items-center gap-3 text-[14px]">
            {data.last_run ? (
              <>
                <Chip tone={data.last_run.status === "succeeded" ? "lime" : "bad"}>Last run {data.last_run.status}</Chip>
                <span className="font-light text-muted">{when(data.last_run.started_at)}</span>
              </>
            ) : (
              <span className="font-light text-muted">No pipeline runs recorded yet.</span>
            )}
            <Link href="/runs" className="ml-auto text-teal underline-offset-4 hover:underline">Runs, alerts and freshness</Link>
          </div>
        </Card>
      </div>
    </>
  );
}
