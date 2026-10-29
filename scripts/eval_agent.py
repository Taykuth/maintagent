"""Ajanı geçmişteki gerçek anlarda sınar ve sonuçları özetler.

Groq ücretsiz katmanında günlük token sınırı var (gpt-oss-120b için 200.000). Bir senaryo
yaklaşık 10.000 token harcadığı için 24 senaryo tek günde bitmeyebilir. Bu yüzden script:
  - her senaryonun sonucunu bitince data/eval/agent_runs.jsonl dosyasına yazar,
  - tekrar çalıştırılınca bitmiş senaryoları atlar, kaldığı yerden devam eder,
  - günlük sınıra takılınca durur ve kaç senaryo kaldığını söyler.

Her ajan sürümü ayrı dosyalara yazılır (--run): agent_runs_<sürüm>.jsonl, agent_summary_<sürüm>.md.
v1: ilk sürüm. v2: düşük riskte prosedür önermeyen prompt ve cevap doğrulaması eklenmiş sürüm.

Kullanım:
    python scripts/eval_agent.py                  # v2, kalan bütün senaryolar
    python scripts/eval_agent.py --limit 5        # en fazla 5 senaryo
    python scripts/eval_agent.py --summary        # sadece özet (LLM çağırmaz)
    python scripts/eval_agent.py --run v1 --summary
    python scripts/eval_agent.py --search bm25    # v1 ile aynı arama; sadece v2 değişiklikleri ölçülür
    python scripts/eval_agent.py --search bm25 --wait   # sınıra takılınca bekleyip kendiliğinden devam eder
    python scripts/eval_agent.py --search bm25 --run v3 --types ariza   # sadece arıza senaryoları
"""

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb  # noqa: E402

from maintagent import config  # noqa: E402
from maintagent.agent import GroqLLM, LLMError, RateLimited  # noqa: E402
from maintagent.evaluation import (append_record, load_records, make_scenarios, run_scenario,  # noqa: E402
                                   summarize, to_frame)
from maintagent.manual import build_search, component_specs, load_chunks  # noqa: E402
from maintagent.model import load  # noqa: E402

EVAL_DIR = config.ROOT_DIR / "data" / "eval"
MAX_SLEEP = 3 * 3600  # --wait ile tek seferde en fazla 3 saat beklenir
SCENARIOS = EVAL_DIR / "agent_scenarios.json"


def line(r: dict) -> str:
    if r["tur"] == "ariza":
        verdict = "bileşen doğru" if r["bilesen_dogru"] else f"bileşen YANLIŞ ({r['ajan_bilesen']})"
        verdict += ", taslak açıldı" if r["taslak"] else ", taslak YOK"
    else:
        verdict = "YANLIŞ ALARM" if r["yanlis_alarm"] else "alarm yok"
    if r.get("dogrulama"):
        verdict += ", doğrulama düzeltti"
    if r["dayanaksiz_sayilar"]:
        verdict += f", dayanaksız sayı kaldı: {r['dayanaksiz_sayilar']}"
    return f"{verdict} | {r['arac_sayisi']} araç, {r['token']:,} token, {r['sure_sn']} sn"


