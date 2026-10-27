"use client";

import { useEffect, useRef, useState } from "react";

import { api, ApiError, type WorkOrder } from "@/lib/api";
import { WorkOrderCard } from "./WorkOrderCard";

type Props = { open: boolean; onClose: () => void; onOrdersChanged: () => void };

// Bütün iş emirleri: onay bekleyenler üstte. Yerleşik <dialog> odak yönetimini ve Esc ile kapanmayı sağlar.
export function WorkOrdersDrawer({ open, onClose, onOrdersChanged }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const [orders, setOrders] = useState<WorkOrder[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) {
      d.showModal();
      setError(null);
      api
        .workOrders()
        .then(setOrders)
        .catch((e: ApiError) => setError(e.message));
    }
    if (!open && d.open) d.close();
  }, [open]);

  const sorted = [...(orders ?? [])].sort(
    (a, b) => Number(b.status === "taslak") - Number(a.status === "taslak") || b.id - a.id,
  );

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(e) => e.target === ref.current && onClose()}
      aria-labelledby="orders-title"
      className="m-0 ml-auto h-full max-h-none w-full max-w-md border-l border-line bg-panel p-0 text-ink backdrop:bg-black/50"
    >
      <div className="flex h-full flex-col">
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <h2 id="orders-title" className="font-cond text-lg font-semibold">
            İş emirleri
          </h2>
          <button type="button" onClick={onClose} className="rounded-md px-2 py-1 text-ink-2 hover:text-ink">
            Kapat
          </button>
        </div>
        <div className="scroll-quiet flex-1 space-y-3 overflow-y-auto p-5">
          {error && <p className="text-ink-2">{error}</p>}
          {orders && orders.length === 0 && (
            <p className="text-sm text-ink-2">
              Henüz iş emri yok. Riskli bir makine için ajana soru sorduğunda taslak burada görünür.
            </p>
          )}
          {sorted.map((o) => (
            <WorkOrderCard
              key={o.id}
              order={o}
              onChange={(u) => {
                setOrders((all) => (all ?? []).map((x) => (x.id === u.id ? u : x)));
                onOrdersChanged();
              }}
            />
          ))}
        </div>
      </div>
    </dialog>
  );
}
