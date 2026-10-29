"""Demo için kayıtlı örnek çalıştırmalar üretir (gerçek LLM ile).

Arayüzdeki öneri düğmeleri bu kayıtları oynatır: ziyaretçi beklemez, Groq hakkı harcanmaz.
Her kayıt gerçek bir çalıştırmadır; elle düzenlenmez. Yaklaşık 5 soru x 9.000 token harcar.

Kullanım:
    python scripts/record_examples.py            # eksik örnekleri kaydeder
    python scripts/record_examples.py --again    # hepsini yeniden kaydeder
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb  # noqa: E402

from maintagent import config  # noqa: E402
from maintagent.agent import GroqLLM, LLMError, run_agent  # noqa: E402
from maintagent.manual import build_search, load_chunks  # noqa: E402
from maintagent.model import load  # noqa: E402
from maintagent.tools import Toolbox  # noqa: E402
from maintagent.work_orders import WorkOrderStore  # noqa: E402

# Varsayılan "şu an" (2015-10-01) için: üç acil makine, bir sağlam makine ve bir filo sorusu.
QUESTIONS = {
    "makine-20": "Makine 20 neden riskli, ne yapmalıyım?",
    "makine-37": "Makine 37 neden riskli, ne yapmalıyım?",
    "makine-66": "Makine 66 neden riskli, ne yapmalıyım?",
    "makine-63": "Makine 63 için durum nedir, ne yapmalıyım?",
    "en-riskli-3": "Şu an en riskli 3 makine hangileri?",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--again", action="store_true", help="Var olan kayıtları da yeniden al")
    args = ap.parse_args()

    path = config.EXAMPLES_PATH
    examples = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    have = {e["id"] for e in examples if e.get("as_of") == str(config.AS_OF)}
    todo = {k: q for k, q in QUESTIONS.items() if args.again or k not in have}
    if not todo:
        print("Bütün örnekler zaten kayıtlı. Yeniden almak için --again.")
        return 0

    con = duckdb.connect(str(config.DB_PATH), read_only=True)
    manual, method = build_search(load_chunks(config.MANUAL_PATH), config.MANUAL_SEARCH)
    model = load(config.ROOT_DIR / "models")
    llm = GroqLLM(config.GROQ_API_KEY, config.GROQ_MODEL, config.GROQ_BASE_URL, config.GROQ_REASONING_EFFORT)

    for key, question in todo.items():
        print(f"{key}: {question} ... ", end="", flush=True)
        events, t0 = [], time.perf_counter()
        # İş emirleri bellekte: kayıt alırken yerel iş emri listesi kirlenmesin.
        toolbox = Toolbox(con.cursor(), config.ROOT_DIR / "models", config.AS_OF, manual=manual,
                          orders=WorkOrderStore(":memory:"), model=model)
        try:
            result = run_agent(question, toolbox, llm,
                               on_event=lambda e: events.append({**e, "t": round(time.perf_counter() - t0, 2)}))
        except LLMError as e:
            print(f"\nHata: {e}\nKalan örnekler için scripti daha sonra tekrar çalıştır.")
            break
        if result.stopped_early:
            print("adım sınırında durdu, kaydedilmedi")
            continue
        examples = [e for e in examples if not (e["id"] == key and e.get("as_of") == str(config.AS_OF))]
        examples.append({"id": key, "question": question, "as_of": str(config.AS_OF),
                         "recorded_at": datetime.now().isoformat(timespec="minutes"),
                         "llm": config.GROQ_MODEL, "manual_search": method, "events": events})
        path.parent.mkdir(parents=True, exist_ok=True)
        examples.sort(key=lambda e: list(QUESTIONS).index(e["id"]) if e["id"] in QUESTIONS else 99)
        path.write_text(json.dumps(examples, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(f"kaydedildi ({len(result.steps)} araç, {result.tokens:,} token)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
