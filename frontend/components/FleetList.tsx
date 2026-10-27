"use client";

import { useMemo, useState } from "react";

import type { Machine } from "@/lib/api";
import { fmt, riskLevel } from "@/lib/format";
import { LEVEL_FILL, LevelIcon } from "./RiskBadge";

type Props = { machines: Machine[]; selectedId: number | null; onSelect: (id: number) => void };

export function FleetList({ machines, selectedId, onSelect }: Props) {
  const [query, setQuery] = useState("");
  const shown = useMemo(() => {
    const q = query.trim().toLocaleLowerCase("tr");
    if (!q) return machines;
    return machines.filter((m) => String(m.machine_id).includes(q) || m.comp_name.includes(q));
  }, [machines, query]);

  return (
    <section aria-labelledby="fleet-title" className="flex min-h-0 flex-col">
      <div className="flex items-baseline justify-between px-4 pt-4 pb-2">
        <h2 id="fleet-title" className="font-cond text-lg font-semibold">
          Filo
        </h2>
        <span className="text-sm text-ink-3">{machines.length} makine, riske göre</span>
      </div>
      <div className="px-4 pb-3">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Makine no ya da bileşen ara"
          aria-label="Makine ara"
          className="w-full rounded-md border border-line bg-page px-3 py-1.5 text-sm placeholder:text-ink-3"
        />
      </div>
      <ul className="scroll-quiet min-h-0 flex-1 overflow-y-auto border-t border-line">
        {shown.map((m) => {
          const level = riskLevel(m.risk_pct);
          const selected = m.machine_id === selectedId;
          return (
            <li key={m.machine_id}>
              <button
                type="button"
                onClick={() => onSelect(m.machine_id)}
                aria-current={selected ? "true" : undefined}
                className={`grid w-full grid-cols-[16px_1fr_auto] items-center gap-x-2.5 border-b border-line/60 px-4 py-2.5 text-left transition-colors ${
                  selected ? "bg-raised" : "hover:bg-raised/50"
                }`}
              >
                <LevelIcon level={level} />
                <span className="flex min-w-0 flex-col">
                  <span className={`font-cond text-[15px] ${level === "normal" ? "text-ink-2" : "font-semibold"}`}>
                    Makine {m.machine_id}
                  </span>
                  <span className="truncate text-xs text-ink-3">{m.comp_name}</span>
                </span>
                <span className="flex w-20 flex-col items-end gap-1">
                  <span className={`tnum text-sm ${level === "normal" ? "text-ink-3" : "text-ink"}`}>
                    %{fmt(m.risk_pct)}
                  </span>
                  <span className="h-1 w-full rounded-full bg-line" aria-hidden>
                    <span
                      className={`block h-1 rounded-full ${LEVEL_FILL[level]}`}
                      style={{ width: `${Math.max(m.risk_pct, 1.5)}%` }}
                    />
                  </span>
                </span>
              </button>
            </li>
          );
        })}
        {shown.length === 0 && <li className="px-4 py-6 text-sm text-ink-3">Bu aramayla eşleşen makine yok.</li>}
      </ul>
    </section>
  );
}
