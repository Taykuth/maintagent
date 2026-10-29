"use client";

import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";

import {
  api,
  askAgent,
  type AgentEvent,
  ApiError,
  type Example,
  REPO_URL,
  replayExample,
  STATIC_DEMO,
  type WorkOrder,
} from "@/lib/api";
import { dayTime, fmt } from "@/lib/format";
import { LevelIcon } from "./RiskBadge";
import { WorkOrderCard } from "./WorkOrderCard";

type Step =
  | { kind: "tool"; tool: string; args: Record<string, unknown>; result?: Record<string, unknown>; ms?: number }
  | { kind: "nudge"; missing: Record<string, string[]> }
  | { kind: "waiting"; seconds: number }
  | { kind: "tool_error"; message: string }
  | { kind: "revise"; numbers: number[]; units: string[]; sections: string[] }
  | { kind: "error"; message: string };

type Replay = Extract<AgentEvent, { type: "replay" }>;
type Answer = Extract<AgentEvent, { type: "answer" }>;

const TOOL_NAMES: Record<string, string> = {
  get_machine_report: "Makine raporu",
  get_telemetry_summary: "Sensör özeti",
  get_recent_errors: "Hata kayıtları",
  rank_machines_by_risk: "Riske göre sıralama",
  search_manual: "Kılavuz araması",
  draft_work_order: "İş emri taslağı",
};

function parseArgs(raw: string): Record<string, unknown> {
  try {
    const v = JSON.parse(raw || "{}");
    return v && typeof v === "object" ? v : {};
  } catch {
    return {};
  }
}

function callTitle(tool: string, a: Record<string, unknown>): string {
  const name = TOOL_NAMES[tool] ?? tool;
  if (tool === "search_manual") return `${name}: “${a.query ?? ""}”`;
  if (tool === "rank_machines_by_risk") return name;
  if (a.machine_id != null) return `${name}, makine ${a.machine_id}`;
  return name;
}

// Araç çıktısının tek satırlık özeti; ayrıntı "Ham çıktı" altında.
function resultLine(tool: string, r: Record<string, unknown>): string {
  if (typeof r.hata === "string") return r.hata;
  if (tool === "get_machine_report") {
    const risk = r.risk as { ariza_riski_24_saat_yuzde: number; en_olasi_bilesen: string; bilesen_adi: string };
    const off = (r.normalden_belirgin_sapan as string[]) ?? [];
    return `Risk %${fmt(risk.ariza_riski_24_saat_yuzde)}, en olası ${risk.en_olasi_bilesen} (${risk.bilesen_adi})${
      off.length ? `; normalden sapan: ${off.join(", ")}` : ""
    }`;
  }
  if (tool === "search_manual") {
    const s = (r.sonuclar as { bolum: string }[]) ?? [];
    return s.length ? s.map((x) => x.bolum).join("; ") : "Eşleşen bölüm yok";
  }
  if (tool === "draft_work_order") {
    const o = r.is_emri as WorkOrder;
    return `Taslak #${o.id} hazırlandı, onay bekliyor`;
  }
  if (tool === "rank_machines_by_risk") {
    const m = (r.makineler as { machine_id: number; ariza_riski_yuzde: number }[]) ?? [];
    return m.map((x) => `${x.machine_id} (%${fmt(x.ariza_riski_yuzde)})`).join(", ");
  }
  if (tool === "get_recent_errors") return `${r.toplam_hata ?? 0} hata kaydı`;
  if (tool === "get_telemetry_summary") {
    const off = (r.normalden_belirgin_sapan as string[]) ?? [];
    return off.length ? `Normalden sapan: ${off.join(", ")}` : "Bütün sensörler normal aralıkta";
  }
  return "Tamamlandı";
}

type Props = {
  machineId: number | null;
  llmName: string;
  liveLeft: number | null; // bugün kalan canlı soru; null: sınır yok
  onOrdersChanged: () => void;
  onLiveRunFinished: () => void;
  onSelectMachine?: (id: number) => void; // kayıt bir makine hakkındaysa ortadaki görünüm o makineye geçer
};

// "Makine 20 ..." sorusunun makine numarası; filo soruları için null
const machineOf = (q: string) => Number(/Makine (\d+)/.exec(q)?.[1] ?? NaN) || null;

