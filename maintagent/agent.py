"""Ajan döngüsü. LangChain gibi bir çerçeve kullanmadan, açıkça yazıldı.

Döngü:
  1. Soruyu ve araç tanımlarını LLM'e gönder.
  2. LLM araç çağırmak isterse aracı çalıştır, sonucu mesajlara ekle, 1'e dön.
  3. LLM araç çağırmadan cevap verirse dur.

Güvenlik önlemleri:
  - En fazla MAX_STEPS LLM turu; sonsuz döngüye girmez.
  - Bilinmeyen araç, bozuk argüman ya da araç hatası programı çökertmez;
    hata mesajı LLM'e geri verilir ve LLM düzeltme şansı bulur.
  - Kanıt kontrolü: LLM bir makinenin riskine bakıp sensör, hata ve bakım
    verisine bakmadan cevap vermeye kalkarsa, döngü cevabı bir kez geri çevirir
    ve eksik araçları söyler. Prompt'a güvenmek yetmedi; ilk denemede model
    tek araçla cevap verdi.
  - Her adım `on_event` ile dışarı bildirilir; arayüz bunları canlı gösterir.
"""

import json
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

from maintagent.tools import TOOL_SCHEMAS, Toolbox

MAX_STEPS = 10

# Bir makinenin riskini açıklamadan önce toplanması gereken kanıt.
EVIDENCE_TOOLS = ("get_telemetry_summary", "get_recent_errors", "get_maintenance_history")

SYSTEM_PROMPT = """Sen bir fabrikada bakım mühendislerine yardım eden bir yapay zeka asistanısın.
Şu anki tarih ve saat: {as_of}. Bu andan sonrasını bilemezsin.

Kurallar:
- Bilgiyi her zaman araçlardan al. Araç çıktısında olmayan hiçbir sayıyı yazma.
- Bir makinenin riskini açıklarken şu araçların hepsini çağır: predict_failure_risk,
  get_telemetry_summary, get_recent_errors, get_maintenance_history ve search_manual. Tek araçla cevap verme.
- search_manual ile en olası bileşenin kontrol adımlarına, değişim süresine ve parçalarına bak.
  Öneriyi kılavuza dayandır ve hangi bölümden aldığını yaz (ör. "Kılavuz: comp2 — Ana mil rulmanı › Kontrol adımları").
- Bileşeni hem kodu hem adıyla yaz (ör. "comp2 (ana mil rulmanı)").
- Sensör değerini çıplak yazma; makinenin normaliyle karşılaştır (ör. "dönüş hızı normalin %16 altında").
- Öneri yalnızca kanıta dayansın. Sensördeki sapma çoğunlukla bileşendeki sorunun belirtisidir;
  sensörün bozuk olduğuna dair kanıt yoksa kalibrasyon ya da sensör değişimi önerme.
- Emin olmadığın şeyi söyle; tahmin yürütüyorsan bunu belirt.
- Türkçe ve kısa yaz.

Cevap biçimi:
**Durum:** tek cümle özet.
**Kanıt:** araçlardan gelen 3-5 madde, her birinde sayı.
**Öneri:** kılavuza dayanan somut adımlar, tahmini süre ve parça; sonunda kaynak bölüm."""


class LLM(Protocol):
    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        """{"content": str, "tool_calls": [{"id", "name", "arguments"}]} döndürür."""


class GroqLLM:
    """OpenAI uyumlu herhangi bir API ile çalışır (Groq, OpenAI)."""

    def __init__(self, api_key: str, model: str, base_url: str):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        r = self.client.chat.completions.create(model=self.model, messages=messages, tools=tools, temperature=0)
        m = r.choices[0].message
        return {"content": m.content or "",
                "tool_calls": [{"id": c.id, "name": c.function.name, "arguments": c.function.arguments}
                               for c in (m.tool_calls or [])]}


@dataclass
class AgentResult:
    answer: str
    steps: list[dict] = field(default_factory=list)
    seconds: float = 0.0
    stopped_early: bool = False


