"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cx } from "@/components/ui";

const GROUPS = [
  {
    title: "Card network",
    links: [
      { href: "/lab", label: "Lab" },
      { href: "/dashboard", label: "Dashboard" },
      { href: "/approvals", label: "Approvals" },
      { href: "/disputes", label: "Disputes" },
      { href: "/fees", label: "Fees" },
    ],
  },
  {
    title: "Reconciliation",
    links: [
      { href: "/exceptions", label: "Exceptions" },
    ],
  },
  {
    title: "Quality",
    links: [
      { href: "/scorecard", label: "Scorecard" },
    ],
  },
];

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cx("flex items-center gap-2", className)}>
      <svg viewBox="0 0 28 28" className="h-7 w-7" aria-hidden>
        <circle cx="14" cy="14" r="12.5" fill="none" stroke="currentColor" strokeWidth="2.2" />
        <path d="M8.5 14.5l3.6 3.6 7.4-8" fill="none" stroke="var(--lime)" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <span className="text-[19px] font-semibold tracking-tight">TrueUp</span>
    </span>
  );
}

/** Left sidebar on large screens; a scrollable row of pills on small ones. */
export function Nav() {
  const path = usePathname();
  const active = (href: string) => path === href || path.startsWith(`${href}/`);
  return (
    <aside className="flex flex-col gap-3 rounded-[24px] bg-card p-3 lg:sticky lg:top-4 lg:h-[calc(100vh-3rem)] lg:gap-6 lg:p-4">
      <Link href="/" aria-label="TrueUp home" className="px-1 pt-1 text-ink">
        <Logo />
      </Link>
      <nav aria-label="Main" className="-mx-1 overflow-x-auto [scrollbar-width:none] lg:mx-0 lg:overflow-visible">
        <div className="flex w-max gap-1 px-1 lg:w-auto lg:flex-col lg:gap-5 lg:px-0">
          {GROUPS.map((g) => (
            <div key={g.title} className="flex gap-1 lg:flex-col">
              <p className="hidden px-3 pb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-on-panel-muted lg:block">{g.title}</p>
              {g.links.map((l) => (
                <Link
                  key={l.href}
                  href={l.href}
                  aria-current={active(l.href) ? "page" : undefined}
                  className={cx(
                    "block whitespace-nowrap rounded-full px-4 py-2 text-[14px] font-medium",
                    active(l.href) ? "bg-teal text-white shadow-sm" : "text-on-panel-muted hover:bg-ink/5 hover:text-ink",
                  )}
                >
                  {l.label}
                </Link>
              ))}
            </div>
          ))}
        </div>
      </nav>
      <div className="mt-auto hidden items-center gap-2 rounded-full bg-white py-1 pl-1 pr-3 lg:flex">
        <span aria-hidden className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-lime text-[12px] font-bold text-ink">AN</span>
        <span className="min-w-0 text-[12.5px] leading-tight text-ink">
          <span className="block font-semibold">Analyst</span>
          <span className="block truncate text-on-panel-muted">Demo workspace</span>
        </span>
      </div>
    </aside>
  );
}
