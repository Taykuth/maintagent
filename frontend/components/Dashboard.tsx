"use client";

import { useCallback, useEffect, useState } from "react";

import { api, API_URL, ApiError, type Health, type Machine } from "@/lib/api";
import { fullDate, riskLevel } from "@/lib/format";
import { AgentPanel } from "./AgentPanel";
import { FleetList } from "./FleetList";
import { MachineView } from "./MachineView";
import { LevelIcon } from "./RiskBadge";
import { WorkOrdersDrawer } from "./WorkOrdersDrawer";

export function Dashboard() {
  const [health, setHealth] = useState<Health | null>(null);
  const [machines, setMachines] = useState<Machine[] | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [pending, setPending] = useState(0);
  const [ordersOpen, setOrdersOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshPending = useCallback(() => {
    api
      .workOrders("taslak")
      .then((o) => setPending(o.length))
      .catch(() => {});
  }, []);

  const load = useCallback(() => {
    setError(null);
    Promise.all([api.health(), api.machines()])
      .then(([h, m]) => {
        setHealth(h);
        setMachines(m);
        setSelectedId((id) => id ?? m[0]?.machine_id ?? null);
      })
      .catch((e: ApiError) => setError(e.message));
    refreshPending();
  }, [refreshPending]);

  useEffect(() => {
    load();
  }, [load]);

  if (error)
    return (
      <main className="grid min-h-screen place-items-center p-6">
        <div className="max-w-lg space-y-3">
          <h1 className="font-cond text-2xl font-semibold">Veriye ulaşılamadı</h1>
          <p className="text-ink-2">{error}</p>
          <p className="text-sm text-ink-3">Beklenen adres: {API_URL}</p>
          <button
            type="button"
            onClick={load}
            className="rounded-md bg-ink px-4 py-1.5 font-semibold text-page hover:bg-white"
          >
            Tekrar dene
          </button>
        </div>
      </main>
    );

  if (!machines || !health)
    return <main className="grid min-h-screen place-items-center text-ink-3">Filo verisi yükleniyor…</main>;

  const urgent = machines.filter((m) => riskLevel(m.risk_pct) === "acil").length;
  const high = machines.filter((m) => riskLevel(m.risk_pct) === "yuksek").length;

  return (
    <div className="flex min-h-screen flex-col lg:h-screen">
      <header className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-line bg-panel px-4 py-3">
        <h1 className="font-cond text-xl font-semibold">MaintAgent</h1>
        <p className="text-sm text-ink-2">
          Şu an <span className="tnum text-ink">{fullDate(health.as_of)}</span>
          <span className="text-ink-3"> (veri setinin zamanı)</span>
        </p>
        <p className="flex items-center gap-4 text-sm text-ink-2" aria-label="Alarm durumu">
          <span className="inline-flex items-center gap-1.5">
            <LevelIcon level="acil" />
            <span className="tnum text-ink">{urgent}</span> acil
          </span>
          <span className="inline-flex items-center gap-1.5">
            <LevelIcon level="yuksek" />
            <span className="tnum text-ink">{high}</span> yüksek
          </span>
          <span className="inline-flex items-center gap-1.5">
            <LevelIcon level="normal" />
            <span className="tnum text-ink">{machines.length - urgent - high}</span> normal
          </span>
        </p>
        <button
          type="button"
          onClick={() => setOrdersOpen(true)}
          className="ml-auto rounded-md border border-line-strong px-3 py-1.5 text-sm hover:bg-raised"
        >
          İş emirleri
          {pending > 0 && <span className="ml-2 rounded-full bg-ink px-1.5 text-xs font-semibold text-page">{pending}</span>}
        </button>
      </header>

      <main className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[280px_minmax(0,1fr)_400px]">
        <div className="flex max-h-80 min-h-0 flex-col border-b border-line bg-panel lg:max-h-none lg:border-r lg:border-b-0">
          <FleetList machines={machines} selectedId={selectedId} onSelect={setSelectedId} />
        </div>
        <div className="scroll-quiet min-h-0 overflow-y-auto">
          {selectedId != null && <MachineView machineId={selectedId} />}
        </div>
        <div className="flex min-h-[560px] flex-col border-t border-line bg-panel lg:min-h-0 lg:border-t-0 lg:border-l">
          <AgentPanel machineId={selectedId} llmName={health.llm} onOrdersChanged={refreshPending} />
        </div>
      </main>

      <WorkOrdersDrawer open={ordersOpen} onClose={() => setOrdersOpen(false)} onOrdersChanged={refreshPending} />
    </div>
  );
}
