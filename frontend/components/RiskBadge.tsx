import { LEVEL_LABEL, type RiskLevel } from "@/lib/format";

// Alarm seviyesi asla sadece renkle anlatılmaz: her seviyenin kendi şekli ve etiketi var.
// Acil: üçgen, Yüksek: eşkenar dörtgen, Normal: boş daire.

export function LevelIcon({ level, size = 12 }: { level: RiskLevel; size?: number }) {
  if (level === "acil")
    return (
      <svg width={size} height={size} viewBox="0 0 12 12" aria-hidden className="shrink-0 text-critical">
        <path d="M6 1 11.2 10.5H.8z" fill="currentColor" />
      </svg>
    );
  if (level === "yuksek")
    return (
      <svg width={size} height={size} viewBox="0 0 12 12" aria-hidden className="shrink-0 text-serious">
        <path d="M6 .8 11.2 6 6 11.2.8 6z" fill="currentColor" />
      </svg>
    );
  return (
    <svg width={size} height={size} viewBox="0 0 12 12" aria-hidden className="shrink-0 text-ink-3">
      <circle cx="6" cy="6" r="4.2" fill="none" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  );
}

export function LevelLabel({ level }: { level: RiskLevel }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-ink-2">
      <LevelIcon level={level} />
      {LEVEL_LABEL[level]}
    </span>
  );
}

export const LEVEL_FILL: Record<RiskLevel, string> = {
  acil: "bg-critical",
  yuksek: "bg-serious",
  normal: "bg-ink-3/60",
};
