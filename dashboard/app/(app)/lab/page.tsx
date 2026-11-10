"use client";

import { useState } from "react";
import { Button, Card, CardTitle, DarkCard, PageHeader, PanelNote, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { num } from "@/lib/format";

type Settings = {
  seed: number;
  days: number;
  txns_per_day: number;
  outage_hours: number;
  card_testing_attempts: number;
  downgrade_share: number;
  dispute_multiplier: number;
};

type Result = {
  kind: "issuer_outage" | "card_testing" | "interchange_downgrade" | "excessive_disputes";
  planted: Record<string, unknown> | null;
  verdict: "found" | "missed" | "false_alarm" | "quiet" | "too_faint";
  trace: number;
  detected_entities: string[];
  evidence: Record<string, string | number>[];
  false_alarms: number;
};

type LabRun = {
  settings: Settings;
  world: { start: string; days: number; authorizations: number; cleared: number; disputes: number; issuers: number; merchants: number };
  results: Result[];
  score: { found: number; missed: number; false_alarms: number; planted: number; too_faint: number };
  seconds: { generate: number; detect: number };
};

const DEFAULTS: Settings = {
  seed: 7,
  days: 60,
  txns_per_day: 300,
  outage_hours: 6,
  card_testing_attempts: 420,
  downgrade_share: 0.35,
  dispute_multiplier: 3,
};

const PRESETS: { label: string; s: Partial<Settings> }[] = [
  { label: "Default", s: DEFAULTS },
  { label: "Subtle attacks", s: { outage_hours: 2, card_testing_attempts: 10, downgrade_share: 0.02, dispute_multiplier: 2.2 } },
  { label: "Nothing planted", s: { outage_hours: 0, card_testing_attempts: 0, downgrade_share: 0, dispute_multiplier: 1 } },
];

const KNOBS: { key: keyof Settings; label: string; hint: string; min: number; max: number; step: number; fmt?: (v: number) => string }[] = [
  { key: "outage_hours", label: "Issuer outage", hint: "Hours the busiest bank stops answering", min: 0, max: 12, step: 1, fmt: (v) => (v ? `${v} h` : "off") },
  { key: "card_testing_attempts", label: "Card-testing attack", hint: "Tiny online attempts on fresh cards in one hour", min: 0, max: 800, step: 5, fmt: (v) => (v ? `${v} tries` : "off") },
  { key: "downgrade_share", label: "Interchange downgrades", hint: "Share of one merchant's online sales charged above the rate card", min: 0, max: 0.8, step: 0.01, fmt: (v) => (v ? `${Math.round(v * 100)}%` : "off") },
  { key: "dispute_multiplier", label: "Dispute spike", hint: "One merchant's chargebacks vs its category norm (1× = normal)", min: 1, max: 4, step: 0.1, fmt: (v) => (v > 1 ? `${v.toFixed(1)}×` : "off") },
  { key: "days", label: "History", hint: "Days of card traffic to generate", min: 35, max: 120, step: 5, fmt: (v) => `${v} days` },
  { key: "txns_per_day", label: "Volume", hint: "Payments per day", min: 100, max: 400, step: 25, fmt: (v) => `${v}/day` },
];

const KIND = {
  issuer_outage: { title: "Issuer outage", rule: "“Issuer unavailable” (91) answers never occur normally: 2 at one bank within an hour, or 3 in a day" },
  card_testing: { title: "Card-testing attack", rule: "An hour ≥4σ above the merchant's own baseline, ≥8 attempts, nearly all on different cards, under half approved" },
  interchange_downgrade: { title: "Interchange downgrades", rule: "3 or more sales at a merchant charged above the rate card, rebuilt exactly per transaction" },
  excessive_disputes: { title: "Dispute spike", rule: "Disputes far above the category benchmark for the merchant's sales (exact Poisson test, p < 0.0002)" },
} as const;

const VERDICT = {
  found: { label: "Found", cls: "bg-lime text-ink" },
  missed: { label: "Missed", cls: "bg-[#f08c7a] text-ink" },
  false_alarm: { label: "False alarm", cls: "bg-[#e9c46a] text-ink" },
  quiet: { label: "Quiet, correctly", cls: "bg-white/10 text-white" },
  too_faint: { label: "Too faint to see", cls: "bg-white/10 text-white" },
} as const;

function plantedText(r: Result) {
  const p = r.planted as Record<string, string | number | number[]> | null;
  if (!p) return "Nothing planted";
  if (r.kind === "issuer_outage") return `${p.issuer_id} on ${p.date}, ${(p.hours_utc as number[]).join(":00–")}:00 UTC`;
  if (r.kind === "card_testing") return `${p.attempts} attempts at ${p.merchant_id} on ${p.date}`;
  if (r.kind === "interchange_downgrade") return `${p.merchant_id}, +${p.added_bps} bps on downgraded sales`;
  return `${p.merchant_id}, chargebacks above its category norm`;
}

function evidenceText(r: Result) {
  const e = r.evidence[0];
  if (!e) {
    if (r.verdict === "too_faint")
      return r.kind === "issuer_outage"
        ? `No detector fired: the outage produced only ${r.trace} timeout${r.trace === 1 ? "" : "s"}, too few to tell from noise.`
        : "No detector fired: at this volume the spike is within chance variation. Raise it, or add days or volume.";
    return "No detector fired.";
  }
  if (r.kind === "issuer_outage") return `${e.entity} · ${e.day}: ${e.unavailable} of ${e.attempts} attempts timed out`;
  if (r.kind === "card_testing") return `${e.entity} · ${String(e.hour).slice(0, 13).replace("T", " ")}:00 — ${e.attempts} attempts, ${e.approvals} approved, z = ${e.zscore}`;
  if (r.kind === "interchange_downgrade") return `${e.entity}: ${num(Number(e.over_rate_card))} of ${num(Number(e.transactions))} sales above the rate card`;
  return `${e.entity}: ${e.disputes} disputes where its category would expect ${e.expected} (p = ${e.p_value})`;
}

export default function LabPage() {
  const [s, setS] = useState<Settings>(DEFAULTS);
  const [run, setRun] = useState<LabRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function go(next = s) {
    setBusy(true);
    setErr(null);
    try {
      setRun(await api<LabRun>("/api/lab/run", { method: "POST", body: JSON.stringify(next) }));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "The run failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Lab"
        intro="Plant your own incidents, generate a fresh card network, and see whether the detectors catch them. Across 200 random runs it found 97% of the incidents that left a detectable trace, with no false alarms."
      />
      <div className="grid gap-4 md:grid-cols-12">
        <Card className="md:col-span-5">
          <CardTitle aside={<span className="text-[12px] text-muted">same settings, same world</span>}>What to plant</CardTitle>
          <div className="mb-5 flex flex-wrap gap-2">
            {PRESETS.map((p) => (
              <button
                key={p.label}
                type="button"
                onClick={() => setS({ ...s, ...p.s })}
                className="rounded-full px-3 py-1.5 text-[13px] font-medium text-ink ring-1 ring-ink/20 hover:bg-ink/5"
              >
                {p.label}
              </button>
            ))}
          </div>
          <div className="space-y-4">
            {KNOBS.map((k) => (
              <label key={k.key} className="block">
                <span className="flex items-baseline justify-between gap-3">
                  <span className="text-[14px] font-semibold">{k.label}</span>
                  <span className="num text-[13px] font-semibold">{k.fmt ? k.fmt(s[k.key]) : s[k.key]}</span>
                </span>
                <input
                  type="range"
                  min={k.min}
                  max={k.max}
                  step={k.step}
                  value={s[k.key]}
                  onChange={(e) => setS({ ...s, [k.key]: Number(e.target.value) })}
                  className="mt-1 w-full accent-[#121611]"
                />
                <span className="block text-[12px] text-muted">{k.hint}</span>
              </label>
            ))}
            <label className="flex items-center justify-between gap-3">
              <span className="text-[14px] font-semibold">Seed</span>
              <span className="flex items-center gap-2">
                <input
                  type="number"
                  min={1}
                  max={99999}
                  value={s.seed}
                  onChange={(e) => setS({ ...s, seed: Number(e.target.value) || 1 })}
                  className="num w-24 rounded-full bg-white px-3 py-1.5 text-right text-[14px] ring-1 ring-ink/15"
                />
                <button
                  type="button"
                  onClick={() => setS({ ...s, seed: 1 + Math.floor(Math.random() * 99999) })}
                  className="rounded-full px-3 py-1.5 text-[13px] font-medium ring-1 ring-ink/20 hover:bg-ink/5"
                >
                  Random
                </button>
              </span>
            </label>
          </div>
          <Button className="mt-6 w-full" onClick={() => go()} disabled={busy}>
            {busy ? "Generating and detecting…" : "Run the lab"}
          </Button>
          {err && (
            <p role="alert" className="mt-3 text-[13px] text-bad">
              {err}. The demo API sleeps when idle; try again in a few seconds.
            </p>
          )}
        </Card>

        <DarkCard className="md:col-span-7" aria-live="polite" aria-busy={busy}>
          {!run ? (
            <div className="flex h-full min-h-[320px] flex-col justify-center gap-3">
              <p className="text-[22px] font-semibold leading-tight">Nothing run yet.</p>
              <p className="max-w-md text-[14px] text-on-dark-muted">
                Each run builds a new world of authorizations, clearing and disputes from your settings, runs four detectors in DuckDB, and grades them against what you planted.
              </p>
            </div>
          ) : (
            <div className={cx(busy && "opacity-50 transition-opacity")}>
              <div className="flex flex-wrap items-end justify-between gap-4 border-b border-white/10 pb-5">
                <dl className="flex flex-wrap gap-7">
                  {[
                    ["Found", `${run.score.found}/${run.score.planted - run.score.too_faint}`],
                    ["Missed", run.score.missed],
                    ["False alarms", run.score.false_alarms],
                    ...(run.score.too_faint ? [["Too faint", run.score.too_faint]] : []),
                  ].map(([a, b]) => (
                    <div key={a}>
                      <dt className="text-[12.5px] text-on-dark-muted">{a}</dt>
                      <dd className="num text-[34px] font-light leading-none">{b}</dd>
                    </div>
                  ))}
                </dl>
                <p className="text-[12px] text-on-dark-muted">
                  {num(run.world.authorizations)} authorizations · {num(run.world.disputes)} disputes · {run.world.days} days · {(run.seconds.generate + run.seconds.detect).toFixed(1)}s
                </p>
              </div>
              <ul className="divide-y divide-white/10">
                {run.results.map((r) => (
                  <li key={r.kind} className="py-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-[15px] font-semibold">{KIND[r.kind].title}</span>
                      <span className={cx("rounded-full px-2.5 py-0.5 text-[12px] font-semibold", VERDICT[r.verdict].cls)}>
                        {VERDICT[r.verdict].label}
                        {r.false_alarms > 0 && r.verdict !== "false_alarm" ? ` · ${r.false_alarms} false alarm${r.false_alarms > 1 ? "s" : ""}` : ""}
                      </span>
                    </div>
                    <p className="mt-1 text-[13px]"><span className="text-on-dark-muted">Planted:</span> {plantedText(r)}</p>
                    <p className="text-[13px]"><span className="text-on-dark-muted">Detected:</span> {evidenceText(r)}</p>
                    <p className="mt-1 text-[12px] text-on-dark-muted">Rule: {KIND[r.kind].rule}</p>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </DarkCard>
      </div>
      <PanelNote className="mt-4">
        Detection rules mirror the dbt marts behind the Approvals, Disputes and Fees pages. Runs are capped at 120 days and 400 payments a day so the free API stays responsive.
      </PanelNote>
    </>
  );
}
