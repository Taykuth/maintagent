"""Ajan döngüsü. LangChain gibi bir çerçeve kullanmadan, açıkça yazıldı.

Döngü:
  1. Soruyu ve araç tanımlarını LLM'e gönder.
  2. LLM araç çağırmak isterse aracı çalıştır, sonucu mesajlara ekle, 1'e dön.
  3. LLM araç çağırmadan cevap verirse dur.

Güvenlik önlemleri:
  - En fazla MAX_STEPS LLM turu; sonsuz döngüye girmez.
  - Bilinmeyen araç, bozuk argüman ya da araç hatası programı çökertmez;
    hata mesajı LLM'e geri verilir ve LLM düzeltme şansı bulur.
  - Adım kontrolü: LLM bir makinenin raporuna bakıp kılavuza bakmadan ya da
    yüksek riskte iş emri taslağı hazırlamadan cevap vermeye kalkarsa, döngü
    cevabı bir kez geri çevirir ve eksik adımları söyler. Prompt'a güvenmek
    yetmedi; ilk denemede model tek araçla cevap verdi.
  - Groq kullanım sınırına (429) takılınca bekler ve bunu arayüze bildirir.
  - Her adım `on_event` ile dışarı bildirilir; arayüz bunları canlı gösterir.

Token bütçesi: Groq ücretsiz katmanında gpt-oss-120b için dakikada 8.000 token
sınırı var. Bu yüzden kanıt tek araçta toplanır (get_machine_report), prompt kısa
tutulur ve araç çıktıları boşluksuz JSON olarak gönderilir.
"""

import json
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

from maintagent.tools import TOOL_SCHEMAS, Toolbox

MAX_STEPS = 10
DRAFT_RISK_THRESHOLD = 50.0  # kılavuz: risk %50 ve üstü "yüksek" öncelik
MAX_WAIT_SECONDS = 60        # daha uzun bekleme gerekiyorsa (ör. günlük sınır) vazgeç
RATE_LIMIT_RETRIES = 3

SYSTEM_PROMPT = """Fabrika bakım mühendislerine yardım eden asistansın. Şu an: {as_of}; sonrasını bilemezsin.
Kurallar:
- Her sayıyı araç çıktısından al, uydurma.
- Bir makine sorulursa önce get_machine_report, sonra en olası bileşen için search_manual (kontrol adımları, süre, parça).
- Risk %{threshold:.0f} veya üstündeyse draft_work_order ile iş emri taslağı oluştur; adım ve parçaları kılavuzdan al.
  Taslak bakım şefinin onayını bekler: "iş emri verildi" deme, "taslak hazırlandı, onay bekliyor" de.
- Bileşeni kod ve adıyla yaz: "comp2 (ana mil rulmanı)". Sensörü normaliyle karşılaştır: "dönüş hızı normalin %16 altında".
- Sensör sapması genelde bileşen sorunudur; sensör arızası kanıtı yoksa kalibrasyon önerme.
- Emin değilsen söyle. Türkçe ve kısa yaz.
Biçim:
**Durum:** tek cümle.
**Kanıt:** 3-5 madde, sayılarla.
**Öneri:** kılavuzdaki adımlar, süre ve parça, kaynak bölüm; taslak hazırlandıysa numarası."""


class LLMError(Exception):
    """Kullanıcıya gösterilebilecek LLM hatası (anahtar yok, bağlantı yok, sınır doldu)."""


class RateLimited(LLMError):
    def __init__(self, wait_seconds: float):
        super().__init__(f"Groq kullanım sınırına ulaşıldı; {wait_seconds:.0f} sn sonra tekrar denenebilir.")
        self.wait_seconds = wait_seconds


class LLM(Protocol):
    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        """{"content": str, "tool_calls": [{"id", "name", "arguments"}], "tokens": int} döndürür."""


class GroqLLM:
    """OpenAI uyumlu herhangi bir API ile çalışır (Groq, OpenAI ve benzerleri)."""

    def __init__(self, api_key: str, model: str, base_url: str, reasoning_effort: str | None = "low"):
        import openai

        if not api_key:
            raise LLMError("GROQ_API_KEY tanımlı değil; .env dosyasını kontrol et.")
        self._openai = openai
        # 429'u kütüphaneye bırakmıyoruz; kendimiz bekleyip arayüze "bekleniyor" diyebilmek için.
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url, max_retries=0)
        self.model = model
        # Düşük akıl yürütme: daha az çıktı tokenı, dakikalık sınıra daha geç takılma.
        self.extra = {"reasoning_effort": reasoning_effort} if reasoning_effort and "gpt-oss" in model else None

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        oa = self._openai
        for attempt in range(2):
            try:
                r = self.client.chat.completions.create(model=self.model, messages=messages, tools=tools,
                                                        temperature=0, extra_body=self.extra)
                break
            except oa.RateLimitError as e:
                raise RateLimited(_retry_after(e)) from e
            except oa.AuthenticationError as e:
                raise LLMError("Groq API anahtarı geçersiz.") from e
            except (oa.APIConnectionError, oa.InternalServerError) as e:
                if attempt == 1:
                    raise LLMError("Groq'a ulaşılamadı; biraz sonra tekrar dene.") from e
                time.sleep(1)
        m = r.choices[0].message
        return {"content": m.content or "",
                "tool_calls": [{"id": c.id, "name": c.function.name, "arguments": c.function.arguments}
                               for c in (m.tool_calls or [])],
                "tokens": r.usage.total_tokens if r.usage else 0}