def run_agent(question: str, toolbox: Toolbox, llm: LLM,
              on_event: Callable[[dict], None] | None = None, max_steps: int = MAX_STEPS) -> AgentResult:
    emit = on_event or (lambda e: None)
    t0 = time.perf_counter()
    messages = [{"role": "system", "content": SYSTEM_PROMPT.format(as_of=toolbox.as_of)},
                {"role": "user", "content": question}]
    steps: list[dict] = []
    nudged = False

    for _ in range(max_steps):
        reply = llm.chat(messages, TOOL_SCHEMAS)
        if not reply["tool_calls"]:
            missing = _missing_evidence(steps)
            if missing and not nudged:
                # Cevabı bir kez geri çevir. Tek seferlik: LLM yine araç çağırmazsa
                # sonsuz döngüye girmemek için ikinci cevabı kabul ederiz.
                nudged = True
                emit({"type": "nudge", "missing": missing})
                todo = "; ".join(f"Makine {m}: {', '.join(tools)}" for m, tools in missing.items())
                messages.append({"role": "assistant", "content": reply["content"]})
                messages.append({"role": "user", "content":
                                 f"[Otomatik kontrol] Cevap vermeden önce eksik kanıtı topla: {todo}. "
                                 "Sonra cevabı aynı biçimde yeniden yaz."})
                continue
            emit({"type": "answer", "content": reply["content"]})
            return AgentResult(reply["content"], steps, time.perf_counter() - t0)

        messages.append({"role": "assistant", "content": reply["content"], "tool_calls": [
            {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}}
            for c in reply["tool_calls"]]})

        for call in reply["tool_calls"]:
            emit({"type": "tool_call", "tool": call["name"], "arguments": call["arguments"]})
            started = time.perf_counter()
            result = _execute(toolbox, call["name"], call["arguments"])
            step = {"tool": call["name"], "arguments": call["arguments"], "result": result,
                    "ms": round((time.perf_counter() - started) * 1000)}
            steps.append(step)
            emit({"type": "tool_result", **step})
            messages.append({"role": "tool", "tool_call_id": call["id"],
                             "content": json.dumps(result, ensure_ascii=False, default=str)})

    note = f"{max_steps} adım sınırına ulaşıldı; ajan cevabı tamamlayamadı."
    emit({"type": "answer", "content": note})
    return AgentResult(note, steps, time.perf_counter() - t0, stopped_early=True)


def _machine_id(step: dict) -> int | None:
    try:
        return int(json.loads(step["arguments"] or "{}")["machine_id"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def _missing_evidence(steps: list[dict]) -> dict[int, list[str]]:
    """Riskine bakılan her makine için henüz çağrılmamış kanıt araçlarını döndürür.

    Hata dönen çağrılar kanıt sayılmaz. Riskine bakılmayan makineler (ör. sadece
    "Makine 5 hangi model?" sorusu) kontrol edilmez. Kılavuz araması makineye
    bağlı değildir; bir kez başarılı arama yapılmışsa yeterli sayılır.
    """
    done = {(s["tool"], _machine_id(s)) for s in steps if "hata" not in s["result"]}
    checked = sorted({m for tool, m in done if tool == "predict_failure_risk" and m is not None})
    manual_done = any(tool == "search_manual" for tool, _ in done)
    missing = {m: [t for t in EVIDENCE_TOOLS if (t, m) not in done] + ([] if manual_done else ["search_manual"])
               for m in checked}
    return {m: tools for m, tools in missing.items() if tools}


def _execute(toolbox: Toolbox, name: str, raw_args: str) -> dict:
    allowed = {t["function"]["name"] for t in TOOL_SCHEMAS}
    if name not in allowed:
        return {"hata": f"'{name}' diye bir araç yok. Kullanılabilir araçlar: {sorted(allowed)}"}
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError:
        return {"hata": f"Argümanlar geçerli JSON değil: {raw_args!r}"}
    try:
        return getattr(toolbox, name)(**args)
    except (ValueError, TypeError, RuntimeError) as e:
        return {"hata": str(e)}