def write_summary(records: list[dict], path: Path, run: str, search: str) -> str:
    table = summarize(records, component_specs(load_chunks(config.MANUAL_PATH)))
    path.write_text(f"# Ajan değerlendirmesi ({run})\n\nLLM: `{config.GROQ_MODEL}` (akıl yürütme: "
                    f"`{config.GROQ_REASONING_EFFORT}`), kılavuz araması: `{search}`\n\n{table}\n",
                    encoding="utf-8")
    return table


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="Bu çalıştırmada en fazla kaç senaryo")
    ap.add_argument("--summary", action="store_true", help="Sadece kayıtlı sonuçların özetini yaz")
    ap.add_argument("--run", default="v2", help="Sonuç dosyalarının sürüm adı (varsayılan v2)")
    ap.add_argument("--types", default="", help="Sadece bu senaryo türleri, virgülle: ariza,hatali_arizasiz,sakin")
    ap.add_argument("--wait", action="store_true",
                    help="Groq sınırına takılınca durma; söylenen süre kadar bekleyip devam et (bilgisayar açık kalmalı)")
    ap.add_argument("--search", default=config.MANUAL_SEARCH,
                    help="Kılavuz arama yöntemi. v1 ile karşılaştırırken tek değişken kalsın diye: --search bm25")
    args = ap.parse_args()
    results_path = EVAL_DIR / f"agent_runs_{args.run}.jsonl"
    summary_path = EVAL_DIR / f"agent_summary_{args.run}.md"

    con = duckdb.connect(str(config.DB_PATH), read_only=True)
    if not SCENARIOS.exists():
        EVAL_DIR.mkdir(parents=True, exist_ok=True)
        scenarios = make_scenarios(con)
        SCENARIOS.write_text(json.dumps(scenarios, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{len(scenarios)} senaryo oluşturuldu: {SCENARIOS}")
    scenarios = json.loads(SCENARIOS.read_text(encoding="utf-8"))

    records = load_records(results_path)
    done = {r["id"] for r in records}
    if args.types:
        scenarios = [s for s in scenarios if s["tur"] in args.types.split(",")]
    pending = [s for s in scenarios if s["id"] not in done]

    if not args.summary and pending:
        todo = pending[: args.limit] if args.limit else pending
        print(f"{len(done)} senaryo daha önce bitmiş; şimdi {len(todo)} senaryo çalışacak.\n")
        model = load(config.ROOT_DIR / "models")
        manual, method = build_search(load_chunks(config.MANUAL_PATH), args.search)
        llm = GroqLLM(config.GROQ_API_KEY, config.GROQ_MODEL, config.GROQ_BASE_URL, config.GROQ_REASONING_EFFORT)
        n = 0
        while n < len(todo):
            sc = todo[n]
            print(f"[{n + 1}/{len(todo)}] {sc['id']} makine {sc['machine_id']}, {sc['as_of']} ({sc['tur']}) ... ",
                  end="", flush=True)
            try:
                r = run_scenario(sc, con, config.ROOT_DIR / "models", manual, llm, model=model)
            except RateLimited as e:
                left = len(todo) - n
                if args.wait and e.wait_seconds <= MAX_SLEEP:
                    until = (datetime.now() + timedelta(seconds=e.wait_seconds + 10)).strftime("%H:%M")
                    print(f"\nGroq sınırı: {e.wait_seconds / 60:.0f} dk bekleniyor, {until} civarı devam edecek "
                          f"({left} senaryo kaldı). Durdurmak için Ctrl+C; sonra kaldığı yerden devam eder.")
                    time.sleep(e.wait_seconds + 10)
                    continue  # aynı senaryoyu baştan dener
                print(f"\n\nGroq sınırı doldu ({e.wait_seconds:.0f} sn beklemek gerekiyor). "
                      f"Kalan {left} senaryo için scripti daha sonra tekrar çalıştır (ya da --wait ekle); "
                      "kaldığı yerden devam eder.")
                break
            except LLMError as e:
                print(f"\n\nHata: {e}")
                break
            append_record(results_path, r)
            records.append(r)
            print(line(r))
            n += 1

    if not records:
        print("Henüz sonuç yok.")
        return 0
    remaining = len(scenarios) - len(records)
    print(f"\n{len(records)}/{len(scenarios)} senaryonun özeti" + (f" ({remaining} senaryo kaldı)" if remaining else ""))
    print(write_summary(records, summary_path, args.run, args.search))

    misses = to_frame(records)
    wrong = misses[(misses.tur == "ariza") & (misses.ajan_bilesen.isna() | ~misses.taslak)]
    if len(wrong):
        print("\nArıza senaryolarında eksik kalanlar:")
        print(wrong.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
