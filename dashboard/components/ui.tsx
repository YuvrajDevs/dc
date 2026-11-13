import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

/** Cream side card (the reference's light cards). */
export function Card({ className, ...p }: ComponentProps<"section">) {
  return <section className={cx("rounded-card bg-card p-5 text-ink sm:p-6", className)} {...p} />;
}

/** Black analysis card (the reference's main card). */
export function DarkCard({ className, ...p }: ComponentProps<"section">) {
  return <section className={cx("rounded-card bg-dark p-5 text-white sm:p-6", className)} {...p} />;
}

export function CardTitle({ children, aside, dark }: { children: ReactNode; aside?: ReactNode; dark?: boolean }) {
  return (
    <div className="mb-4 flex items-center justify-between gap-3">
      <h2 className={cx("text-lead font-semibold", dark ? "text-white" : "text-ink")}>{children}</h2>
      {aside}
    </div>
  );
}

const tones = {
  neutral: "bg-line text-ink",
  accent: "bg-accent-soft text-ink",
  dark: "bg-dark text-white",
  warn: "bg-warn-soft text-warn",
  bad: "bg-bad-soft text-bad",
} as const;

export function Chip({ tone = "neutral", children, className }: { tone?: keyof typeof tones; children: ReactNode; className?: string }) {
  return <span className={cx("inline-flex items-center rounded-full px-2.5 py-0.5 text-caption font-semibold", tones[tone], className)}>{children}</span>;
}

export function statusTone(status: string): keyof typeof tones {
  if (status === "open") return "bad";
  if (status === "resolved") return "accent";
  if (status === "explained") return "dark";
  return "neutral";
}

export function Button({
  variant = "dark",
  className,
  ...p
}: ComponentProps<"button"> & { variant?: "dark" | "accent" | "ghost" }) {
  const v = {
    dark: "bg-dark text-white hover:bg-dark-deep",
    accent: "bg-accent text-ink hover:brightness-95",
    ghost: "bg-transparent text-ink ring-1 ring-ink/15 hover:bg-ink/5",
  }[variant];
  return (
    <button
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-full px-5 py-2.5 text-body font-semibold disabled:cursor-not-allowed disabled:opacity-50",
        v,
        className,
      )}
      {...p}
    />
  );
}

/** Outlined filter pills on the panel; the active one turns black, as in the reference. */
export function Pills<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-2">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          className={cx(
            "rounded-full px-4 py-2 text-body font-medium",
            value === o.value ? "bg-dark text-white" : "text-ink ring-1 ring-ink/20 hover:bg-ink/5",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/**
 * Headline number. Currency is part of the value ("$2.5M"); a percent or unit suffix sits on the
 * same baseline in a smaller size, so figures read as one token and compare cleanly in a row.
 */
export function Stat({ label, value, suffix, hint, className }: { label: string; value: ReactNode; suffix?: string; hint?: ReactNode; className?: string }) {
  return (
    <div className={className}>
      <p className="text-body-sm font-medium text-on-panel-muted">{label}</p>
      <p className="num mt-1.5 flex items-baseline gap-0.5 text-stat font-light text-ink">
        {value}
        {suffix && <span className="text-title font-normal text-on-panel-muted">{suffix}</span>}
      </p>
      {hint && <p className="mt-2 text-caption text-on-panel-muted">{hint}</p>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cx("skeleton", className)} />;
}

export function CardSkeleton({ lines = 3 }: { lines?: number }) {
  return (
    <Card aria-busy="true" aria-label="Loading">
      <Skeleton className="mb-4 h-5 w-1/3" />
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} className="mb-3 h-4 w-full" />
      ))}
    </Card>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <Card role="alert">
      <h2 className="text-lead font-semibold text-bad">Something went wrong</h2>
      <p className="mt-1 text-body">{message}</p>
      <p className="mt-1 text-body-sm text-muted">The demo API sleeps when idle; the first request can take a few seconds. Try again.</p>
      {onRetry && (
        <Button variant="ghost" className="mt-4" onClick={onRetry}>
          Try again
        </Button>
      )}
    </Card>
  );
}

export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      <div aria-hidden className="mb-1 grid h-11 w-11 place-items-center rounded-full bg-accent text-xl text-ink">✓</div>
      <p className="text-lead font-semibold">{title}</p>
      {hint && <p className="max-w-sm text-body-sm text-muted">{hint}</p>}
      {action}
    </div>
  );
}

/** Page title on the panel: large, white, with an optional one-line lead. */
export function PageHeader({ title, intro, actions }: { title: string; intro?: string; actions?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-stat font-semibold leading-[1.05] tracking-tight text-ink sm:text-display">{title}</h1>
        {intro && <p className="mt-2 max-w-2xl text-lead text-on-panel-muted">{intro}</p>}
      </div>
      {actions}
    </header>
  );
}

/** Small text that sits directly on the panel (notes, footers). */
export function PanelNote({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={cx("text-body-sm text-on-panel-muted", className)}>{children}</p>;
}

export function ArrowLink({ href, children, dark }: { href: string; children: ReactNode; dark?: boolean }) {
  return (
    <Link href={href} className={cx("inline-flex items-center gap-1 text-body-sm font-semibold underline-offset-4 hover:underline", dark ? "text-accent" : "text-ink")}>
      {children} <span aria-hidden>→</span>
    </Link>
  );
}