export function AgentPanel({ machineId, llmName, liveLeft, onOrdersChanged, onLiveRunFinished, onSelectMachine }: Props) {
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState<string | null>(null);
  const [steps, setSteps] = useState<Step[]>([]);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [orders, setOrders] = useState<WorkOrder[]>([]);
  const [running, setRunning] = useState(false);
  const [replay, setReplay] = useState<Replay | null>(null);
  const [examples, setExamples] = useState<Example[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Yeni adım geldikçe panelin kendi içinde en alta kaydır. Sayfanın tamamını kaydırmaz.
  // Not: useEffect içinden bir değer döndürmemek için gövde süslü parantezli.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && asked) el.scrollTop = el.scrollHeight;
  }, [steps, answer, orders, asked]);

  useEffect(() => {
    api.examples().then(setExamples).catch(() => setExamples([]));
  }, []);

  // Panel kapanırsa (sayfa değişirse) süren isteği iptal et.
  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  function handle(e: AgentEvent) {
    switch (e.type) {
      case "tool_call":
        setSteps((s) => [...s, { kind: "tool", tool: e.tool, args: parseArgs(e.arguments) }]);
        break;
      case "tool_result":
        setSteps((s) => {
          const copy = [...s];
          for (let i = copy.length - 1; i >= 0; i--) {
            const st = copy[i];
            if (st.kind === "tool" && st.tool === e.tool && !st.result) {
              copy[i] = { ...st, result: e.result, ms: e.ms };
              break;
            }
          }
          return copy;
        });
        if (e.tool === "draft_work_order" && e.result.is_emri) {
          const order = e.result.is_emri as WorkOrder;
          setOrders((o) => [...o.filter((x) => x.id !== order.id), order]);
          onOrdersChanged();
        }
        break;
      case "nudge":
        setSteps((s) => [...s, { kind: "nudge", missing: e.missing }]);
        break;
      case "waiting":
        setSteps((s) => [...s, { kind: "waiting", seconds: e.seconds }]);
        break;
      case "tool_error":
        setSteps((s) => [...s, { kind: "tool_error", message: e.message }]);
        break;
      case "revise":
        setSteps((s) => [
          ...s,
          { kind: "revise", numbers: e.sayilar ?? [], units: e.birimler ?? [], sections: e.eksik_bolumler ?? [] },
        ]);
        break;
      case "replay":
        setReplay(e);
        break;
      case "answer":
        setAnswer(e);
        break;
      case "error":
        setSteps((s) => [...s, { kind: "error", message: e.message }]);
        break;
    }
  }

  async function start(text: string, go: (signal: AbortSignal) => Promise<void>, live: boolean) {
    if (running) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setAsked(text);
    setSteps([]);
    setAnswer(null);
    setOrders([]);
    setReplay(null);
    setRunning(true);
    try {
      await go(controller.signal);
    } catch (e) {
      handle({ type: "error", message: (e as ApiError).message });
    } finally {
      setRunning(false);
      if (live) onLiveRunFinished();
    }
  }

  function ask(q: string) {
    const text = q.trim();
    if (!text) return;
    setQuestion("");
    start(text, (signal) => askAgent(text, handle, signal), true);
  }

  function play(ex: Example) {
    const m = machineOf(ex.question);
    if (m !== null) onSelectMachine?.(m);
    start(ex.question, (signal) => replayExample(ex.id, handle, signal), false);
  }

  // Öneriler: seçili makinenin ve filonun kayıtlı örnekleri anında oynatılır; kaydı olmayan makine için canlı soru.
  // Statik demoda canlı soru yok; bütün kayıtlar gösterilir, seçili makineninki başta.
  const recorded = STATIC_DEMO
    ? [...examples].sort((a, b) => Number(machineOf(b.question) === machineId) - Number(machineOf(a.question) === machineId))
    : examples.filter((ex) => machineOf(ex.question) === null || machineOf(ex.question) === machineId);
  const live =
    !STATIC_DEMO && machineId != null && !recorded.some((ex) => machineOf(ex.question) === machineId)
      ? [`Makine ${machineId} neden riskli, ne yapmalıyım?`]
      : [];
  const outOfLive = liveLeft === 0;
  const toolCount = steps.filter((s) => s.kind === "tool").length;

  return (
    <section aria-labelledby="agent-title" className="flex min-h-0 flex-col">
      <div className="flex items-baseline justify-between border-b border-line px-4 pt-4 pb-3">
        <h2 id="agent-title" className="font-cond text-lg font-semibold">
          Bakım ajanı
        </h2>
        <span className="text-xs text-ink-3">{llmName}</span>
      </div>

      <div ref={scrollRef} className="scroll-quiet min-h-0 flex-1 overflow-y-auto px-4 py-4" aria-live="polite">
        {!asked && (
          <div className="text-sm text-ink-2">
            <p className="max-w-[40ch]">
              Ajan makinenin verisine ve bakım kılavuzuna bakarak cevap verir. Risk yüksekse iş emri taslağı hazırlar;
              taslak senin onayın olmadan uygulanmaz.
            </p>
            {STATIC_DEMO && (
              <p className="mt-3 max-w-[40ch]">
                Bu demoda ajanın gerçek çalıştırmalarının kayıtları oynatılır. Aşağıdan bir soru seç; çıkan iş emri
                taslağını onaylayabilir ya da reddedebilirsin.
              </p>
            )}
          </div>
        )}

        {asked && (
          <p className="mb-4 rounded-md bg-raised px-3 py-2 text-sm">
            <span className="text-ink-3">Soru: </span>
            {asked}
          </p>
        )}

        {replay && (
          <p className="mb-4 rounded-md border border-line px-3 py-2 text-xs text-ink-2">
            Kayıtlı çalıştırma: {dayTime(replay.recorded_at.replace("T", " "))} tarihinde {replay.llm} ile yapılmış
            gerçek bir çalıştırmanın kaydı. Canlı değil; adımlar arası beklemeler kısaltıldı.
          </p>
        )}

        {steps.length > 0 && (
          <ol className="relative mb-4 space-y-3 border-l border-line pl-4 text-sm">
            {steps.map((s, i) => (
              <li key={i} className="relative">
                <StepDot step={s} />
                <StepBody step={s} />
              </li>
            ))}
          </ol>
        )}

        {running && !answer && (
          <p className="mb-4 text-sm text-ink-3">{steps.length ? "Ajan çalışıyor…" : "Ajan soruyu okuyor…"}</p>
        )}

        {answer && (
          <div className="mb-4">
            <div className="agent-answer space-y-2 text-[15px] leading-relaxed">
              <Markdown
                components={{
                  p: (p) => <p className="text-ink-2" {...p} />,
                  strong: (p) => <strong className="font-semibold text-ink" {...p} />,
                  ul: (p) => <ul className="list-disc space-y-1 pl-5 text-ink-2 marker:text-ink-3" {...p} />,
                  ol: (p) => <ol className="list-decimal space-y-1 pl-5 text-ink-2 marker:text-ink-3" {...p} />,
                  a: ({ children }) => <span>{children}</span>,
                }}
              >
                {answer.content}
              </Markdown>
            </div>
            <p className="tnum mt-3 text-xs text-ink-3">
              {toolCount} araç çağrısı, {fmt(answer.tokens)} token, {fmt(answer.seconds)} sn
              {answer.stopped_early ? ", adım sınırında durdu" : ""}
            </p>
          </div>
        )}

        <div className="space-y-3">
          {orders.map((o) => (
            <WorkOrderCard
              key={o.id}
              order={o}
              onChange={(u) => {
                setOrders((all) => all.map((x) => (x.id === u.id ? u : x)));
                onOrdersChanged();
              }}
            />
          ))}
        </div>
      </div>

      <div className="border-t border-line p-4">
        <div className="mb-2 flex flex-wrap gap-1.5">
          {recorded.map((ex) => (
            <button
              key={ex.id}
              type="button"
              disabled={running}
              onClick={() => play(ex)}
              title="Gerçek bir çalıştırmanın kaydı; anında oynatılır"
              className="rounded-full border border-line px-2.5 py-1 text-left text-xs text-ink-2 hover:border-line-strong hover:text-ink disabled:opacity-40"
            >
              {ex.question}
              <span className="ml-1.5 rounded bg-raised px-1 py-px text-[10px] text-ink-3">kayıt</span>
            </button>
          ))}
          {live.map((q) => (
            <button
              key={q}
              type="button"
              disabled={running || outOfLive}
              onClick={() => ask(q)}
              className="rounded-full border border-line px-2.5 py-1 text-left text-xs text-ink-2 hover:border-line-strong hover:text-ink disabled:opacity-40"
            >
              {q}
            </button>
          ))}
        </div>
        {STATIC_DEMO ? (
          <p className="text-xs text-ink-3">
            Bu yayında canlı soru yok (ücretsiz yayın, LLM kotası ayrılmadı). Kendi sorunu sormak için projeyi
            yerelde çalıştır:{" "}
            <a href={REPO_URL} target="_blank" rel="noreferrer" className="text-ink-2 underline hover:text-ink">
              GitHub
            </a>
            .
          </p>
        ) : (
          <>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                ask(question);
              }}
              className="flex items-end gap-2"
            >
              <label htmlFor="agent-question" className="sr-only">
                Ajana soru
              </label>
              <textarea
                id="agent-question"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    ask(question);
                  }
                }}
                rows={2}
                maxLength={500}
                placeholder="Bir makine hakkında sor"
                className="min-h-[44px] flex-1 resize-none rounded-md border border-line bg-page px-3 py-2 text-sm placeholder:text-ink-3"
              />
              <button
                type="submit"
                disabled={running || !question.trim() || outOfLive}
                className="h-[44px] rounded-md bg-ink px-4 font-semibold text-page hover:bg-white disabled:opacity-40"
              >
                {running ? "Çalışıyor" : "Sor"}
              </button>
            </form>
            {liveLeft !== null && (
              <p className="mt-2 text-xs text-ink-3">
                {outOfLive
                  ? "Bugünkü canlı soru hakkı doldu; kayıtlı örnekleri izleyebilirsin."
                  : `Bugün kalan canlı soru: ${liveLeft}. Kayıtlı örnekler bu hakkı kullanmaz.`}
              </p>
            )}
          </>
        )}
      </div>
    </section>
  );
}

