"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { Bars, Meter } from "@/components/charts";
import { Card, CardTitle, Chip, DarkCard, ErrorState, PageHeader, Pills, Skeleton, Stat } from "@/components/ui";
import { type Approvals, useApi } from "@/lib/api";
import { PRODUCT_LABELS, bps, compactUsd, day, num, pct } from "@/lib/format";

const DIMS = [
  { value: "issuer", label: "Issuer" },
  { value: "merchant", label: "Merchant" },
  { value: "network", label: "Network" },
  { value: "product", label: "Card product" },
  { value: "channel", label: "Channel" },
  { value: "cross_border", label: "Cross-border" },
  { value: "issuer_region", label: "Region" },
  { value: "mcc_group", label: "Category" },
] as const;
type Dim = (typeof DIMS)[number]["value"];
const FILTERABLE: Partial<Record<Dim, "issuer" | "merchant">> = { issuer: "issuer", merchant: "merchant" };

function niceLabel(dim: string, key: string, label: string) {
  if (dim === "product") return PRODUCT_LABELS[key] ?? key;
  if (dim === "channel") return key === "cnp" ? "Online (card not present)" : "In person (card present)";
  if (dim === "cross_border") return key === "true" ? "Cross-border" : "Domestic";
  if (dim === "network") return key === "visa" ? "Visa" : "Mastercard";
  return label;
}

function View() {
  const sp = useSearchParams();
  const router = useRouter();
  const dim = (sp.get("dim") as Dim) || "issuer";
  const merchant = sp.get("merchant");
  const issuer = sp.get("issuer");
  const q = new URLSearchParams({ dim, ...(merchant ? { merchant } : {}), ...(issuer ? { issuer } : {}) });
  const { data, error, reload } = useApi<Approvals>(`/api/network/approvals?${q}`);

  const set = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(sp.toString());
    Object.entries(patch).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    router.replace(`/approvals?${next}`, { scroll: false });
  };

  if (error) return <ErrorState message={error} onRetry={reload} />;
  const total = data?.breakdown.reduce((s, r) => s + r.attempts, 0) ?? 0;
  const approved = data?.breakdown.reduce((s, r) => s + r.approvals, 0) ?? 0;
  const soft = data?.breakdown.reduce((s, r) => s + r.soft_declines, 0) ?? 0;
  const hard = data?.breakdown.reduce((s, r) => s + r.hard_declines, 0) ?? 0;
  const maxDecl = Math.max(1, ...(data?.declines.map((d) => d.declines) ?? [1]));
  const filter = merchant ? `merchant ${merchant}` : issuer ? `issuer ${issuer}` : null;

  return (
    <>
      <PageHeader
        title="Approvals"
        intro="Who says yes, who says no and why. Slice by any dimension; click a merchant or issuer to drill in."
      />
      <div className="mb-6 grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-4 sm:gap-6">
        <Stat label="Approval rate" value={total ? (100 * approved / total).toFixed(1) : "–"} unit="%" hint={filter ?? "all traffic"} />
        <Stat label="Attempts" value={num(total)} />
        <Stat label="Soft declines" value={num(soft)} hint="retry can succeed" />
        <Stat label="Hard declines" value={num(hard)} hint="do not retry" />
      </div>
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <Pills<Dim> label="Break down by" value={dim} onChange={(v) => set({ dim: v })} options={[...DIMS]} />
        {filter && (
          <button
            type="button"
            onClick={() => set({ merchant: null, issuer: null })}
            className="rounded-full bg-lime px-4 py-2 text-[14px] font-semibold text-ink hover:brightness-95"
          >
            {filter} ✕
          </button>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-12 lg:items-start">
        <DarkCard className="lg:col-span-8">
          <CardTitle dark>Approval rate by day{filter ? ` · ${filter}` : ""}</CardTitle>
          {data ? (
            <Bars
              label="Approval rate by day"
              data={data.daily.map((d) => ({ key: d.day, label: day(d.day), value: d.approval_rate_bps / 10000 }))}
              format={(v) => pct(v, 1)}
              height={265}
              min={Math.max(0, Math.min(...data.daily.map((d) => d.approval_rate_bps / 10000)) - 0.05)}
            />
          ) : (
            <Skeleton className="h-40" />
          )}
        </DarkCard>
        <Card className="lg:col-span-4">
          <CardTitle>Why declined</CardTitle>
          {!data ? (
            <Skeleton className="h-40" />
          ) : (
            <ul className="space-y-3">
              {data.declines.slice(0, 7).map((d) => (
                <li key={d.code}>
                  <div className="mb-1 flex items-center justify-between gap-2 text-[13px]">
                    <span className="flex min-w-0 items-center gap-2">
                      <span className="num w-6 shrink-0 font-semibold text-muted">{d.code}</span>
                      <span className="truncate font-medium">{d.label}</span>
                    </span>
                    <span className="flex shrink-0 items-center gap-2">
                      <Chip tone={d.soft ? "lime" : "neutral"}>{d.soft ? "soft" : "hard"}</Chip>
                      <span className="num w-12 text-right">{num(d.declines)}</span>
                    </span>
                  </div>
                  <Meter value={d.declines} max={maxDecl} />
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="lg:col-span-12">
          <CardTitle>By {DIMS.find((d) => d.value === dim)?.label.toLowerCase()}</CardTitle>
          {!data ? (
            <Skeleton className="h-48" />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-[14px]">
                <thead>
                  <tr className="text-left text-[12px] text-muted">
                    <th scope="col" className="py-2 font-medium">{DIMS.find((d) => d.value === dim)?.label}</th>
                    <th scope="col" className="py-2 text-right font-medium">Attempts</th>
                    <th scope="col" className="w-[30%] py-2 pl-6 font-medium">Approval rate</th>
                    <th scope="col" className="py-2 text-right font-medium">Soft</th>
                    <th scope="col" className="py-2 text-right font-medium">Hard</th>
                    <th scope="col" className="py-2 text-right font-medium">Approved</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {data.breakdown.map((r) => {
                    const target = FILTERABLE[dim];
                    const name = niceLabel(dim, r.key, r.label);
                    return (
                      <tr key={r.key} className="hover:bg-ink/[0.03]">
                        <td className="py-2.5 font-medium">
                          {target ? (
                            <button type="button" className="underline-offset-4 hover:underline" onClick={() => set({ [target]: r.key })}>
                              {name}
                            </button>
                          ) : (
                            name
                          )}
                        </td>
                        <td className="num py-2.5 text-right">{num(r.attempts)}</td>
                        <td className="py-2.5 pl-6">
                          <div className="flex items-center gap-3">
                            <span className="num w-14 shrink-0 font-semibold">{bps(r.approval_rate_bps, 1)}</span>
                            <Meter value={r.approval_rate_bps - 7000} max={3000} tone={r.approval_rate_bps < 8500 ? "bad" : "dark"} />
                          </div>
                        </td>
                        <td className="num py-2.5 text-right">{num(r.soft_declines)}</td>
                        <td className="num py-2.5 text-right">{num(r.hard_declines)}</td>
                        <td className="num py-2.5 text-right">{compactUsd(r.approved_usd ?? 0)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}

export default function ApprovalsPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96" />}>
      <View />
    </Suspense>
  );
}
