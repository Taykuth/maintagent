"use client";

import { CartesianGrid, Line, LineChart, ReferenceLine, Tooltip, XAxis, YAxis } from "recharts";

import type { MachineEvent, SensorSummary } from "@/lib/api";
import { day, dayTime, fmt, signedPct } from "@/lib/format";

type Props = {
  name: string;
  data: { ts: string; value: number }[];
  summary?: SensorSummary;
  abnormal: boolean;
  events: MachineEvent[];
};

const WINDOW = 24;

// Saatlik veri çok gürültülü; asıl çizgi 24 saatlik hareketli ortalama (modelin de baktığı pencere).
// Saatlik değerler arkada soluk duruyor. İlk 23 saat sadece ortalamayı hesaplamak için çekiliyor.
function withRollingMean(data: { ts: string; value: number }[]) {
  let sum = 0;
  const out = data.map((p, i) => {
    sum += p.value;
    if (i >= WINDOW) sum -= data[i - WINDOW].value;
    return { ...p, mean: i >= WINDOW - 1 ? sum / WINDOW : null };
  });
  return out.slice(WINDOW - 1);
}

// Bir sensör için 7 günlük iz. Dört sensörün ölçekleri farklı olduğu için
// tek grafikte iki eksen yerine dört küçük grafik kullanılıyor.
export function SensorChart({ name, data: raw, summary, abnormal, events: allEvents }: Props) {
  const stroke = abnormal ? "var(--color-warning)" : "var(--color-trace)";
  const data = withRollingMean(raw);
  const first = data[0]?.ts ?? "";
  const events = allEvents.filter((e) => e.ts >= first);
  const ticks = data.filter((p) => p.ts.endsWith("00:00:00")).map((p) => p.ts);

  return (
    <figure className="flex min-w-0 flex-col rounded-lg border border-line bg-panel px-4 pt-3 pb-1">
      <figcaption className="flex flex-wrap items-baseline justify-between gap-x-3">
        <span className="font-cond text-base font-semibold">{name}</span>
        {summary && (
          <span className="text-sm text-ink-2">
            Son 24 saat <span className="tnum text-ink">{fmt(summary.ortalama)}</span>
            <span className="text-ink-3">, normal {fmt(summary.normal_30_gun)}</span>
          </span>
        )}
      </figcaption>
      <p className="mb-1 flex min-h-5 items-center gap-1.5 text-sm">
        {summary && abnormal ? (
          <>
            <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden className="text-warning">
              <path d="M6 1 11.2 10.5H.8z" fill="currentColor" />
            </svg>
            <span className="text-ink">Normalden sapıyor: {signedPct(summary.degisim_yuzde)}</span>
          </>
        ) : summary ? (
          <span className="text-ink-3">Normal aralıkta ({signedPct(summary.degisim_yuzde)})</span>
        ) : null}
      </p>
      <LineChart
        responsive
        style={{ width: "100%", height: 150 }}
        data={data}
        margin={{ top: 6, right: 8, bottom: 0, left: -8 }}
        accessibilityLayer
      >
        <CartesianGrid stroke="var(--color-line)" vertical={false} />
        <XAxis
          dataKey="ts"
          ticks={ticks}
          tickFormatter={day}
          tick={{ fill: "var(--color-ink-3)", fontSize: 11 }}
          axisLine={{ stroke: "var(--color-line-strong)" }}
          tickLine={false}
          minTickGap={8}
        />
        <YAxis
          domain={["auto", "auto"]}
          tick={{ fill: "var(--color-ink-3)", fontSize: 11 }}
          axisLine={false}
          tickLine={false}
          width={44}
          tickFormatter={(v: number) => fmt(Math.round(v))}
          className="tnum"
        />
        {summary && (
          <ReferenceLine
            y={summary.normal_30_gun}
            stroke="var(--color-ink-2)"
            strokeWidth={1}
            ifOverflow="extendDomain"
          />
        )}
        {events.map((e) => (
          <ReferenceLine
            key={`${e.ts}-${e.kod}`}
            x={e.ts}
            stroke={e.tur === "hata" ? "var(--color-critical)" : "var(--color-ink-3)"}
            strokeWidth={1}
          />
        ))}
        <Tooltip
          cursor={{ stroke: "var(--color-ink-3)", strokeWidth: 1 }}
          isAnimationActive={false}
          content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null;
            const point = payload[0].payload as { value: number; mean: number };
            const here = events.filter((e) => e.ts === label);
            return (
              <div className="rounded-md border border-line-strong bg-page px-3 py-2 text-sm shadow-lg">
                <div className="tnum text-base font-semibold text-ink">{fmt(point.mean)}</div>
                <div className="text-ink-2">
                  24 saat ortalaması; o saat <span className="tnum">{fmt(point.value)}</span>
                </div>
                <div className="text-ink-3">{dayTime(String(label))}</div>
                {here.map((e) => (
                  <div key={e.kod} className="mt-1 text-ink-2">
                    {e.tur === "hata" ? `Hata kaydı: ${e.kod}` : `Bakım: ${e.kod} değişti`}
                  </div>
                ))}
              </div>
            );
          }}
        />
        <Line
          type="linear"
          dataKey="value"
          stroke={stroke}
          strokeOpacity={0.3}
          strokeWidth={1}
          dot={false}
          activeDot={false}
          isAnimationActive={false}
        />
        <Line
          type="monotone"
          dataKey="mean"
          stroke={stroke}
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 4, stroke: "var(--color-panel)", strokeWidth: 2, fill: stroke }}
          isAnimationActive={false}
        />
      </LineChart>
    </figure>
  );
}
