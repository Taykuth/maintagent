"""Ajan değerlendirmesi: geçmişteki gerçek anlara dönüp ajana soru sorar, cevabı gerçekle karşılaştırır.

Senaryolar test döneminden (Ağustos-Aralık 2015) seçilir; risk modeli bu dönemi eğitimde görmedi.
Ajan her senaryoda "şu an" olarak o anı görür, sonrasını göremez.

Senaryo türleri:
  - ariza:            gerçek bir arızadan 3, 12 ya da 21 saat önce. Beklenen: doğru bileşen ve iş emri taslağı.
  - hatali_arizasiz:  son 24 saatte hata kaydı var ama sonraki 72 saatte arıza yok. Zor negatif;
                      yanlış alarm burada çıkar.
  - sakin:            son 24 saatte hata yok, sonraki 72 saatte arıza yok.

Ölçütler:
  - bileşen doğruluğu (arıza senaryolarında), risk modelinin kendi tahminiyle karşılaştırmalı.
    Model bu veri setinde çok güçlü olduğu için bu ölçüt çoğunlukla modeli ölçer; ajanın kendi
    katkısı "modelin bileşenini doğru aktardı mı" ve aşağıdaki davranış ölçütlerinde görünür
  - iş emri kararı: arızada taslak açıldı mı, arızasızda açılmadı mı (yanlış alarm)
  - sayı dayanağı: cevaptaki her sayı araç çıktılarında geçiyor mu (uydurma sayı kontrolü)
  - birim uydurma, cevap biçimi, adım kontrolünün devreye girme oranı, token ve süre
"""

import json
import random
import re
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd

from maintagent.agent import LLM, evidence, run_agent
from maintagent.grounding import invented_units, missing_sections, numbers_in_text, ungrounded_numbers
from maintagent.manual import ManualSearch, component_specs
from maintagent.tools import Toolbox
from maintagent.work_orders import WorkOrderStore

TEST_START = datetime(2015, 8, 2)
TEST_END = datetime(2015, 12, 31)
LEAD_HOURS = (3, 12, 21)
QUESTION = "Makine {machine_id} için durum nedir, ne yapmalıyım?"  # bilerek yönlendirmesiz: "riskli" demiyor

# --- Senaryolar ------------------------------------------------------------------

