"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cx } from "@/components/ui";

const LINKS = [
  { href: "/", label: "Overview" },
  { href: "/exceptions", label: "Exceptions" },
  { href: "/payouts", label: "Payouts" },
  { href: "/scorecard", label: "Scorecard" },
  { href: "/runs", label: "Runs" },
  { href: "/ask", label: "Ask" },
];

export function Nav() {
  const path = usePathname();
  return (
    <header className="mx-auto flex w-full max-w-[1200px] items-center gap-4 px-4 py-4 sm:px-6">
      <Link href="/" className="flex shrink-0 items-center gap-2" aria-label="TrueUp home">
        <span aria-hidden className="grid h-9 w-9 place-items-center rounded-full bg-teal">
          <span className="h-4 w-4 rounded-full bg-lime" />
        </span>
        <span className="text-[17px] font-semibold tracking-tight">TrueUp</span>
      </Link>
      <nav aria-label="Main" className="-mx-1 min-w-0 flex-1 overflow-x-auto">
        <ul className="flex w-max items-center gap-1 px-1">
          {LINKS.map((l) => {
            const active = l.href === "/" ? path === "/" : path.startsWith(l.href);
            return (
              <li key={l.href}>
                <Link
                  href={l.href}
                  aria-current={active ? "page" : undefined}
                  className={cx(
                    "block rounded-full px-4 py-2 text-[14px] transition",
                    active ? "bg-card font-medium text-ink shadow-sm" : "text-muted hover:bg-white/60 hover:text-ink",
                  )}
                >
                  {l.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </header>
  );
}
