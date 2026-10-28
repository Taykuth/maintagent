"""Ajan döngüsü. LangChain gibi bir çerçeve kullanmadan, açıkça yazıldı.

Döngü:
  1. Soruyu ve araç tanımlarını LLM'e gönder.
  2. LLM araç çağırmak isterse aracı çalıştır, sonucu mesajlara ekle, 1'e dön.
  3. LLM araç çağırmadan cevap verirse dur.

Güvenlik önlemleri:
  - En fazla MAX_STEPS LLM turu; sonsuz döngüye girmez.
  - Bilinmeyen araç, bozuk argüman ya da araç hatası programı çökertmez;
    hata mesajı LLM'e geri verilir ve LLM düzeltme şansı bulur.
  - Adım kontrolü: risk yüksek bir makinede LLM kılavuza bakmadan ya da iş emri
    taslağı hazırlamadan cevap vermeye kalkarsa, döngü cevabı bir kez geri çevirir
    ve eksik adımları söyler. Prompt'a güvenmek yetmedi; ilk denemede model tek
    araçla cevap verdi.
  - Cevap doğrulama: cevapta araç çıktılarında olmayan bir sayı, veride olmayan bir
    birim ya da eksik bölüm varsa, cevap kullanıcıya gösterilmeden bir kez
    düzelttirilir. İlk değerlendirmede cevapların %62'sinde dayanaksız sayı vardı.
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

from maintagent.grounding import invented_units, missing_sections, numbers_in_text, ungrounded_numbers
from maintagent.tools import TOOL_SCHEMAS, Toolbox

MAX_STEPS = 10
DRAFT_RISK_THRESHOLD = 50.0  # kılavuz: risk %50 ve üstü "yüksek" öncelik
MAX_WAIT_SECONDS = 60        # daha uzun bekleme gerekiyorsa (ör. günlük sınır) vazgeç
RATE_LIMIT_RETRIES = 3

# İlk değerlendirmeden sonra eklenen kurallar: düşük riskte prosedür önerme, adım başına süre
# uydurma, hesap yapma. Değerlendirmede bunların hepsi gerçek cevaplarda görüldü.
SYSTEM_PROMPT = """Fabrika bakım mühendislerine yardım eden asistansın. Şu an: {as_of}; sonrasını bilemezsin.
Kurallar:
- Her sayıyı araç çıktısından al; uydurma, hesaplama yapma.
- Bir makine sorulursa önce get_machine_report çağır.
- Risk %{threshold:.0f} veya üstündeyse: search_manual ile en olası bileşenin kontrol adımlarına, süresine ve
  parçalarına bak, sonra draft_work_order ile iş emri taslağı oluştur. Taslak bakım şefinin onayını bekler:
  "iş emri verildi" deme, "taslak hazırlandı, onay bekliyor" de.
- Risk %{threshold:.0f}'nin altındaysa iş emri ve bakım prosedürü önerme; "acil işlem gerekmiyor, planlı bakıma
  devam" de. Belirgin sapan sensör varsa izlenmesini öner.
