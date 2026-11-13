"use client";

import { useEffect, useState } from "react";
import { cx } from "@/components/ui";

const EASE = "cubic-bezier(0.22, 1, 0.36, 1)";

/** A rounded baseline just under the lowest value (to the nearest 5 points), so dips are visible but not exaggerated. */
export const niceFloor = (values: number[], step = 0.05) =>
  values.length ? Math.max(0, Math.floor((Math.min(...values) - step / 2) / step) * step) : 0;

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
      <div className="mb-2 h-5 text-body-sm" aria-live="polite">
        {shown ? (
          <>
            <span className="font-semibold">{shown.label ?? shown.key}</span>{" "}
            <span className="num font-semibold text-accent">{format(shown.value)}</span>
          </>
        ) : (
          <span className="text-on-dark-muted">{onSelect ? "Hover for a value, click a bar to filter" : "Hover a bar for its value"}</span>
        )}
      </div>
      {/* Scale: three labelled gridlines, so a dip reads without hovering */}
      <div className="grid grid-cols-[auto_1fr] gap-x-2 pt-2">
      <div className="relative w-9 text-right text-micro text-on-dark-muted" style={{ height }} aria-hidden>
        {[1, 0.5, 0].map((t) => (
          <span key={t} className="num absolute right-0 -translate-y-1/2" style={{ top: `${(1 - t) * 100}%` }}>{format(lo + t * (hi - lo))}</span>
        ))}
      </div>
      <div className="relative">
      {[0, 0.5, 1].map((t) => (
        <span key={t} aria-hidden className="pointer-events-none absolute inset-x-0 border-t border-white/10" style={{ top: `${t * 100}%` }} />
      ))}
      <div className="relative flex items-end" style={{ height, gap: data.length > 60 ? 1 : 3 }} role="group" aria-label={label} onMouseLeave={() => setHover(null)}>
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
              "min-w-px flex-1 rounded-t-[3px] rounded-b-[1px] outline-none focus-visible:ring-2 focus-visible:ring-accent",
              highlight?.has(d.key) ? "bg-alert" : isSel ? "bg-white" : "bg-accent",
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
      {data.length > 1 && (
        <div className="mt-1.5 flex justify-between text-micro text-on-dark-muted" aria-hidden>
          <span>{data[0].label ?? data[0].key}</span>
          <span>{data[data.length - 1].label ?? data[data.length - 1].key}</span>
        </div>
      )}
      </div>
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
  const colors = ["var(--accent)", "#ffffff", "#6fc3ff", "#5fd4b0", "#ffb38a"]; // distinct on navy, in legend order
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
      <div className="mt-1.5 flex justify-between text-micro text-on-dark-muted">
        {xLabels.map((x) => (
          <span key={x}>{x}</span>
        ))}
      </div>
      <figcaption className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-caption">
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
export function Meter({ value, max, tone = "dark" }: { value: number; max: number; tone?: "dark" | "accent" | "bad" }) {
  const pct = max ? Math.min(100, (value / max) * 100) : 0;
  const ready = useReady();
  const bg = { dark: "bg-ink", accent: "bg-accent", bad: "bg-bad" }[tone];
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
            <div className="w-full rounded-t-[4px] bg-accent" style={{ height: `${(d.benign / max) * 100}%` }} />
            <div className="w-full bg-white" style={{ height: `${(d.errors / max) * 100}%` }} />
          </div>
        ))}
      </div>
      <div className="mt-3 flex items-center gap-4 text-caption text-on-dark-muted">
        <span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-white" />Real errors</span>
        <span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-accent" />Benign look-alikes</span>
      </div>
    </div>
  );
}
