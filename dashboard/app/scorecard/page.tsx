"use client";

import { Meter } from "@/components/charts";
import { Card, CardSkeleton, CardTitle, Chip, EmptyState, ErrorState, PageHeader } from "@/components/ui";
import { type Scorecard, useApi } from "@/lib/api";
import { label, num, pct } from "@/lib/format";

export default function ScorecardPage() {
  const { data, error, loading, reload } = useApi<Scorecard>("/api/scorecard");
  if (error) return <><PageHeader title="Scorecard" /><ErrorState message={error} onRetry={reload} /></>;
  if (loading || !data) return <><PageHeader title="Scorecard" /><CardSkeleton lines={6} /></>;

  const key = Object.keys(data.profiles)[0];
  if (!key) return <><PageHeader title="Scorecard" /><Card><EmptyState title="No scorecard saved yet" hint="Run python -m tally grade ... --json benchmarks/scorecard-hard-seed42.json" /></Card></>;
  const cur = data.profiles[key];
  const s = cur.summary;
  const base = data.baseline?.summary;
  const floors = data.floors?.hard;

  const tiles = [
    { name: "Real errors found right", value: pct(s.error_micro_precision, 1), sub: "precision: of everything flagged, how much was a real error", base: base ? pct(base.error_micro_precision, 1) : null },
    { name: "Real errors caught", value: pct(s.error_micro_recall, 1), sub: "recall: of all real errors, how many it found", base: base ? pct(base.error_micro_recall, 1) : null },
    { name: "Look-alikes wrongly alarmed", value: pct(s.benign_false_alarm_rate, 1), sub: `${s.benign_false_alarms} of ${num(s.benign_defects)} harmless oddities`, base: null },
    { name: "Records matched correctly", value: pct(cur.links.ledger_txn.precision, 2), sub: `${num(cur.links.ledger_txn.found)} ledger-to-transaction links`, base: data.baseline ? pct(data.baseline.links.ledger_txn.precision, 2) : null },
  ];

  return (
    <>
      <PageHeader
        title="Scorecard"
        intro="TrueUp invents its own messy payment data, hides a known set of mistakes in it, and grades the reconciliation like a test. These are the results on a deliberately hard world."
        actions={<Chip tone="lime">{String(cur.meta.days)} days · seed {String(cur.meta.seed)}</Chip>}
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {tiles.map((t, i) => (
          <Card key={t.name} className={i === 0 ? "bg-lime" : i === 1 ? "bg-teal text-white" : ""}>
            <p className={`text-[13px] font-light ${i === 1 ? "text-white/75" : "text-muted"}`}>{t.name}</p>
            <p className="mt-2 text-[34px] font-medium leading-none tabular-nums">{t.value}</p>
            <p className={`mt-2 text-[12px] font-light leading-snug ${i === 1 ? "text-white/75" : "text-muted"}`}>{t.sub}</p>
            {t.base && <p className={`mt-3 text-[12px] ${i === 1 ? "text-lime" : "text-teal-deep"}`}>First version of the engine: {t.base}</p>}
          </Card>
        ))}
      </div>

      <Card className="mt-4">
        <CardTitle>How each kind of problem was handled</CardTitle>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[620px] text-left text-[13px]">
            <caption className="sr-only">Per-class results</caption>
            <thead><tr className="text-[12px] font-light text-muted">
              <th scope="col" className="py-2 pr-3 font-light">Kind</th><th scope="col" className="px-2 font-light">Cases</th>
              <th scope="col" className="px-2 font-light">Found right</th><th scope="col" className="px-2 font-light">Missed</th>
              <th scope="col" className="px-2 font-light">False alarms</th><th scope="col" className="w-40 pl-3 font-light">Recall</th>
            </tr></thead>
            <tbody className="divide-y divide-line">
              {cur.classes.filter((c) => c.support > 0 || c.fp > 0).map((c) => (
                <tr key={c.class}>
                  <th scope="row" className="py-2.5 pr-3 font-medium">{label(c.class)} <Chip tone={c.category === "error" ? "bad" : "neutral"} className="ml-1 !px-2 !py-0.5 !text-[11px]">{c.category}</Chip></th>
                  <td className="px-2 tabular-nums">{c.support}</td><td className="px-2 tabular-nums">{c.tp}</td>
                  <td className="px-2 tabular-nums">{c.fn}</td><td className="px-2 tabular-nums">{c.fp}</td>
                  <td className="pl-3"><div className="mb-1 tabular-nums">{pct(c.recall, 1)}</div><Meter value={c.recall} max={1} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        {floors && (
          <Card>
            <CardTitle>Floors enforced on every change</CardTitle>
            <p className="mb-3 text-[13px] font-light text-muted">If a change makes any of these worse, the build fails. They were set from 8 measured runs and are never loosened to make a build pass.</p>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-[13px]">
              {Object.entries(floors).filter(([k]) => !k.startsWith("min_")).map(([k, v]) => (
                <div key={k}><dt className="font-light text-muted">{k.replaceAll("_", " ")}</dt><dd className="font-medium tabular-nums">{k.includes("max") ? "at most " : "at least "}{pct(v, 1)}</dd></div>
              ))}
            </dl>
          </Card>
        )}
        {data.scale && (
          <Card>
            <CardTitle>Speed at scale</CardTitle>
            <div className="overflow-x-auto"><table className="w-full text-left text-[13px]">
              <caption className="sr-only">Reconciliation time by size</caption>
              <thead><tr className="text-[12px] font-light text-muted"><th scope="col" className="py-2 font-light">Ledger rows</th><th scope="col" className="font-light">Reconcile</th><th scope="col" className="font-light">Rows / sec</th><th scope="col" className="font-light">Precision</th><th scope="col" className="font-light">Recall</th></tr></thead>
              <tbody className="divide-y divide-line">
                {data.scale.map((r) => (
                  <tr key={r.rows}><th scope="row" className="py-2.5 font-medium tabular-nums">{num(r.rows)}</th><td className="tabular-nums">{r.reconcile_s}s</td><td className="tabular-nums">{num(r.rows_per_second)}</td><td className="tabular-nums">{pct(r.precision, 1)}</td><td className="tabular-nums">{pct(r.recall, 1)}</td></tr>
                ))}
              </tbody>
            </table></div>
            <p className="mt-3 text-[12px] font-light text-muted">Accuracy dips slightly at one million rows because more look-alike payments share a time window.</p>
          </Card>
        )}
      </div>
      <p className="mt-4 text-[12px] font-light text-muted">All data is synthetic. A real ledger has surprises this world does not model.</p>
    </>
  );
}