def _retry_after(error) -> float:
    try:
        return float(error.response.headers.get("retry-after", 10))
    except (AttributeError, TypeError, ValueError):
        return 10.0


@dataclass
class AgentResult:
    answer: str
    steps: list[dict] = field(default_factory=list)
    seconds: float = 0.0
    stopped_early: bool = False
    tokens: int = 0


def run_agent(question: str, toolbox: Toolbox, llm: LLM,
              on_event: Callable[[dict], None] | None = None, max_steps: int = MAX_STEPS,
              draft_threshold: float = DRAFT_RISK_THRESHOLD,
              sleep: Callable[[float], None] = time.sleep) -> AgentResult:
    emit = on_event or (lambda e: None)
    t0 = time.perf_counter()
    messages = [{"role": "system", "content": SYSTEM_PROMPT.format(as_of=toolbox.as_of, threshold=draft_threshold)},
                {"role": "user", "content": question}]
    steps: list[dict] = []
    tokens = 0
    nudged = False

    def finish(answer: str, stopped_early: bool = False) -> AgentResult:
        seconds = time.perf_counter() - t0
        emit({"type": "answer", "content": answer, "tokens": tokens, "seconds": round(seconds, 1),
              "stopped_early": stopped_early})
        return AgentResult(answer, steps, seconds, stopped_early, tokens)

    for _ in range(max_steps):
        reply = _chat_with_retry(llm, messages, emit, sleep)
        tokens += reply.get("tokens", 0)
        if not reply["tool_calls"]:
            missing = _missing_steps(steps, draft_threshold)
            if missing and not nudged:
                # Cevabı bir kez geri çevir. Tek seferlik: LLM yine araç çağırmazsa
                # sonsuz döngüye girmemek için ikinci cevabı kabul ederiz.
                nudged = True
                emit({"type": "nudge", "missing": missing})
                todo = "; ".join(f"Makine {m}: {', '.join(tools)}" for m, tools in missing.items())
                messages.append({"role": "assistant", "content": reply["content"]})
                messages.append({"role": "user", "content":
                                 f"[Otomatik kontrol] Cevap vermeden önce eksik adımları tamamla: {todo}. "
                                 "Sonra cevabı aynı biçimde yeniden yaz."})
                continue
            return finish(reply["content"])

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
            # Boşluksuz JSON: aynı bilgi, daha az token.
            messages.append({"role": "tool", "tool_call_id": call["id"],
                             "content": json.dumps(result, ensure_ascii=False, default=str, separators=(",", ":"))})

    return finish(f"{max_steps} adım sınırına ulaşıldı; ajan cevabı tamamlayamadı.", stopped_early=True)


def _chat_with_retry(llm: LLM, messages: list[dict], emit, sleep) -> dict:
    """Groq dakikalık sınıra takılırsa söylenen süre kadar bekleyip tekrar dener."""
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        try:
            return llm.chat(messages, TOOL_SCHEMAS)
        except RateLimited as e:
            if attempt == RATE_LIMIT_RETRIES or e.wait_seconds > MAX_WAIT_SECONDS:
                raise
            emit({"type": "waiting", "seconds": round(e.wait_seconds, 1)})
            sleep(e.wait_seconds)
    raise AssertionError("buraya ulaşılmamalı")


def _machine_id(step: dict) -> int | None:
    try:
        return int(json.loads(step["arguments"] or "{}")["machine_id"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def _missing_steps(steps: list[dict], draft_threshold: float) -> dict[int, list[str]]:
    """Raporuna bakılan her makine için eksik kalan adımları döndürür.

    - Kılavuz araması makineye bağlı değil; bir başarılı arama yeterli.
    - Risk eşiğin üstündeyse o makine için iş emri taslağı da gerekli.
    Hata dönen çağrılar sayılmaz. Raporuna bakılmayan makineler kontrol edilmez
    (ör. "En riskli 3 makine hangileri?" sorusu).
    """
    ok = [(s["tool"], _machine_id(s), s["result"]) for s in steps if "hata" not in s["result"]]
    reported = {m: r["risk"]["ariza_riski_24_saat_yuzde"] for tool, m, r in ok
                if tool == "get_machine_report" and m is not None}
    manual_done = any(tool == "search_manual" for tool, _, _ in ok)
    drafted = {m for tool, m, _ in ok if tool == "draft_work_order"}
    missing = {}
    for m, risk in sorted(reported.items()):
        need = [] if manual_done else ["search_manual"]
        if risk >= draft_threshold and m not in drafted:
            need.append("draft_work_order")
        if need:
            missing[m] = need
    return missing


def _execute(toolbox: Toolbox, name: str, raw_args: str) -> dict:
    allowed = {t["function"]["name"] for t in TOOL_SCHEMAS}
    if name not in allowed:
        return {"hata": f"'{name}' diye bir araç yok. Kullanılabilir araçlar: {sorted(allowed)}"}
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError:
        return {"hata": f"Argümanlar geçerli JSON değil: {raw_args!r}"}
    if not isinstance(args, dict):
        return {"hata": "Argümanlar bir JSON nesnesi olmalı."}
    try:
        return getattr(toolbox, name)(**args)
    except (ValueError, TypeError, RuntimeError) as e:
        return {"hata": str(e)}
