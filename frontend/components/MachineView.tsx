"use client";

import { useEffect, useState } from "react";

import { api, ApiError, type MachineReport, type Telemetry } from "@/lib/api";
import { fmt, LEVEL_LABEL, riskLevel, SENSOR_BY_TR, SENSORS } from "@/lib/format";
import { LevelIcon } from "./RiskBadge";
import { SensorChart } from "./SensorChart";

type Loaded = { id: number; report: MachineReport; telemetry: Telemetry };

export function MachineView({ machineId }: { machineId: number }) {
  const [data, setData] = useState<Loaded | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    // 7 gün + 23 saat: grafikteki 24 saatlik ortalamanın ilk noktası da tam pencereyle hesaplansın.
    Promise.all([api.machine(machineId), api.telemetry(machineId, 7 * 24 + 23)])
      .then(([report, telemetry]) => !cancelled && setData({ id: machineId, report, telemetry }))
      .catch((e: ApiError) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [machineId]);

  if (error) return <p className="p-6 text-ink-2">{error}</p>;
  if (!data) return <p className="p-6 text-ink-3">Makine verisi yükleniyor…</p>;

  // Yeni makine yüklenirken eski görünüm soluk kalır; sayfa zıplamaz.
  const stale = data.id !== machineId;
  const { report, telemetry } = data;
  const risk = report.risk.ariza_riski_24_saat_yuzde;
  const level = riskLevel(risk);
  const abnormal = new Set(report.normalden_belirgin_sapan.map((n) => SENSOR_BY_TR[n]));
  const summaries = Object.fromEntries(
    Object.entries(report.sensorler_son_24_saat).map(([tr, s]) => [SENSOR_BY_TR[tr], s]),
  );

  return (
    <div className={`flex flex-col gap-5 p-5 transition-opacity ${stale ? "opacity-50" : ""}`} aria-busy={stale}>
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="font-cond text-3xl font-semibold leading-tight">Makine {report.makine.id}</h2>
          <p className="text-ink-2">
            {report.makine.model}, {report.makine.yas} yaşında
          </p>
        </div>
        <div className="text-right">
          <div className="flex items-center justify-end gap-2">
            <LevelIcon level={level} size={16} />
            <span className="text-5xl leading-none font-semibold">%{fmt(risk)}</span>
          </div>
          <p className="mt-1 text-sm text-ink-2">
            24 saat içinde arıza riski, {LEVEL_LABEL[level].toLocaleLowerCase("tr")} öncelik
          </p>
        </div>
      </header>

      <p className="-mt-2 max-w-[70ch] text-sm text-ink-2">
        En olası arıza: <span className="text-ink">{report.risk.en_olasi_bilesen}</span> ({report.risk.bilesen_adi}).
        <span className="text-ink-3">
          {" "}
          Bu veri setinde arızadan önceki hata kayıtları çok belirgin olduğu için model çoğu zaman %0&apos;a ya da
          %100&apos;e yakın tahmin verir.
        </span>
      </p>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {SENSORS.map((s) => (
          <SensorChart
            key={s.key}
            name={s.name}
            data={telemetry.points.map((p) => ({ ts: p.ts, value: p[s.key] }))}
            summary={summaries[s.key]}
            abnormal={abnormal.has(s.key)}
            events={telemetry.events}
          />
        ))}
      </div>
      <p className="-mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-ink-3">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-3 w-px bg-critical" aria-hidden /> Hata kaydı
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-3 w-px bg-ink-3" aria-hidden /> Bileşen değişimi
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-0.5 w-3 bg-trace" aria-hidden /> 24 saatlik ortalama (soluk çizgi: saatlik değer)
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-px w-3 bg-ink-2" aria-hidden /> Önceki 30 günün ortalaması (normal)
        </span>
      </p>

      <div className="grid grid-cols-1 gap-5 border-t border-line pt-4 md:grid-cols-3">
        <section>
          <h3 className="mb-2 font-cond text-base font-semibold">Riski artıran etkenler</h3>
          <ol className="space-y-1.5 text-sm">
            {report.risk.riski_en_cok_artiran_3_etken.map((f) => (
              <li key={f.etken} className="flex justify-between gap-3">
                <span className="text-ink-2">{f.etken}</span>
                <span className="tnum text-ink">{fmt(f.deger)}</span>
              </li>
            ))}
          </ol>
        </section>
        <section>
          <h3 className="mb-2 font-cond text-base font-semibold">Son 7 günün hataları</h3>
          {report.hatalar_son_7_gun.length === 0 ? (
            <p className="text-sm text-ink-3">Hata kaydı yok.</p>
          ) : (
            <ul className="space-y-1.5 text-sm">
              {report.hatalar_son_7_gun.map((e) => (
                <li key={e.kod} className="flex justify-between gap-3">
                  <span className="text-ink-2">{e.anlami}</span>
                  <span className="tnum text-ink">{e.adet} kez</span>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section>
          <h3 className="mb-2 font-cond text-base font-semibold">Bileşenler</h3>
          <table className="w-full text-sm">
            <caption className="sr-only">Bileşenlerin kaç gündür değişmediği</caption>
            <tbody>
              {report.bilesen_degisimleri.map((c) => (
                <tr key={c.bilesen}>
                  <th scope="row" className="py-0.5 text-left font-normal text-ink-2">
                    {c.ad}
                  </th>
                  <td className="tnum py-0.5 text-right text-ink">
                    {c.kac_gundur === null ? "kayıt yok" : `${fmt(c.kac_gundur)} gün`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    </div>
  );
}