- Süre olarak sadece kılavuzdaki toplam süreyi yaz; adım başına süre yazma.
- Veride birim yok: sayıların yanına rpm, V, bar, mm/s gibi birim yazma.
- Bileşeni kod ve adıyla yaz: "compN (bileşen adı)". Sensörü normaliyle karşılaştır: "<sensör> normalin %X altında/üstünde".
- Sensör sapması genelde bileşen sorunudur; sensör arızası kanıtı yoksa kalibrasyon önerme.
- Emin değilsen söyle. Türkçe ve kısa yaz.
Biçim:
**Durum:** tek cümle.
**Kanıt:** 3-5 madde, sayılarla.
**Öneri:** yapılacaklar; risk yüksekse kılavuzdaki adımlar, toplam süre, parça, kaynak bölüm ve taslak numarası."""

# Taslağın bu alanlarını LLM yazdı; sayı kontrolünde kanıt sayılmaz (yoksa uydurma süre kendini doğrular).
LLM_WRITTEN_FIELDS = {"reason", "steps", "parts", "estimated_hours", "manual_section", "note", "created_at"}


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
              sleep: Callable[[float], None] = time.sleep, verify_answer: bool = True) -> AgentResult:
    emit = on_event or (lambda e: None)
    t0 = time.perf_counter()
    messages = [{"role": "system", "content": SYSTEM_PROMPT.format(as_of=toolbox.as_of, threshold=draft_threshold)},
                {"role": "user", "content": question}]
    steps: list[dict] = []
    tokens = 0
    nudged = revised = False

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
            problems = answer_problems(question, reply["content"], steps, toolbox.as_of) if verify_answer else {}
            if problems and not revised:
                # Cevap kullanıcıya gitmeden bir kez düzelttirilir; ikinci cevap ne olursa kabul edilir.
                revised = True
                emit({"type": "revise", **problems})
                messages.append({"role": "assistant", "content": reply["content"]})
                messages.append({"role": "user", "content": _revise_message(problems)})
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
    """Riski eşiğin üstünde olan her makine için eksik kalan adımları döndürür.

    Risk yüksekse kılavuz araması ve o makine için iş emri taslağı gerekir. Kılavuz
    araması makineye bağlı değil; bir başarılı arama yeterli. Risk düşükse hiçbir adım
    zorunlu değildir: ilk değerlendirmede bu zorunluluk, sağlam makinelere gereksiz
    bakım prosedürü önermeye yol açtı. Hata dönen çağrılar sayılmaz.
    """
    ok = [(s["tool"], _machine_id(s), s["result"]) for s in steps if "hata" not in s["result"]]
    reported = {m: r["risk"]["ariza_riski_24_saat_yuzde"] for tool, m, r in ok
                if tool == "get_machine_report" and m is not None}
    manual_done = any(tool == "search_manual" for tool, _, _ in ok)
    drafted = {m for tool, m, _ in ok if tool == "draft_work_order"}
    missing = {}
    for m, risk in sorted(reported.items()):
        if risk < draft_threshold:
            continue
        need = [] if manual_done else ["search_manual"]
        if m not in drafted:
            need.append("draft_work_order")
        if need:
            missing[m] = need
    return missing


def evidence(steps: list[dict]) -> list[dict]:
    """Sayı kontrolünde kanıt sayılan araç çıktıları. Taslağın LLM'in yazdığı alanları hariç."""
    out = []
    for s in steps:
        r = s["result"]
        if s["tool"] == "draft_work_order" and isinstance(r.get("is_emri"), dict):
            r = {k: v for k, v in r["is_emri"].items() if k not in LLM_WRITTEN_FIELDS}
        out.append(r)
    return out


def answer_problems(question: str, answer: str, steps: list[dict], as_of) -> dict:
    """Cevaptaki dayanaksız sayılar, uydurma birimler ve eksik bölümler. Sorun yoksa boş sözlük."""
    extra = {float(as_of.year), float(as_of.month), float(as_of.day), float(as_of.hour)}
    extra |= set(numbers_in_text(question))
    problems = {"sayilar": ungrounded_numbers(answer, evidence(steps), extra),
                "birimler": invented_units(answer),
                "eksik_bolumler": missing_sections(answer)}
    return {k: v for k, v in problems.items() if v}


def _revise_message(problems: dict) -> str:
    fmt = lambda x: f"{x:g}".replace(".", ",")  # noqa: E731
    lines = ["[Otomatik kontrol] Cevabı kullanıcıya göstermeden önce düzelt:"]
    if "sayilar" in problems:
        lines.append(f"- Şu sayılar araç çıktılarında yok: {'; '.join(fmt(x) for x in problems['sayilar'])}. "
                     "Bunları çıkar. Süre için sadece kılavuzdaki toplam süreyi yaz.")
    if "birimler" in problems:
        lines.append(f"- Veride birim yok, şunları kaldır: {', '.join(problems['birimler'])}.")
    if "eksik_bolumler" in problems:
        lines.append(f"- Eksik bölüm: {', '.join(problems['eksik_bolumler'])}. Biçim: **Durum:**, **Kanıt:**, **Öneri:**.")
    lines.append("Yeni sayı ekleme; cevabı aynı biçimde yeniden yaz.")
    return "\n".join(lines)


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
