import Link from "next/link";
import { Logo } from "@/components/nav";

const REPO = "https://github.com/YuvrajDevs/dc";

const TOPICS = [
  { href: "/approvals", label: "Approvals" },
  { href: "/disputes", label: "Disputes" },
  { href: "/fees", label: "Fees" },
  { href: "/exceptions", label: "Reconciliation" },
  { href: "/scorecard", label: "Scorecard" },
  { href: "/ask", label: "Ask in English" },
];

const FINDS = [
  { dot: "bg-[#f08c7a]", title: "An issuer stops answering", body: "Timeouts spike for one bank for a few hours and its approval rate falls; the dashboard names the bank and the window." },
  { dot: "bg-[#f08c7a]", title: "A card-testing attack", body: "Hundreds of tiny online attempts on fresh cards in one hour, scored against the merchant's own baseline." },
  { dot: "bg-[#e9c46a]", title: "A merchant over the dispute threshold", body: "Monthly chargeback ratio against monitoring thresholds, with reason codes, win rates and response deadlines." },
  { dot: "bg-lime", title: "Interchange above the rate card", body: "The rate card is rebuilt in SQL, so every downgraded transaction and overpaid dollar is traceable." },
];

const STEPS = [
  ["Generate", "Messy card and payment data with a hidden answer key"],
  ["Gate", "Schema contracts and quality checks; bad rows quarantined"],
  ["Model", "dbt staging, facts and analytics marts on DuckDB"],
  ["Reconcile", "Ledger, processor and bank matched in five tiers"],
  ["Grade", "Every finding scored against the answer key in CI"],
];

