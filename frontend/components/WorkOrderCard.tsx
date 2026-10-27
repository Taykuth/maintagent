"use client";

import { useState } from "react";

import { api, ApiError, type WorkOrder } from "@/lib/api";
import { dayTime, fmt, LEVEL_LABEL } from "@/lib/format";
import { LevelIcon } from "./RiskBadge";

const COMP_NAME: Record<string, string> = {
  comp1: "güç ünitesi",
  comp2: "ana mil rulmanı",
  comp3: "hidrolik valf bloğu",
  comp4: "motor-mil kaplini",
};

const STATUS_TEXT = { taslak: "Onay bekliyor", onaylandi: "Onaylandı", reddedildi: "Reddedildi" } as const;

type Props = { order: WorkOrder; onChange: (o: WorkOrder) => void };

// İş emri taslağı. Ajan sadece taslak hazırlar; karar bu karttaki düğmelerle insan tarafından verilir.
export function WorkOrderCard({ order, onChange }: Props) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function decide(approve: boolean) {
    setBusy(true);
    setError(null);
    try {
      onChange(await (approve ? api.approve(order.id, note) : api.reject(order.id, note)));
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  const priority = order.priority === "acil" ? "acil" : order.priority === "yuksek" ? "yuksek" : "normal";

  return (
    <article className="rounded-lg border border-line-strong bg-raised p-4 text-sm" aria-label={`İş emri ${order.id}`}>
      <header className="flex items-start justify-between gap-3">
        <div>
          <h3 className="font-cond text-base font-semibold">
            İş emri #{order.id}: Makine {order.machine_id}, {COMP_NAME[order.component] ?? order.component}
          </h3>
          <p className="mt-0.5 flex items-center gap-1.5 text-ink-2">
            <LevelIcon level={priority} />
            {LEVEL_LABEL[priority]} öncelik
            <span className="text-ink-3">(risk %{fmt(order.risk_pct)})</span>
          </p>
        </div>
        <span
          className={`shrink-0 rounded-full border px-2 py-0.5 text-xs ${
            order.status === "onaylandi"
              ? "border-good/60 text-ink"
              : order.status === "reddedildi"
                ? "border-line-strong text-ink-3"
                : "border-line-strong text-ink-2"
          }`}
        >
          {order.status === "onaylandi" && <span className="mr-1 text-good">✓</span>}
          {STATUS_TEXT[order.status]}
        </span>
      </header>

      <p className="mt-3 text-ink-2">{order.reason}</p>

      <ol className="mt-3 list-decimal space-y-1 pl-5 marker:text-ink-3">
        {order.steps.map((s, i) => (
          <li key={i}>{s}</li>
        ))}
      </ol>

      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-ink-2">
        {order.estimated_hours != null && (
          <>
            <dt className="text-ink-3">Süre</dt>
            <dd>{fmt(order.estimated_hours)} saat</dd>
          </>
        )}
        {order.parts.length > 0 && (
          <>
            <dt className="text-ink-3">Parça</dt>
            <dd>{order.parts.join(", ")}</dd>
          </>
        )}
        {order.manual_section && (
          <>
            <dt className="text-ink-3">Kaynak</dt>
            <dd>{order.manual_section}</dd>
          </>
        )}
      </dl>

      {order.status === "taslak" ? (
        <div className="mt-4 flex flex-col gap-2">
          <label className="sr-only" htmlFor={`note-${order.id}`}>
            Not
          </label>
          <input
            id={`note-${order.id}`}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Not ekle (isteğe bağlı)"
            maxLength={500}
            className="rounded-md border border-line bg-page px-3 py-1.5 placeholder:text-ink-3"
          />
          <div className="flex gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => decide(true)}
              className="rounded-md bg-ink px-4 py-1.5 font-semibold text-page hover:bg-white disabled:opacity-50"
            >
              Onayla
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => decide(false)}
              className="rounded-md border border-line-strong px-4 py-1.5 text-ink-2 hover:text-ink disabled:opacity-50"
            >
              Reddet
            </button>
          </div>
          {error && (
            <p className="flex items-start gap-1.5 text-ink">
              <span className="mt-1">
                <LevelIcon level="acil" />
              </span>
              {error}
            </p>
          )}
        </div>
      ) : (
        <p className="mt-3 text-xs text-ink-3">
          {STATUS_TEXT[order.status]}
          {order.decided_at ? `, ${dayTime(order.decided_at.replace("T", " "))}` : ""}
          {order.note ? `. Not: ${order.note}` : ""}
        </p>
      )}
    </article>
  );
}