function StepDot({ step }: { step: Step }) {
  const pending = step.kind === "tool" && !step.result;
  const failed = step.kind === "error" || (step.kind === "tool" && typeof step.result?.hata === "string");
  const color = failed
    ? "bg-critical"
    : step.kind === "nudge" || step.kind === "waiting" || step.kind === "revise" || step.kind === "tool_error"
      ? "bg-warning"
      : pending
        ? "bg-trace pulse"
        : "bg-ink-3";
  return <span className={`absolute top-1.5 -left-[21px] h-2.5 w-2.5 rounded-full ring-4 ring-panel ${color}`} />;
}

function StepBody({ step }: { step: Step }) {
  if (step.kind === "nudge")
    return (
      <div>
        <p className="text-ink">Adım kontrolü devreye girdi</p>
        <p className="text-ink-2">
          Ajan eksik adımla cevap vermeye çalıştı; şunları tamamlaması istendi:{" "}
          {Object.entries(step.missing)
            .map(([m, tools]) => `makine ${m}: ${tools.map((t) => TOOL_NAMES[t] ?? t).join(", ")}`)
            .join("; ")}
        </p>
      </div>
    );
  if (step.kind === "tool_error")
    return (
      <div>
        <p className="text-ink">Araç çağrısı reddedildi</p>
        <p className="text-ink-2">Model şemaya uymayan bir çağrı üretti; hata modele geri verildi.</p>
      </div>
    );
  if (step.kind === "revise")
    return (
      <div>
        <p className="text-ink">Cevap doğrulaması devreye girdi</p>
        <p className="text-ink-2">
          İlk cevap gösterilmeden düzelttirildi.
          {step.numbers.length > 0 && ` Araç çıktısında olmayan sayılar: ${step.numbers.map(fmt).join("; ")}.`}
          {step.units.length > 0 && ` Veride olmayan birimler: ${step.units.join(", ")}.`}
          {step.sections.length > 0 && ` Eksik bölüm: ${step.sections.join(", ")}.`}
        </p>
      </div>
    );
  if (step.kind === "waiting")
    return <p className="text-ink-2">Groq kullanım sınırı: {fmt(step.seconds)} sn bekleniyor</p>;
  if (step.kind === "error")
    return (
      <p className="flex items-start gap-1.5 text-ink">
        <span className="mt-1">
          <LevelIcon level="acil" />
        </span>
        {step.message}
      </p>
    );

  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-ink">{callTitle(step.tool, step.args)}</p>
        {step.ms != null && <span className="tnum shrink-0 text-xs text-ink-3">{fmt(step.ms)} ms</span>}
      </div>
      {step.result && (
        <>
          <p className={typeof step.result.hata === "string" ? "text-ink" : "text-ink-2"}>
            {resultLine(step.tool, step.result)}
          </p>
          <details className="mt-1">
            <summary className="cursor-pointer text-xs text-ink-3 hover:text-ink-2">Ham çıktı</summary>
            <pre className="scroll-quiet mt-1 max-h-56 overflow-auto rounded bg-page p-2 text-xs leading-snug text-ink-2">
              {JSON.stringify(step.result, null, 2)}
            </pre>
          </details>
        </>
      )}
    </div>
  );
}
