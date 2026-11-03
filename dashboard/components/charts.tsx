"use client";

import { cx } from "@/components/ui";

/** Stacked daily bars: errors (dark) over benign (lime). Accessible: a table-like summary is provided. */
export function DailyBars({ data }: { data: { day: string; errors: number; benign: number }[] }) {
  const max = Math.max(1, ...data.map((d) => d.errors + d.benign));
  return (
    <div>
      <div role="img" aria-label={`Findings per day over the last ${data.length} days, errors and benign look-alikes`}
        className="flex h-40 items-end gap-[3px]">
        {data.map((d) => {
          const total = d.errors + d.benign;
          return (
            <div key={d.day} title={`${d.day}: ${d.errors} errors, ${d.benign} benign`} className="flex h-full flex-1 flex-col justify-end">
              <div className="w-full rounded-t-[6px] bg-lime" style={{ height: `${(d.benign / max) * 100}%` }} />
              <div className={cx("w-full bg-teal", d.benign === 0 && "rounded-t-[6px]")} style={{ height: `${(d.errors / max) * 100}%` }} />
              <span className="sr-only">{`${d.day}: ${total} findings`}</span>
            </div>
          );
        })}
      </div>
      <div className="mt-3 flex items-center gap-4 text-[12px] text-muted">
        <span className="flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-full bg-teal" />Real errors</span>
        <span className="flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-full bg-lime" />Benign look-alikes</span>
      </div>
    </div>
  );
}

export function Meter({ value, max, tone = "teal" }: { value: number; max: number; tone?: "teal" | "lime" }) {
  const pct = max ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div aria-hidden="true" className="h-2.5 w-full overflow-hidden rounded-full bg-black/10">
      <div className={cx("h-full rounded-full", tone === "lime" ? "bg-lime" : "bg-teal")} style={{ width: `${pct}%` }} />
    </div>
  );
}
