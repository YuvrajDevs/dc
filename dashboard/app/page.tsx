import Link from "next/link";
import { Logo } from "@/components/nav";

const REPO = "https://github.com/YuvrajDevs/dc";

const TOPICS = [
  { href: "/lab", label: "Lab" },
  { href: "/approvals", label: "Approvals" },
  { href: "/disputes", label: "Disputes" },
  { href: "/fees", label: "Fees" },
  { href: "/exceptions", label: "Reconciliation" },
  { href: "/scorecard", label: "Scorecard" },
];

const FINDS = [
  { dot: "bg-alert", title: "A card-testing attack", body: "A burst of tiny online attempts on fresh cards, scored against the merchant's own hourly baseline." },
  { dot: "bg-alert", title: "An issuer stops answering", body: "A cluster of “issuer unavailable” timeouts at one bank; the dashboard names the bank and the window." },
  { dot: "bg-caution", title: "A merchant's disputes spike", body: "Chargebacks far above the category benchmark, flagged before the network's monitoring threshold." },
  { dot: "bg-accent", title: "Interchange above the rate card", body: "The rate card is rebuilt per transaction in SQL, so every overcharged dollar is traceable." },
];

const STEPS = [
  ["Generate", "Card and payment data with a hidden answer key"],
  ["Gate", "Schema contracts and quality checks; bad rows quarantined"],
  ["Model", "dbt staging, facts and analytics marts on DuckDB"],
  ["Detect", "Fraud, outage, dispute and fee rules in SQL"],
  ["Grade", "Every finding scored against the answer key in CI"],
];

