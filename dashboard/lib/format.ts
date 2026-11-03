export const usd = (n: number, digits = 0) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: digits, minimumFractionDigits: digits }).format(n);

export const num = (n: number) => new Intl.NumberFormat("en-US").format(n);

export const pct = (n: number, digits = 1) => `${(n * 100).toFixed(digits)}%`;

export function money(minor: number, currency: string) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(minor / 100);
}

export function day(iso: string | null | undefined) {
  if (!iso) return "–";
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

export function when(iso: string | null | undefined) {
  if (!iso) return "–";
  return new Date(iso.endsWith("Z") ? iso : `${iso}Z`).toLocaleString("en-GB", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC",
  }) + " UTC";
}

export const CLASS_LABELS: Record<string, string> = {
  duplicate_ledger: "Duplicate booking",
  missing_in_ledger: "Not in ledger",
  missing_in_processor: "Not in processor",
  amount_mismatch: "Amount mismatch",
  fee_variance: "Fee variance",
  fx_mismatch: "FX mismatch",
  payout_missing: "Payout missing",
  payout_short: "Payout short",
  payout_over: "Payout over",
  payout_late: "Payout late",
  payout_split: "Payout split",
  payout_composition_mismatch: "Payout doesn’t add up",
  bank_orphan: "Orphan bank line",
  bank_ref_missing: "Bank reference missing",
  fx_rounding: "FX rounding",
  cutoff_timing: "Midnight cut-off",
  ref_noise: "Mangled reference",
};
export const label = (c: string) => CLASS_LABELS[c] ?? c.replaceAll("_", " ");
