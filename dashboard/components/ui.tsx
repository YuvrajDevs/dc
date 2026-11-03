import type { ComponentProps, ReactNode } from "react";

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

export function Card({ className, ...p }: ComponentProps<"section">) {
  return <section className={cx("rounded-[28px] bg-card p-6 shadow-[0_1px_0_rgba(15,31,28,.04)]", className)} {...p} />;
}

export function CardTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-4 flex items-center justify-between gap-3">
      <h2 className="text-[15px] font-medium text-ink">{children}</h2>
      {aside}
    </div>
  );
}

export function Eyebrow({ children }: { children: ReactNode }) {
  return <p className="text-[13px] font-light text-muted">{children}</p>;
}

const tones = {
  neutral: "bg-line text-ink",
  lime: "bg-lime-soft text-teal-deep",
  teal: "bg-teal text-white",
  warn: "bg-warn-soft text-warn",
  bad: "bg-bad-soft text-bad",
} as const;

export function Chip({ tone = "neutral", children, className }: { tone?: keyof typeof tones; children: ReactNode; className?: string }) {
  return <span className={cx("inline-flex items-center rounded-full px-3 py-1 text-[12px] font-medium", tones[tone], className)}>{children}</span>;
}

export function statusTone(status: string): keyof typeof tones {
  if (status === "open") return "bad";
  if (status === "resolved") return "lime";
  if (status === "explained") return "teal";
  if (status === "auto_cleared") return "neutral";
  return "neutral";
}

export function Button({
  variant = "dark",
  className,
  ...p
}: ComponentProps<"button"> & { variant?: "dark" | "lime" | "ghost" }) {
  const v = {
    dark: "bg-teal text-white hover:bg-teal-deep",
    lime: "bg-lime text-teal-deep hover:brightness-95",
    ghost: "bg-transparent text-ink ring-1 ring-line hover:bg-line",
  }[variant];
  return (
    <button
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-2xl px-5 py-2.5 text-[14px] font-medium transition disabled:cursor-not-allowed disabled:opacity-50",
        v,
        className,
      )}
      {...p}
    />
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
    <Card role="alert" className="border border-bad/20 bg-bad-soft">
      <h2 className="text-[15px] font-medium text-bad">Something went wrong</h2>
      <p className="mt-1 text-[14px] text-ink">{message}</p>
      <p className="mt-1 text-[13px] text-muted">Check that the Tally API is running (python -m tally serve) and try again.</p>
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
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-14 text-center">
      <div aria-hidden className="mb-1 flex h-12 w-12 items-center justify-center rounded-full bg-lime-soft text-2xl text-teal">✓</div>
      <p className="text-[15px] font-medium">{title}</p>
      {hint && <p className="max-w-sm text-[13px] font-light text-muted">{hint}</p>}
      {action}
    </div>
  );
}

export function PageHeader({ title, intro, actions }: { title: string; intro?: string; actions?: ReactNode }) {
  return (
    <header className="mb-6 mt-4 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-[28px] font-medium leading-tight tracking-tight">{title}</h1>
        {intro && <p className="mt-1 max-w-2xl text-[14px] font-light text-muted">{intro}</p>}
      </div>
      {actions}
    </header>
  );
}