export default function Landing() {
  return (
    <div className="mx-auto w-full max-w-[1320px] p-2 sm:p-4">
      <div className="panel px-3 pb-8 pt-2 sm:px-6">
        <header className="flex items-center gap-3">
          <Logo className="text-ink" />
          <nav aria-label="Landing" className="ml-auto flex items-center gap-1">
            <a href="#how" className="hidden rounded-full px-4 py-2 text-body text-on-panel-muted hover:text-ink sm:block">How it works</a>
            <a href={REPO} target="_blank" rel="noopener noreferrer" className="hidden rounded-full px-4 py-2 text-body text-on-panel-muted hover:text-ink sm:block">GitHub</a>
            <Link href="/dashboard" className="rounded-full bg-dark px-5 py-2.5 text-body font-semibold text-white hover:bg-dark-deep">
              Open dashboard
            </Link>
          </nav>
        </header>

        <main id="main" className="rise">
          <section className="mt-10 grid items-stretch gap-6 md:grid-cols-12">
            <div className="flex flex-col justify-end md:col-span-7">
              <p className="mb-3 inline-flex w-fit items-center gap-2 rounded-full bg-card px-3 py-1 text-body-sm text-on-panel-muted">
                <span className="h-1.5 w-1.5 rounded-full bg-accent" /> For payment operations and risk analysts
              </p>
              <h1 className="text-stat font-semibold leading-[1.02] tracking-tight text-ink sm:text-hero">
                Find where card payments leak money, and prove the detector is right.
              </h1>
              <p className="mt-4 max-w-xl text-lead text-on-panel-muted">
                Card-testing fraud, issuer outages, dispute spikes and interchange overcharges, found by SQL over approvals, clearing, disputes and
                reconciliation, with every finding graded against a known answer key.
              </p>
            </div>

            <div className="flex flex-col justify-between rounded-card bg-dark p-6 text-white md:col-span-5">
              <div>
                <p className="text-body-sm font-medium text-on-dark-muted">Try it: the lab</p>
                <p className="mt-2 text-section font-semibold leading-tight">Plant a fraud attack. See if it gets caught.</p>
                <p className="mt-2 text-body text-on-dark-muted">
                  Set the attack size, outage length, dispute spike and fee overcharge. A fresh card network is generated and four detectors are graded
                  on it in seconds.
                </p>
              </div>
              <dl className="mt-6 grid grid-cols-3 gap-4 border-t border-white/10 pt-5">
                {[
                  ["97%", "detectable incidents found"],
                  ["0", "false alarms in 200 runs"],
                  ["100%", "card-testing attacks caught"],
                ].map(([v, l]) => (
                  <div key={l} className="flex flex-col-reverse">
                    <dt className="mt-1 text-caption leading-snug text-on-dark-muted">{l}</dt>
                    <dd className="num text-section font-light leading-none">{v}</dd>
                  </div>
                ))}
              </dl>
              <Link href="/lab" className="mt-6 inline-flex w-fit items-center gap-2 rounded-full bg-accent px-5 py-2.5 text-body font-semibold text-ink hover:brightness-95">
                Open the lab <span aria-hidden>→</span>
              </Link>
            </div>
          </section>

          <div className="mt-8 flex flex-wrap items-center gap-2">
            {TOPICS.map((t) => (
              <Link key={t.href} href={t.href} className="rounded-full px-5 py-2.5 text-lead font-medium text-ink ring-1 ring-ink/20 hover:bg-ink/5">
                {t.label}
              </Link>
            ))}
          </div>

          <section className="mt-5 grid gap-4 md:grid-cols-12">
            <div className="rounded-card bg-card p-6 text-ink md:col-span-7 lg:col-span-8">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-heading font-semibold">What it catches</h2>
                <span className="text-caption text-muted">rules in SQL, checked by tests</span>
              </div>
              <ul className="divide-y divide-line">
                {FINDS.map((f) => (
                  <li key={f.title} className="flex gap-3 py-3">
                    <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${f.dot}`} aria-hidden />
                    <span>
                      <span className="block text-lead font-semibold">{f.title}</span>
                      <span className="block text-body leading-snug text-muted">{f.body}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>

            <div className="grid gap-4 md:col-span-5 lg:col-span-4">
              <div className="rounded-card bg-card p-6 text-ink">
                <p className="text-body-sm font-medium text-muted">Reconciliation, graded</p>
                <p className="num mt-2 text-stat font-light leading-none xl:text-display">0.561 → 0.999</p>
                <p className="mt-2 text-body-sm text-muted">
                  Error precision of the ledger, processor and bank matcher. The first engine fell for typo&apos;d references; the rewrite holds 0.999
                  precision and 0.994 recall on 8 seeds, and 1M rows reconcile in about 7 seconds.
                </p>
              </div>
              <div className="rounded-card bg-card p-6 text-ink">
                <p className="text-body-sm font-medium text-muted">Why synthetic data</p>
                <p className="mt-2 text-lead font-semibold leading-snug">
                  Real card data is private, and with real data nobody knows the right answer. Generated data with a hidden answer key is the only way to
                  measure a detector honestly.
                </p>
              </div>
            </div>
          </section>

          <section id="how" className="mt-10 scroll-mt-6">
            <h2 className="text-section font-semibold tracking-tight text-ink">How it works</h2>
            <ol className="mt-4 grid gap-3 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-5">
              {STEPS.map(([t, d], i) => (
                <li key={t} className="rounded-[20px] bg-card p-4">
                  <span className="num text-caption text-on-panel-muted">0{i + 1}</span>
                  <span className="block text-heading font-semibold text-ink">{t}</span>
                  <span className="mt-1 block text-body-sm leading-snug text-on-panel-muted">{d}</span>
                </li>
              ))}
            </ol>
            <p className="mt-4 text-body-sm text-on-panel-muted">
              Python · SQL · DuckDB · dbt · FastAPI · Airflow · Next.js. Codes follow ISO 8583, Visa and Mastercard conventions.
            </p>
          </section>
        </main>
      </div>
      <footer className="flex flex-wrap items-center justify-between gap-2 px-4 py-5 text-body-sm text-muted">
        <span>TrueUp · a portfolio project by Yuvraj Singh Shekhawat</span>
        <Link href="/lab" className="font-semibold text-ink hover:underline">Open the lab →</Link>
      </footer>
    </div>
  );
}
