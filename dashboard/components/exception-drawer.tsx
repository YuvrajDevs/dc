"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Card, Chip, ErrorState, Skeleton, statusTone } from "@/components/ui";
import { type ExceptionDetail, api, useApi } from "@/lib/api";
import { day, label, money, usd, when } from "@/lib/format";

const SOURCE_TITLES: Record<string, string> = {
  ledger: "Ledger entry", processor: "Processor transaction", processor_payout: "Payout", bank: "Bank line",
};

function field(rec: Record<string, unknown>, key: string) {
  const v = rec[key];
  return v === null || v === undefined || v === "" ? "–" : String(v);
}

function RecordFacts({ source, rec }: { source: string; rec: Record<string, unknown> }) {
  const cur = String(rec.currency ?? "USD");
  const m = (k: string) => (typeof rec[k] === "number" ? money(rec[k] as number, cur) : field(rec, k));
  const rows: [string, string][] =
    source === "ledger"
      ? [["ID", field(rec, "ledger_id")], ["Reference", field(rec, "order_ref_raw")], ["Amount", m("amount_minor")], ["Booked", when(String(rec.booked_at))]]
      : source === "processor"
        ? [["ID", field(rec, "txn_id")], ["Reference", field(rec, "order_ref_raw")], ["Captured", m("gross_minor")], ["Fee charged", m("fee_minor")], ["Fee expected", m("expected_fee_minor")], ["Payout", field(rec, "payout_id")], ["Captured at", when(String(rec.captured_at))]]
        : source === "processor_payout"
          ? [["ID", field(rec, "payout_id")], ["Due", day(String(rec.payout_date))], ["Payout total", m("net_minor_total")], ["Adds up to", m("net_minor_actual")], ["Transactions", field(rec, "txn_count")]]
          : [["ID", field(rec, "bank_line_id")], ["Reference", field(rec, "reference")], ["Amount", m("amount_minor")], ["Value date", day(String(rec.value_date))], ["Description", field(rec, "description")]];
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-[13px]">
      {rows.map(([k, v]) => (
        <div key={k} className="min-w-0">
          <dt className="font-light text-muted">{k}</dt>
          <dd className="truncate font-medium tabular-nums" title={v}>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

const STATUS_CHOICES: { value: "open" | "explained" | "resolved"; text: string }[] = [
  { value: "open", text: "Open" },
  { value: "explained", text: "Explained" },
  { value: "resolved", text: "Resolved" },
];

export function ExceptionDrawer({ id, onClose, onChanged }: { id: string; onClose: () => void; onChanged: () => void }) {
  const { data, error, loading, reload } = useApi<ExceptionDetail>(`/api/exceptions/${id}`);
  const dialog = useRef<HTMLDivElement>(null);
  const opener = useRef<Element | null>(null);
  const [status, setStatus] = useState<"open" | "explained" | "resolved">("explained");
  const [note, setNote] = useState("");
  const [actor, setActor] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    opener.current = document.activeElement;
    setActor(localStorage.getItem("trueup.actor") ?? "");
    dialog.current?.focus();
    return () => {
      if (opener.current instanceof HTMLElement) opener.current.focus();
    };
  }, []);

  useEffect(() => {
    if (data) {
      setNote(data.exception.note ?? "");
      setStatus(data.exception.status === "open" || data.exception.status === "auto_cleared" ? "explained" : (data.exception.status as "explained" | "resolved"));
    }
  }, [data]);

  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [onClose]);

  const onKey = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Tab" && dialog.current) {
        const f = dialog.current.querySelectorAll<HTMLElement>("button, [href], input, textarea, select, [tabindex]:not([tabindex='-1'])");
        if (!f.length) return;
        const first = f[0], last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    },
    [],
  );

  const needsNote = status !== "open";
  async function save(e: React.FormEvent) {
    e.preventDefault();
    setMsg(null);
    if (!actor.trim()) return setMsg({ ok: false, text: "Please enter your name so the history shows who decided." });
    if (needsNote && !note.trim()) return setMsg({ ok: false, text: `Add a short note explaining why this is ${status}.` });
    setBusy(true);
    try {
      localStorage.setItem("trueup.actor", actor.trim());
      await api(`/api/exceptions/${id}`, { method: "PATCH", body: JSON.stringify({ status, note: note.trim(), actor: actor.trim() }) });
      setMsg({ ok: true, text: "Saved. The history below has your entry." });
      reload();
      onChanged();
    } catch (err) {
      setMsg({ ok: false, text: err instanceof Error ? err.message : "Could not save." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-40" onKeyDown={onKey}>
      <div className="absolute inset-0 bg-ink/30" onClick={onClose} aria-hidden />
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="drawer-title"
        tabIndex={-1}
        className="absolute inset-y-0 right-0 flex w-full max-w-[520px] flex-col overflow-y-auto bg-page p-4 shadow-2xl outline-none sm:p-5"
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 id="drawer-title" className="text-[18px] font-medium">
            {data ? label(data.exception.class) : "Exception"}
          </h2>
          <button onClick={onClose} aria-label="Close details" className="grid h-10 w-10 place-items-center rounded-full bg-card text-lg hover:bg-line">×</button>
        </div>

        {error && <ErrorState message={error} onRetry={reload} />}
        {loading && !data && <Skeleton className="h-40 w-full" />}
        {data && (
          <div className="space-y-4">
            <Card className="p-5">
              <div className="flex flex-wrap items-center gap-2">
                <Chip tone={statusTone(data.exception.status)}>{data.exception.status.replace("_", " ")}</Chip>
                <Chip>{data.exception.merchant_id ?? "Bank"}</Chip>
                <Chip>{day(data.exception.occurred_on)}</Chip>
                {data.exception.confidence !== null && <Chip tone="lime">{Math.round((data.exception.confidence ?? 0) * 100)}% sure</Chip>}
              </div>
              <p className="mt-3 text-[26px] font-medium leading-none tabular-nums">{usd(data.exception.amount_usd, 2)}</p>
              <p className="mt-1 text-[12px] font-light text-muted">
                {money(data.exception.amount_at_stake_minor, data.exception.currency)} at stake
              </p>
              <p className="mt-4 text-[14px] leading-relaxed">{data.exception.reason}</p>
            </Card>

            <Card className="p-5">
              <h3 className="mb-3 text-[14px] font-medium">What was matched</h3>
              <div className="space-y-4">
                {data.records.map((r) => (
                  <div key={`${r.source}-${r.id}`} className="rounded-2xl bg-page/60 p-4">
                    <p className="mb-2 text-[12px] font-medium uppercase tracking-wide text-teal">{SOURCE_TITLES[r.source] ?? r.source}</p>
                    {r.record ? <RecordFacts source={r.source} rec={r.record} /> : <p className="text-[13px] text-muted">Record no longer available.</p>}
                    {r.links && r.links.length > 0 && (
                      <p className="mt-3 text-[12px] font-light text-muted">
                        Linked to {r.links.map((l) => String(l.bank_line_id ?? l.linked_id)).join(", ")} ({String(r.links[0].method)} match)
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </Card>

            <Card className="p-5">
              <h3 className="mb-3 text-[14px] font-medium">Your decision</h3>
              <form onSubmit={save} className="space-y-4" noValidate>
                <fieldset>
                  <legend className="mb-2 text-[13px] font-light text-muted">Status</legend>
                  <div className="flex gap-2">
                    {STATUS_CHOICES.map((s) => (
                      <label key={s.value} className={`flex-1 cursor-pointer rounded-2xl px-3 py-2 text-center text-[13px] font-medium ring-1 ring-line has-[:checked]:bg-teal has-[:checked]:text-white has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-teal`}>
                        <input type="radio" name="status" value={s.value} checked={status === s.value} onChange={() => setStatus(s.value)} className="sr-only" />
                        {s.text}
                      </label>
                    ))}
                  </div>
                </fieldset>
                <div>
                  <label htmlFor="note" className="mb-1 block text-[13px] font-light text-muted">
                    Note {needsNote && <span className="text-bad">(required)</span>}
                  </label>
                  <textarea id="note" value={note} onChange={(e) => setNote(e.target.value)} rows={3} placeholder="Why is this fine, or what fixed it?"
                    className="w-full rounded-2xl bg-page/60 px-4 py-3 text-[14px] ring-1 ring-line placeholder:text-muted/70" />
                </div>
                <div>
                  <label htmlFor="actor" className="mb-1 block text-[13px] font-light text-muted">Your name</label>
                  <input id="actor" value={actor} onChange={(e) => setActor(e.target.value)} autoComplete="name"
                    className="w-full rounded-2xl bg-page/60 px-4 py-3 text-[14px] ring-1 ring-line" />
                </div>
                <div aria-live="polite" className="min-h-5 text-[13px]">
                  {msg && <p className={msg.ok ? "text-teal" : "text-bad"}>{msg.text}</p>}
                </div>
                <Button type="submit" disabled={busy} className="w-full">{busy ? "Saving…" : "Save decision"}</Button>
              </form>
            </Card>

            <Card className="p-5">
              <h3 className="mb-3 text-[14px] font-medium">History</h3>
              <ol className="space-y-3 border-l-2 border-line pl-4">
                {[...data.history].reverse().map((h, i) => (
                  <li key={i} className="relative text-[13px]">
                    <span aria-hidden className="absolute -left-[22px] top-1.5 h-2.5 w-2.5 rounded-full bg-teal" />
                    <p><span className="font-medium">{h.actor}</span> {h.from ? <>changed <b>{h.from.replace("_", " ")}</b> to <b>{h.to.replace("_", " ")}</b></> : <>reported it as <b>{h.to}</b></>}</p>
                    {h.note && <p className="font-light text-muted">“{h.note}”</p>}
                    <p className="text-[12px] font-light text-muted">{when(h.at ?? h.occurred_at)}</p>
                  </li>
                ))}
              </ol>
            </Card>
          </div>
        )}
      </div>
    </div>
  );
}
