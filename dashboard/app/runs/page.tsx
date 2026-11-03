"use client";

import { Card, CardSkeleton, CardTitle, Chip, EmptyState, ErrorState, PageHeader } from "@/components/ui";
import { type Runs, useApi } from "@/lib/api";
import { day, when } from "@/lib/format";

const sev = (s: string) => (s === "critical" ? "bad" : s === "warning" ? "warn" : "neutral") as "bad" | "warn" | "neutral";
const layer = (t: string) => t.split(".")[0];
const LAYERS = ["raw", "staging", "marts", "recon", "ops"];

export default function RunsPage() {
  const { data, error, loading, reload } = useApi<Runs>("/api/runs");
  if (error) return <><PageHeader title="Runs" /><ErrorState message={error} onRetry={reload} /></>;
  if (loading || !data) return <><PageHeader title="Runs" /><CardSkeleton lines={5} /></>;

  const byLayer = LAYERS.map((l) => ({ l, edges: data.lineage.filter(([, c]) => layer(c) === l) }));

  return (
    <>
      <PageHeader title="Runs" intro="Is the data fresh, did the last run work, and where does each table come from?" />
      <div className="grid gap-4 lg:grid-cols-12">
        <Card className="lg:col-span-5">
          <CardTitle>Freshness</CardTitle>
          {data.freshness.length === 0 ? <EmptyState title="No data yet" /> : (
            <ul className="space-y-3">
              {data.freshness.map((f) => (
                <li key={f.source} className="flex items-center justify-between gap-3 text-[14px]">
                  <span><span className="block font-medium">{f.source.replaceAll("_", " ")}</span><span className="text-[12px] font-light text-muted">latest {day(f.latest)}{f.lag_days !== null && ` · ${f.lag_days} day(s) behind`}</span></span>
                  <Chip tone={f.status === "ok" ? "lime" : "bad"}>{f.status === "ok" ? "Fresh" : f.status}</Chip>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="lg:col-span-7">
          <CardTitle>Alerts</CardTitle>
          {data.alerts.length === 0 ? <EmptyState title="No alerts" hint="Nothing has gone wrong." /> : (
            <ul className="divide-y divide-line">
              {data.alerts.slice(0, 8).map((a, i) => (
                <li key={i} className="flex items-start gap-3 py-3 text-[13px]">
                  <Chip tone={sev(a.severity)}>{a.severity}</Chip>
                  <span className="min-w-0 flex-1"><span className="block font-medium">{a.kind.replaceAll("_", " ")}</span><span className="font-light text-muted">{a.message}</span></span>
                  <span className="shrink-0 text-[12px] font-light text-muted">{when(a.raised_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="lg:col-span-12">
          <CardTitle>Pipeline runs</CardTitle>
          {data.runs.length === 0 ? <EmptyState title="No runs recorded" hint="Run python -m tally run ... to record one." /> : (
            <ul className="divide-y divide-line">
              {data.runs.map((r) => (
                <li key={r.run_id} className="flex flex-wrap items-center gap-x-4 gap-y-2 py-3 text-[13px]">
                  <Chip tone={r.status === "succeeded" ? "lime" : r.status === "failed" ? "bad" : "warn"}>{r.status}</Chip>
                  <span className="min-w-0 flex-1 font-medium">{r.run_id}</span>
                  <ol className="flex flex-wrap gap-1.5" aria-label="Steps">
                    {r.steps.map((s, i) => <li key={i}><Chip tone={s.status === "succeeded" ? "lime" : s.status === "skipped" ? "neutral" : "bad"}>{s.step}{s.status === "skipped" ? " (skipped)" : ""}</Chip></li>)}
                  </ol>
                  <span className="text-[12px] font-light text-muted">{when(r.started_at)}</span>
                  {r.error && <p className="basis-full text-bad">{r.error}</p>}
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="lg:col-span-12">
          <CardTitle>Where each table comes from</CardTitle>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {byLayer.filter((g) => g.edges.length).map(({ l, edges }) => (
              <div key={l}>
                <h3 className="mb-2 text-[12px] font-medium uppercase tracking-wide text-teal">{l}</h3>
                <ul className="space-y-1.5 text-[12px]">
                  {Object.entries(edges.reduce<Record<string, string[]>>((a, [p, c]) => ((a[c] ??= []).push(p), a), {})).map(([child, parents]) => (
                    <li key={child}><span className="font-medium">{child}</span><br /><span className="font-light text-muted">← {parents.join(", ")}</span></li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </>
  );
}
