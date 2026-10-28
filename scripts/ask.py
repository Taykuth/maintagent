"""Ajana terminalden soru sor; adımları canlı izle.

Kullanım:
    python scripts/ask.py "Makine 20 neden riskli, ne yapmalıyım?"
    python scripts/ask.py "Şu an en riskli 3 makine hangileri?"
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb  # noqa: E402

from maintagent import config  # noqa: E402
from maintagent.agent import GroqLLM, LLMError, run_agent  # noqa: E402
from maintagent.manual import ManualSearch, load_chunks  # noqa: E402
from maintagent.tools import Toolbox  # noqa: E402
from maintagent.work_orders import WorkOrderStore  # noqa: E402


def show(event: dict) -> None:
    t = event["type"]
    if t == "tool_call":
        print(f"\n→ {event['tool']}({event['arguments']})", flush=True)
    elif t == "tool_result":
        text = json.dumps(event["result"], ensure_ascii=False, default=str)
        print(f"  ← {text[:300]}{'...' if len(text) > 300 else ''}  ({event['ms']} ms)", flush=True)
    elif t == "nudge":
        print(f"\n! Adım kontrolü: cevap geri çevrildi, eksik: {event['missing']}", flush=True)
    elif t == "revise":
        found = {k: v for k, v in event.items() if k != "type"}
        print(f"\n! Cevap doğrulaması: ilk cevap düzelttirildi {found}", flush=True)
    elif t == "waiting":
        print(f"\n… Groq dakikalık sınırı: {event['seconds']} sn bekleniyor", flush=True)


def main() -> int:
    if len(sys.argv) < 2:
        print('Kullanım: python scripts/ask.py "Makine 20 neden riskli?"')
        return 1
    question = " ".join(sys.argv[1:])
    con = duckdb.connect(str(config.DB_PATH), read_only=True)
    manual = ManualSearch(load_chunks(config.MANUAL_PATH), config.MANUAL_SEARCH)
    toolbox = Toolbox(con, config.ROOT_DIR / "models", config.AS_OF, manual=manual,
                      orders=WorkOrderStore(config.WORK_ORDERS_DB))

    print(f"Şu an: {config.AS_OF}  |  Model: {config.GROQ_MODEL}  |  Kılavuz araması: {config.MANUAL_SEARCH}")
    print(f"Soru: {question}")
    try:
        result = run_agent(question, toolbox, GroqLLM(config.GROQ_API_KEY, config.GROQ_MODEL, config.GROQ_BASE_URL,
                                                   config.GROQ_REASONING_EFFORT),
                           on_event=show)
    except LLMError as e:
        print(f"\nHata: {e}")
        return 2
    print(f"\n{'=' * 60}\n{result.answer}\n{'=' * 60}")
    print(f"{len(result.steps)} araç çağrısı, {result.tokens} token, {result.seconds:.1f} sn")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
