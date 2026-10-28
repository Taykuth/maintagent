// Backend (FastAPI) ile konuşan tek dosya. Tipler maintagent/api.py ve tools.py çıktılarıyla aynı.

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export type Health = {
  ok: boolean;
  as_of: string;
  llm: string;
  manual_search: string;
  draft_threshold: number;
};

export type Machine = {
  machine_id: number;
  model: string;
  age: number;
  risk_pct: number;
  likely_comp: string;
  comp_name: string;
};

export type SensorSummary = { ortalama: number; normal_30_gun: number; degisim_yuzde: number };

export type MachineReport = {
  makine: { id: number; model: string; yas: number };
  risk: {
    ariza_riski_24_saat_yuzde: number;
    en_olasi_bilesen: string;
    bilesen_adi: string;
    riski_en_cok_artiran_3_etken: { etken: string; deger: number }[];
  };
  sensorler_son_24_saat: Record<string, SensorSummary>;
  normalden_belirgin_sapan: string[];
  hatalar_son_7_gun: { kod: string; anlami: string; adet: number }[];
  bilesen_degisimleri: { bilesen: string; ad: string; kac_gundur: number | null; son_neden: string | null }[];
};

export type TelemetryPoint = { ts: string; volt: number; rotate: number; pressure: number; vibration: number };
export type MachineEvent = { ts: string; tur: "hata" | "bakim"; kod: string };
export type Telemetry = { machine_id: number; points: TelemetryPoint[]; events: MachineEvent[] };

export type WorkOrderStatus = "taslak" | "onaylandi" | "reddedildi";
export type WorkOrder = {
  id: number;
  created_at: string;
  machine_id: number;
  component: string;
  priority: "acil" | "yuksek" | "normal";
  risk_pct: number;
  reason: string;
  steps: string[];
  parts: string[];
  estimated_hours: number | null;
  manual_section: string | null;
  status: WorkOrderStatus;
  decided_at: string | null;
  note: string | null;
};

// Ajanın canlı akışındaki olaylar (maintagent/agent.py → emit)
export type AgentEvent =
  | { type: "tool_call"; tool: string; arguments: string }
  | { type: "tool_result"; tool: string; arguments: string; result: Record<string, unknown>; ms: number }
  | { type: "nudge"; missing: Record<string, string[]> }
  | { type: "waiting"; seconds: number }
  | { type: "tool_error"; message: string }
  | { type: "revise"; sayilar?: number[]; birimler?: string[]; eksik_bolumler?: string[] }
  | { type: "answer"; content: string; tokens: number; seconds: number; stopped_early: boolean }
  | { type: "error"; message: string };

export class ApiError extends Error {
  constructor(message: string, public status?: number) {
    super(message);
  }
}

const UNREACHABLE =
  "API'ye ulaşılamıyor. Terminalde şu komut çalışıyor mu? uvicorn maintagent.api:create_app --factory";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, init);
  } catch {
    throw new ApiError(UNREACHABLE);
  }
  if (!res.ok) throw new ApiError(await errorMessage(res), res.status);
  return res.json() as Promise<T>;
}

async function errorMessage(res: Response): Promise<string> {
  const body = await res.json().catch(() => null);
  // FastAPI doğrulama hatalarında detail bir listedir; diğerlerinde metin.
  if (typeof body?.detail === "string") return body.detail;
  return `İstek başarısız oldu (HTTP ${res.status}).`;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  health: () => request<Health>("/api/health"),
  machines: () => request<Machine[]>("/api/machines"),
  machine: (id: number) => request<MachineReport>(`/api/machines/${id}`),
  telemetry: (id: number, hours = 168) => request<Telemetry>(`/api/machines/${id}/telemetry?hours=${hours}`),
  workOrders: (status?: WorkOrderStatus) =>
    request<WorkOrder[]>(`/api/work-orders${status ? `?status=${status}` : ""}`),
  approve: (id: number, note: string) => request<WorkOrder>(`/api/work-orders/${id}/approve`, json({ note })),
  reject: (id: number, note: string) => request<WorkOrder>(`/api/work-orders/${id}/reject`, json({ note })),
};

/** Ajana soru sorar; sunucunun gönderdiği her olayı (SSE) geldiği anda onEvent'e verir. */
export async function askAgent(question: string, onEvent: (e: AgentEvent) => void, signal?: AbortSignal) {
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/ask`, { ...json({ question }), signal });
  } catch (e) {
    if ((e as Error).name === "AbortError") return;
    throw new ApiError(UNREACHABLE);
  }
  if (!res.ok || !res.body) throw new ApiError(await errorMessage(res), res.status);

  // SSE biçimi: her olay "event: ...\ndata: {...}\n\n". Parçalar yarım gelebilir; tamponda biriktiriyoruz.
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let end: number;
    while ((end = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      const data = block
        .split("\n")
        .filter((line) => line.startsWith("data: "))
        .map((line) => line.slice(6))
        .join("\n");
      if (data) onEvent(JSON.parse(data) as AgentEvent);
    }
  }
}