def make_scenarios(con: duckdb.DuckDBPyConnection, n_failure: int = 12, n_error_no_failure: int = 6,
                   n_quiet: int = 6, seed: int = 0, start: datetime = TEST_START, end: datetime = TEST_END) -> list[dict]:
    """Tekrarlanabilir (seed) senaryo listesi üretir."""
    rng = random.Random(seed)
    fails = con.execute("SELECT machine_id, ts, comp FROM failures ORDER BY ts, machine_id, comp").df()
    errors = con.execute("SELECT machine_id, ts FROM errors ORDER BY ts, machine_id").df()
    machines = [int(m) for (m,) in con.execute("SELECT machine_id FROM machines ORDER BY 1").fetchall()]
    lo, hi = start + timedelta(days=2), end - timedelta(days=3)
    used: set[tuple[int, datetime]] = set()

    def failures_between(m: int, a: datetime, b: datetime) -> list[str]:
        f = fails[(fails.machine_id == m) & (fails.ts > a) & (fails.ts <= b)]
        return sorted(set(f.comp))

    def errors_between(m: int, a: datetime, b: datetime) -> int:
        return int(((errors.machine_id == m) & (errors.ts > a) & (errors.ts <= b)).sum())

    scenarios: list[dict] = []

    # 1) Arızadan önce: bileşenlere dengeli dağıt
    events = fails[(fails.ts > lo) & (fails.ts <= hi)][["machine_id", "ts"]].drop_duplicates()
    events = events.sample(frac=1, random_state=seed).itertuples(index=False)
    by_comp: dict[str, list] = {}
    for m, ts in events:
        for c in failures_between(int(m), ts - timedelta(seconds=1), ts):
            by_comp.setdefault(c, []).append((int(m), ts.to_pydatetime()))
    comps = sorted(by_comp)
    i = 0
    while len([s for s in scenarios if s["tur"] == "ariza"]) < n_failure and any(by_comp.values()):
        comp = comps[i % len(comps)]
        i += 1
        if not by_comp[comp]:
            continue
        m, f_ts = by_comp[comp].pop()
        lead = LEAD_HOURS[len(scenarios) % len(LEAD_HOURS)]
        as_of = f_ts - timedelta(hours=lead)
        if (m, as_of) in used:
            continue
        used.add((m, as_of))
        scenarios.append({"id": f"a{len(scenarios) + 1:02d}", "tur": "ariza", "machine_id": m, "as_of": str(as_of),
                          "saat_once": lead, "gercek_bilesenler": failures_between(m, as_of, as_of + timedelta(hours=24))})

    # 2) Hata kaydı var, arıza yok (zor negatifler)
    candidates = errors[(errors.ts > lo) & (errors.ts <= hi)].sample(frac=1, random_state=seed)
    count = 0
    for m, e_ts in candidates.itertuples(index=False):
        if count >= n_error_no_failure:
            break
        m, e_ts = int(m), e_ts.to_pydatetime()
        as_of = e_ts.replace(minute=0, second=0) + timedelta(hours=(3 - e_ts.hour % 3) % 3)
        if (m, as_of) in used or failures_between(m, as_of - timedelta(hours=48), as_of + timedelta(hours=72)):
            continue
        used.add((m, as_of))
        count += 1
        scenarios.append({"id": f"h{count:02d}", "tur": "hatali_arizasiz", "machine_id": m, "as_of": str(as_of),
                          "saat_once": None, "gercek_bilesenler": []})

    # 3) Sakin anlar
    slots = int((hi - lo).total_seconds() // (3 * 3600))
    count, tries = 0, 0
    while count < n_quiet and tries < 10_000:
        tries += 1
        m = rng.choice(machines)
        as_of = lo + timedelta(hours=3 * rng.randrange(slots))
        if (m, as_of) in used or errors_between(m, as_of - timedelta(hours=24), as_of) \
                or failures_between(m, as_of - timedelta(hours=48), as_of + timedelta(hours=72)):
            continue
        used.add((m, as_of))
        count += 1
        scenarios.append({"id": f"s{count:02d}", "tur": "sakin", "machine_id": m, "as_of": str(as_of),
                          "saat_once": None, "gercek_bilesenler": []})
    return scenarios


# --- Puanlama --------------------------------------------------------------------

def predicted_component(answer: str, steps: list[dict]) -> str | None:
    """Ajanın işaret ettiği bileşen: önce açtığı taslak, yoksa cevaptaki 'Durum' satırı."""
    for s in steps:
        if s["tool"] == "draft_work_order" and "is_emri" in s["result"]:
            return s["result"]["is_emri"]["component"]
    status = next((line for line in answer.splitlines() if "Durum" in line), answer)
    m = re.search(r"comp[1-4]", status) or re.search(r"comp[1-4]", answer)
    return m.group(0) if m else None


def _part_in_manual(part: str, manual_parts: list[str]) -> bool:
    """Parça kılavuzda geçiyor mu? Stok kodu ya da adıyla eşleşme yeter ("GU-01" = "güç ünitesi (stok kodu GU-01)")."""
    norm = lambda x: re.sub(r"\(.*?\)|stok kodu", "", x.lower()).strip()  # noqa: E731
    code = re.search(r"[A-Z]{2}-\d{2}", part)
    return any((code and code.group(0) in m) or (norm(part) and (norm(part) in norm(m) or norm(m) in norm(part)))
               for m in manual_parts)


def draft_checks(steps: list[dict], specs: dict) -> dict:
    """İş emri taslağındaki süre ve parçalar kılavuzla aynı mı? Taslak yoksa None.

    v2'ye kadar kontroller sadece cevap metnine bakıyordu; uydurma süre ve parça taslakta kalabiliyordu.
    """
    draft = next((s["result"]["is_emri"] for s in steps
                  if s["tool"] == "draft_work_order" and isinstance(s["result"].get("is_emri"), dict)), None)
    if draft is None or draft.get("component") not in specs:
        return {"taslak_sure_dogru": None, "taslak_parca_dogru": None}
    spec = specs[draft["component"]]
    hours, parts = draft.get("estimated_hours"), draft.get("parts") or []
    return {"taslak_sure_dogru": hours is not None and abs(float(hours) - spec["saat"]) < 1e-9,
            "taslak_parca_dogru": bool(parts) and all(_part_in_manual(str(x), spec["parcalar"]) for x in parts)}


def score(sc: dict, question: str, result, events: list[dict], model_pred: dict, specs: dict | None = None) -> dict:
    as_of = datetime.fromisoformat(sc["as_of"])
    drafts = [s for s in result.steps if s["tool"] == "draft_work_order" and "is_emri" in s["result"]]
    comp = predicted_component(result.answer, result.steps)
    positive = sc["tur"] == "ariza"
    extra = {float(sc["machine_id"]), float(as_of.year), float(as_of.month), float(as_of.day), float(as_of.hour)}
    extra |= set(numbers_in_text(question))
    revise = next((e for e in events if e["type"] == "revise"), None)
    return {
        **sc,
        "model_risk": model_pred["ariza_riski_24_saat_yuzde"],
        "model_bilesen": model_pred["en_olasi_bilesen"],
        "ajan_bilesen": comp,
        "taslak": bool(drafts),
        "bilesen_dogru": (comp in sc["gercek_bilesenler"]) if positive else None,
        "model_bilesen_dogru": (model_pred["en_olasi_bilesen"] in sc["gercek_bilesenler"]) if positive else None,
        "yanlis_alarm": None if positive else bool(drafts),
        # Son cevaptaki sorunlar (doğrulama düzelttikten sonra kalanlar)
        "dayanaksiz_sayilar": ungrounded_numbers(result.answer, evidence(result.steps), extra),
        "uydurma_birim": invented_units(result.answer),
        "bicim_ok": not missing_sections(result.answer),
        # Doğrulamanın ilk cevapta yakaladıkları
        "dogrulama": {k: v for k, v in (revise or {}).items() if k != "type"},
        "adim_kontrolu": any(e["type"] == "nudge" for e in events),
        "arac_reddi": sum(e["type"] == "tool_error" for e in events),  # sağlayıcının reddettiği araç çağrıları
        "bekleme_sn": sum(e["seconds"] for e in events if e["type"] == "waiting"),
        "arac_sayisi": len(result.steps),
        "token": result.tokens,
        "sure_sn": round(result.seconds, 1),
        "durdu": result.stopped_early,
        "cevap": result.answer,
        **draft_checks(result.steps, specs or {}),
        # Sonradan yeniden puanlayabilmek için araç çıktıları da saklanır
        "araclar": [{"tool": s["tool"], "arguments": s["arguments"], "result": s["result"]} for s in result.steps],
    }


def run_scenario(sc: dict, con: duckdb.DuckDBPyConnection, model_dir: Path, manual: ManualSearch, llm: LLM,
                 model=None, sleep=None) -> dict:
    """Tek senaryo: o ana dön, ajana sor, puanla. İş emirleri senaryoya özel, bellekte tutulur."""
    as_of = datetime.fromisoformat(sc["as_of"])
    toolbox = Toolbox(con, model_dir, as_of, manual=manual, orders=WorkOrderStore(":memory:"), model=model)
    question = QUESTION.format(machine_id=sc["machine_id"])
    events: list[dict] = []
    kwargs = {"sleep": sleep} if sleep else {}
    result = run_agent(question, toolbox, llm, on_event=events.append, **kwargs)
    model_pred = toolbox.predict_failure_risk(sc["machine_id"])  # aynı anda modelin kendi tahmini (LLM'siz)
    return score(sc, question, result, events, model_pred, component_specs(manual.chunks))


# --- Özet ------------------------------------------------------------------------

def _rate(part: int, whole: int) -> str:
    return f"{part}/{whole} (%{round(100 * part / whole)})" if whole else "-"


def summarize(records: list[dict], specs: dict | None = None) -> str:
    """Özet tablo. specs verilirse eski kayıtların taslak kontrolleri saklanan araç çıktılarından hesaplanır."""
    if specs:
        records = [{**r, **draft_checks(r.get("araclar", []), specs)} if "taslak_sure_dogru" not in r else r
                   for r in records]
    drafted = [r for r in records if r.get("taslak_sure_dogru") is not None]
    pos = [r for r in records if r["tur"] == "ariza"]
    hard = [r for r in records if r["tur"] == "hatali_arizasiz"]
    quiet = [r for r in records if r["tur"] == "sakin"]
    risky = [r for r in records if r["model_risk"] >= 50]  # modelin alarm verdiği anlar
    tokens = sorted(r["token"] for r in records)
    rows = [
        ("Senaryo", f"{len(records)} ({len(pos)} arıza, {len(hard)} hatalı-arızasız, {len(quiet)} sakin)"),
        ("Bileşen doğru (ajan)", _rate(sum(r["bilesen_dogru"] for r in pos), len(pos))),
        ("Bileşen doğru (sadece risk modeli)", _rate(sum(r["model_bilesen_dogru"] for r in pos), len(pos))),
        ("Ajan, modelin bileşenini doğru aktardı", _rate(sum(r["ajan_bilesen"] == r["model_bilesen"] for r in risky),
                                                         len(risky))),
        ("Arızada iş emri taslağı açıldı", _rate(sum(r["taslak"] for r in pos), len(pos))),
        ("Taslakta süre kılavuzla aynı", _rate(sum(r["taslak_sure_dogru"] for r in drafted), len(drafted))),
        ("Taslaktaki parçalar kılavuzda var", _rate(sum(r["taslak_parca_dogru"] for r in drafted), len(drafted))),
        ("Yanlış alarm: hatalı-arızasız", _rate(sum(r["yanlis_alarm"] for r in hard), len(hard))),
        ("Yanlış alarm: sakin", _rate(sum(r["yanlis_alarm"] for r in quiet), len(quiet))),
        ("Doğrulama ilk cevabı düzelttirdi", _rate(sum(bool(r.get("dogrulama")) for r in records), len(records))),
        ("Dayanaksız sayı içeren cevap (son hâli)",
         _rate(sum(bool(r["dayanaksiz_sayilar"]) for r in records), len(records))),
        ("Uydurma birim içeren cevap (son hâli)", _rate(sum(bool(r["uydurma_birim"]) for r in records), len(records))),
        ("Biçime uyan cevap (son hâli)", _rate(sum(r["bicim_ok"] for r in records), len(records))),
        ("Adım kontrolü devreye girdi", _rate(sum(r["adim_kontrolu"] for r in records), len(records))),
        ("Araç çağrısı şemaya uymadı (en az bir kez)",
         _rate(sum(bool(r.get("arac_reddi")) for r in records), len(records))),
        ("Adım sınırında durdu", _rate(sum(r["durdu"] for r in records), len(records))),
        ("Ortalama araç çağrısı", f"{sum(r['arac_sayisi'] for r in records) / max(len(records), 1):.1f}"),
        ("Token (medyan / en çok)", f"{tokens[len(tokens) // 2]:,} / {tokens[-1]:,}" if tokens else "-"),
        ("Süre, bekleme hariç (medyan sn)",
         f"{sorted(r['sure_sn'] - r['bekleme_sn'] for r in records)[len(records) // 2]:.1f}" if records else "-"),
    ]
    lines = ["| Ölçüt | Sonuç |", "|---|---|", *[f"| {k} | {v} |" for k, v in rows]]
    return "\n".join(lines)


def load_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_record(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def to_frame(records: list[dict]) -> pd.DataFrame:
    """İnceleme için: her senaryo bir satır."""
    cols = ["id", "tur", "machine_id", "as_of", "saat_once", "gercek_bilesenler", "model_risk", "model_bilesen",
            "ajan_bilesen", "taslak", "dayanaksiz_sayilar", "adim_kontrolu", "arac_sayisi", "token"]
    return pd.DataFrame(records)[cols] if records else pd.DataFrame(columns=cols)