export default function Landing() {
  return (
    <div className="mx-auto w-full max-w-[1320px] p-2 sm:p-4">
      <div className="panel px-3 pb-8 pt-2 sm:px-6">
        <header className="flex items-center gap-3">
          <Logo className="text-ink" />
          <nav aria-label="Landing" className="ml-auto flex items-center gap-1">
            <a href="#how" className="hidden rounded-full px-4 py-2 text-[14px] text-on-panel-muted hover:text-ink sm:block">How it works</a>
            <a href={REPO} target="_blank" rel="noopener noreferrer" className="hidden rounded-full px-4 py-2 text-[14px] text-on-panel-muted hover:text-ink sm:block">GitHub</a>
            <Link href="/dashboard" className="rounded-full bg-teal px-5 py-2.5 text-[14px] font-semibold text-white hover:bg-black">
              Open dashboard
            </Link>
          </nav>
        </header>

        <main id="main" className="rise">
          <section className="mt-10 grid items-end gap-8 lg:grid-cols-[1.4fr_auto_1fr_1fr_1fr]">
            <div>
              <p className="mb-3 inline-flex items-center gap-2 rounded-full bg-card px-3 py-1 text-[13px] text-on-panel-muted">
                <span className="h-1.5 w-1.5 rounded-full bg-lime" /> Live demo · synthetic data, no sign-in
              </p>
              <h1 className="text-[44px] font-semibold leading-[1.0] tracking-tight text-ink sm:text-[60px]">
                Payments,
                <br />
                explained.
              </h1>
              <p className="mt-3 max-w-md text-[15px] text-on-panel-muted">
                Card approvals, disputes, interchange and reconciliation in one place, with every number graded against a known answer key.
              </p>
            </div>
            <figure className="relative h-28 w-28 shrink-0" role="img" aria-label="Error precision 99.9%">
              <svg viewBox="0 0 100 100" className="h-full w-full -rotate-90">
                <circle cx="50" cy="50" r="42" fill="none" stroke="var(--lime-soft)" strokeWidth="10" />
                <circle cx="50" cy="50" r="42" fill="none" stroke="var(--teal)" strokeWidth="10" strokeLinecap="round" strokeDasharray={`${2 * Math.PI * 42 * 0.999} 999`} />
              </svg>
              <span className="num absolute inset-0 grid place-items-center text-[17px] font-semibold text-ink">99.9%</span>
            </figure>
            {[
              ["Error precision", "0.999", "graded vs answer key"],
              ["Error recall", "0.994", "on the hard world"],
              ["1M ledger rows", "~7", "seconds to reconcile"],
            ].map(([l, v, h]) => (
              <div key={l}>
                <p className="text-[13px] font-medium text-on-panel-muted">{l}</p>
                <p className="num mt-1 text-[44px] font-light leading-none text-ink sm:text-[52px]">{v}</p>
                <p className="mt-1.5 text-[12.5px] text-on-panel-muted">{h}</p>
              </div>
            ))}
          </section>

          <div className="mt-9 flex flex-wrap items-center gap-2">
            {TOPICS.map((t, i) => (
              <Link
                key={t.href}
                href={t.href}
                className={
                  i === 0
                    ? "rounded-full bg-teal px-5 py-2.5 text-[15px] font-medium text-white"
                    : "rounded-full px-5 py-2.5 text-[15px] font-medium text-ink ring-1 ring-ink/20 hover:bg-ink/5"
                }
              >
                {t.label}
              </Link>
            ))}
          </div>

          <section className="mt-5 grid gap-4 lg:grid-cols-12">
            <div className="rounded-[26px] bg-teal p-6 text-white lg:col-span-8">
              <div className="mb-4 flex items-center justify-between">
                <h2 className="text-[16px] font-semibold">What it finds on its own</h2>
                <span className="text-[12px] text-on-dark-muted">planted in the data, found by SQL, checked by tests</span>
              </div>
              <ul className="divide-y divide-white/10">
                {FINDS.map((f) => (
                  <li key={f.title} className="flex gap-3 py-3">
                    <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${f.dot}`} aria-hidden />
                    <span>
                      <span className="block text-[15px] font-semibold">{f.title}</span>
                      <span className="block text-[13.5px] leading-snug text-on-dark-muted">{f.body}</span>
                    </span>
                  </li>
                ))}
              </ul>
              <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-white/10 pt-5">
                <dl className="flex flex-wrap gap-8">
                  {[["Authorizations", "54k"], ["Disputes", "200+"], ["Issuers", "20"], ["Tests", "216"]].map(([a, b]) => (
                    <div key={a}>
                      <dt className="text-[12.5px] text-on-dark-muted">{a}</dt>
                      <dd className="num text-[30px] font-light leading-none">{b}</dd>
                    </div>
                  ))}
                </dl>
                <Link href="/dashboard" className="grid h-12 w-12 place-items-center rounded-full bg-lime text-[20px] text-ink hover:brightness-95" aria-label="Open the dashboard">
                  →
                </Link>
              </div>
            </div>

            <div className="grid gap-4 lg:col-span-4">
              <div className="rounded-[26px] bg-card p-6 text-ink">
                <p className="text-[13px] font-medium text-muted">Graded, not claimed</p>
                <p className="num mt-2 text-[44px] font-light leading-none">0.561 → 0.999</p>
                <p className="mt-2 text-[13px] text-muted">The first engine fell for typo&apos;d references on the hard world. The rewrite is measured on 8 seeds and floors are enforced in CI.</p>
              </div>
              <div className="rounded-[26px] bg-card p-6 text-ink">
                <p className="text-[13px] font-medium text-muted">Plain-English questions</p>
                <p className="mt-2 text-[22px] font-semibold leading-tight">&ldquo;Approval rate by issuer last week&rdquo;</p>
                <p className="mt-2 text-[13px] text-muted">Becomes validated, read-only SQL: 45 of 45 evaluation questions answered, 68 of 68 unsafe requests refused.</p>
              </div>
            </div>
          </section>

          <section id="how" className="mt-10 scroll-mt-6">
            <h2 className="text-[26px] font-semibold tracking-tight text-ink">How it works</h2>
            <ol className="mt-4 grid gap-3 sm:grid-cols-5">
              {STEPS.map(([t, d], i) => (
                <li key={t} className="rounded-[20px] bg-card p-4">
                  <span className="num text-[12px] text-on-panel-muted">0{i + 1}</span>
                  <span className="block text-[16px] font-semibold text-ink">{t}</span>
                  <span className="mt-1 block text-[13px] leading-snug text-on-panel-muted">{d}</span>
                </li>
              ))}
            </ol>
            <p className="mt-4 text-[13px] text-on-panel-muted">
              Python · DuckDB · dbt · FastAPI · Airflow · Next.js. All data is synthetic; codes follow ISO 8583, Visa and Mastercard conventions.
            </p>
          </section>
        </main>
      </div>
      <footer className="flex flex-wrap items-center justify-between gap-2 px-4 py-5 text-[12.5px] text-muted">
        <span>TrueUp · a portfolio project by Yuvraj Singh Shekhawat</span>
        <Link href="/dashboard" className="font-semibold text-ink hover:underline">Open the dashboard →</Link>
      </footer>
    </div>
  );
}
