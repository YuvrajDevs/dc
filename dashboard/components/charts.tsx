"use client";

import { useEffect, useState } from "react";
import { cx } from "@/components/ui";

const EASE = "cubic-bezier(0.22, 1, 0.36, 1)";

function useReady() {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const id = requestAnimationFrame(() => setReady(true));
    return () => cancelAnimationFrame(id);
  }, []);
  return ready;
}

/**
 * Bars for a daily series on a dark card. Hover shows a value in the fixed readout; clicking a
 * bar selects it (when onSelect is given). Bars grow in on mount.
 */
export function Bars({
  data,
  label,
  format,
  height = 150,
  min,
  selected,
  onSelect,
  highlight,
}: {
  data: { key: string; value: number; label?: string }[];
  label: string;
  format: (v: number) => string;
  height?: number;
  /** Baseline for the scale (e.g. 0.6 for approval rates), so small dips are visible. */
  min?: number;
  selected?: string | null;
  onSelect?: (key: string | null) => void;
  /** Keys to draw in the alert colour (e.g. outage days). */
  highlight?: Set<string>;
}) {
  const ready = useReady();
  const [hover, setHover] = useState<string | null>(null);
  const lo = min ?? 0;
  const hi = Math.max(lo + 1e-9, ...data.map((d) => d.value));
  const focus = hover ?? selected ?? null;
  const shown = data.find((d) => d.key === focus) ?? null;
  return (
    <figure>
      <div className="mb-2 h-5 text-[13px]" aria-live="polite">
        {shown ? (
          <>
            <span className="font-semibold">{shown.label ?? shown.key}</span>{" "}
            <span className="num font-semibold text-lime">{format(shown.value)}</span>
          </>
        ) : (
          <span className="text-on-dark-muted">{onSelect ? "Hover for a value, click a bar to filter" : "Hover a bar for its value"}</span>
        )}
      </div>
      <div className="flex items-end" style={{ height, gap: data.length > 60 ? 1 : 3 }} role="group" aria-label={label} onMouseLeave={() => setHover(null)}>
        {data.map((d, i) => {
          const h = ready ? Math.max(2, ((d.value - lo) / (hi - lo)) * 100) : 0;
          const isSel = selected === d.key;
          const dim = focus !== null && d.key !== focus && !isSel;
          const common = {
            onMouseEnter: () => setHover(d.key),
            onFocus: () => setHover(d.key),
            onBlur: () => setHover(null),
            "aria-label": `${d.label ?? d.key}: ${format(d.value)}`,
            className: cx(
              "min-w-px flex-1 rounded-t-[3px] rounded-b-[1px] outline-none focus-visible:ring-2 focus-visible:ring-lime",
              highlight?.has(d.key) ? "bg-[#f08c7a]" : isSel ? "bg-white" : "bg-lime",
            ),
            style: {
              height: `${h}%`,
              opacity: dim ? 0.35 : 1,
              transition: `height 700ms ${EASE} ${Math.min(i * 8, 300)}ms, opacity 250ms ease`,
            },
          };
          return onSelect ? (
            <button key={d.key} type="button" aria-pressed={isSel} onClick={() => onSelect(isSel ? null : d.key)} {...common} />
          ) : (
            <div key={d.key} role="img" tabIndex={0} {...common} />
          );
        })}
      </div>
    </figure>
  );
}

/** Lines for a few series sharing an x axis (dispute curves). */
export function Lines({
  series,
  xLabels,
  format,
  label,
  height = 160,
}: {
  series: { name: string; values: number[] }[];
  xLabels: string[];
  format: (v: number) => string;
  label: string;
  height?: number;
}) {
  const ready = useReady();
  const max = Math.max(1e-9, ...series.flatMap((s) => s.values));
  const w = 100;
  const colors = ["var(--lime)", "#ffffff", "#c9b98a", "#7fb3a8", "#e6a07a"];
  const pts = (vals: number[]) =>
    vals.map((v, i) => `${(i / Math.max(1, vals.length - 1)) * w},${height - (v / max) * (height - 8) - 4}`).join(" ");
  return (
    <figure>
      <svg viewBox={`0 0 ${w} ${height}`} preserveAspectRatio="none" className="w-full overflow-visible" style={{ height }} role="img" aria-label={label}>
        {[0.25, 0.5, 0.75, 1].map((t) => (
          <line key={t} x1="0" x2={w} y1={height - t * (height - 8) - 4} y2={height - t * (height - 8) - 4} stroke="rgba(255,255,255,.08)" vectorEffect="non-scaling-stroke" />
        ))}
        {series.map((s, i) => (
          <polyline
            key={s.name}
            points={pts(s.values)}
            fill="none"
            stroke={colors[i % colors.length]}
            strokeWidth="2.2"
            vectorEffect="non-scaling-stroke"
            strokeLinejoin="round"
            strokeLinecap="round"
            style={{ opacity: ready ? 1 : 0, transition: `opacity 600ms ${EASE} ${i * 120}ms` }}
          />
        ))}
      </svg>
      <div className="mt-1.5 flex justify-between text-[11px] text-on-dark-muted">
        {xLabels.map((x) => (
          <span key={x}>{x}</span>
        ))}
      </div>
      <figcaption className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[12px]">
        {series.map((s, i) => (
          <span key={s.name} className="flex items-center gap-1.5">
            <i className="h-2 w-2 rounded-full" style={{ background: colors[i % colors.length] }} />
            {s.name} <span className="num text-on-dark-muted">{format(s.values[s.values.length - 1] ?? 0)}</span>
          </span>
        ))}
      </figcaption>
    </figure>
  );
}

/** Thin horizontal meter. */
export function Meter({ value, max, tone = "dark" }: { value: number; max: number; tone?: "dark" | "lime" | "bad" | "teal" }) {
  const pct = max ? Math.min(100, (value / max) * 100) : 0;
  const ready = useReady();
  const bg = { dark: "bg-ink", teal: "bg-ink", lime: "bg-lime", bad: "bg-bad" }[tone];
  return (
    <div aria-hidden="true" className="h-2 w-full overflow-hidden rounded-full bg-ink/10">
      <div className={cx("h-full rounded-full", bg)} style={{ width: ready ? `${pct}%` : "0%", transition: `width 700ms ${EASE}` }} />
    </div>
  );
}

/** Stacked daily bars kept for the reconciliation trend: errors over benign look-alikes. */
export function DailyBars({ data }: { data: { day: string; errors: number; benign: number }[] }) {
  const max = Math.max(1, ...data.map((d) => d.errors + d.benign));
  return (
    <div>
      <div role="img" aria-label={`Findings per day over the last ${data.length} days`} className="flex h-36 items-end gap-[3px]">
        {data.map((d) => (
          <div key={d.day} title={`${d.day}: ${d.errors} errors, ${d.benign} benign`} className="flex h-full flex-1 flex-col justify-end">
            <div className="w-full rounded-t-[4px] bg-lime" style={{ height: `${(d.benign / max) * 100}%` }} />
            <div className="w-full bg-white" style={{ height: `${(d.errors / max) * 100}%` }} />
          </div>
        ))}
      </div>
      <div className="mt-3 flex items-center gap-4 text-[12px] text-on-dark-muted">
        <span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-white" />Real errors</span>
        <span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-lime" />Benign look-alikes</span>
      </div>
    </div>
  );
}
