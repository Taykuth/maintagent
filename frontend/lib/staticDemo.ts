// Sunucusuz demo (NEXT_PUBLIC_DEMO_MODE=static): veriler public/demo altındaki JSON'lardan okunur.
// Dosyaları scripts/export_static.py üretir; içerik API'nin kendi yanıtlarıdır.
// Sunucuda yapılan iki iş burada tarayıcıda yapılır:
//   - iş emri kaydı ve onay/ret (maintagent/work_orders.py ile aynı kurallar; sayfa yenilenince sıfırlanır)
//   - kayıtlı çalıştırmanın oynatılması (maintagent/examples.py → replay_events ile aynı mantık)

import type { AgentEvent, WorkOrder, WorkOrderStatus } from "./api";

const BASE = "/demo";
const MAX_GAP_SECONDS = 1.2; // adımlar arası bekleme kısaltılır

export class DemoError extends Error {
  constructor(message: string, public status?: number) {
    super(message);
  }
}

export async function demoGet<T>(file: string): Promise<T> {
  const res = await fetch(`${BASE}/${file}`).catch(() => null);
  if (!res?.ok) throw new DemoError("Demo verisi yüklenemedi. Sayfayı yenilemeyi dene.", res?.status);
  return res.json() as Promise<T>;
}

// --- İş emirleri -------------------------------------------------------------------------------

type NewOrder = Pick<
  WorkOrder,
  "machine_id" | "component" | "risk_pct" | "reason" | "steps" | "parts" | "estimated_hours" | "manual_section"
>;

// Kılavuzdaki öncelik kuralı; work_orders.py → priority_for ile aynı
const priorityFor = (risk: number): WorkOrder["priority"] => (risk >= 80 ? "acil" : risk >= 50 ? "yuksek" : "normal");
// Yerel saat, saat dilimi eki olmadan (sunucudaki datetime.now().isoformat ile aynı biçim)
const now = () => {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 19);
};

const orders: WorkOrder[] = [];

export const demoOrders = {
  list(status?: WorkOrderStatus): WorkOrder[] {
    return orders.filter((o) => !status || o.status === status).sort((a, b) => b.id - a.id);
  },
  openDraft(machineId: number, component: string): WorkOrder | undefined {
    return orders.find((o) => o.machine_id === machineId && o.component === component && o.status === "taslak");
  },
  create(o: NewOrder): WorkOrder {
    const order: WorkOrder = {
      ...o,
      id: orders.reduce((max, x) => Math.max(max, x.id), 0) + 1,
      created_at: now(),
      priority: priorityFor(o.risk_pct),
      status: "taslak",
      decided_at: null,
      note: null,
    };
    orders.push(order);
    return order;
  },
  decide(id: number, approve: boolean, note: string): WorkOrder {
    const i = orders.findIndex((o) => o.id === id);
    if (i < 0) throw new DemoError(`İş emri ${id} bulunamadı.`, 404);
    if (orders[i].status !== "taslak") throw new DemoError(`İş emri ${id} zaten '${orders[i].status}' durumunda.`, 409);
    orders[i] = { ...orders[i], status: approve ? "onaylandi" : "reddedildi", decided_at: now(), note };
    return orders[i];
  },
};

// --- Kayıtlı çalıştırmalar --------------------------------------------------------------------

type RecordedEvent = AgentEvent & { t?: number };
export type RecordedExample = {
  id: string;
  question: string;
  recorded_at: string;
  llm: string;
  events: RecordedEvent[];
};

let examples: Promise<RecordedExample[]> | null = null;

export function demoExamples(): Promise<RecordedExample[]> {
  examples ??= demoGet<RecordedExample[]>("examples.json").catch((e) => {
    examples = null; // bir sonraki denemede yeniden indir
    throw e;
  });
  return examples;
}

function sleep(ms: number, signal?: AbortSignal) {
  return new Promise<void>((resolve) => {
    if (signal?.aborted || ms <= 0) return resolve();
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(timer);
      resolve();
    });
  });
}

/** Kaydı olay olay oynatır. Kayıttaki taslak iş emri buradaki listeye de eklenir; cevaptaki numara düzeltilir. */
export async function replayLocal(id: string, onEvent: (e: AgentEvent) => void, signal?: AbortSignal) {
  const example = (await demoExamples()).find((e) => e.id === id);
  if (!example) throw new DemoError(`Kayıtlı örnek bulunamadı: ${id}`, 404);
  onEvent({ type: "replay", question: example.question, recorded_at: example.recorded_at, llm: example.llm });

  let previous = 0;
  const idMap = new Map<number, number>();
  for (const event of example.events) {
    if (event.type === "waiting") continue; // kayıttaki Groq beklemeleri oynatılmaz
    const t = event.t ?? previous;
    await sleep(Math.min(Math.max(t - previous, 0), MAX_GAP_SECONDS) * 1000, signal);
    if (signal?.aborted) return;
    previous = t;
    const { t: _t, ...rest } = event;
    let out = rest as AgentEvent;
    if (out.type === "tool_result" && out.tool === "draft_work_order" && out.result.is_emri) {
      const old = out.result.is_emri as WorkOrder;
      const order = demoOrders.openDraft(old.machine_id, old.component) ?? demoOrders.create(old);
      idMap.set(old.id, order.id);
      out = { ...out, result: { ...out.result, is_emri: order } };
    }
    if (out.type === "answer" && idMap.size)
      out = { ...out, content: out.content.replace(/#(\d+)/g, (_m, n) => `#${idMap.get(Number(n)) ?? n}`) };
    onEvent(out);
  }
}
