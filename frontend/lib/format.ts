// Sayı, tarih ve risk seviyesi biçimlendirme. Tüm metinler Türkçe.

export type RiskLevel = "acil" | "yuksek" | "normal";

/** Kılavuzdaki öncelik kuralıyla aynı: %80 ve üstü acil, %50-80 yüksek. */
export function riskLevel(pct: number): RiskLevel {
  if (pct >= 80) return "acil";
  if (pct >= 50) return "yuksek";
  return "normal";
}

export const LEVEL_LABEL: Record<RiskLevel, string> = { acil: "Acil", yuksek: "Yüksek", normal: "Normal" };

const num = new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 1 });
export const fmt = (n: number) => num.format(n);
export const pct = (n: number) => `%${num.format(n)}`;
export const signedPct = (n: number) => `${n > 0 ? "+" : n < 0 ? "−" : ""}%${num.format(Math.abs(n))}`;

// Veri setindeki zamanlar saat dilimi içermez ("2015-09-30 06:00:00"); yerel saat olarak okunur.
const toDate = (ts: string) => new Date(ts.replace(" ", "T"));
const dayFmt = new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "short" });
const timeFmt = new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const fullFmt = new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" });

export const day = (ts: string) => dayFmt.format(toDate(ts));
export const dayTime = (ts: string) => timeFmt.format(toDate(ts));
export const fullDate = (ts: string) => fullFmt.format(toDate(ts));

export const SENSORS = [
  { key: "volt", name: "Voltaj" },
  { key: "rotate", name: "Dönüş hızı" },
  { key: "pressure", name: "Basınç" },
  { key: "vibration", name: "Titreşim" },
] as const;

// Rapordaki Türkçe sensör adları (tools.py SENSOR_TR) → telemetri sütun adları
export const SENSOR_BY_TR: Record<string, (typeof SENSORS)[number]["key"]> = {
  voltaj: "volt",
  "dönüş hızı": "rotate",
  basınç: "pressure",
  titreşim: "vibration",
};
