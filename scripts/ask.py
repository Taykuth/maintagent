"""Ajana terminalden soru sor; adımları canlı izle.

Kullanım:
    python scripts/ask.py "Makine 42 neden riskli?"
    python scripts/ask.py "En riskli 3 makine hangileri?"
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb  # noqa: E402

from maintagent import config  # noqa: E402
from maintagent.agent import GroqLLM, run_agent  # noqa: E402
from maintagent.manual import ManualSearch, load_chunks  # noqa: E402
from maintagent.tools import Toolbox  # noqa: E402


def show(event: dict) -> None:
    if event["type"] == "tool_call":
        print(f"\n→ {event['tool']}({event['arguments']})", flush=True)
    elif event["type"] == "tool_result":
        text = json.dumps(event["result"], ensure_ascii=False, default=str)
        print(f"  ← {text[:300]}{'...' if len(text) > 300 else ''}  ({event['ms']} ms)", flush=True)
    elif event["type"] == "nudge":
        print(f"\n! Kanıt kontrolü: cevap geri çevrildi, eksik araçlar: {event['missing']}", flush=True)


def main() -> int:
    if len(sys.argv) < 2:
        print('Kullanım: python scripts/ask.py "Makine 42 neden riskli?"')
        return 1
    question = " ".join(sys.argv[1:])
    con = duckdb.connect(str(config.DB_PATH), read_only=True)
    manual = ManualSearch(load_chunks(config.MANUAL_PATH), config.MANUAL_SEARCH)
    toolbox = Toolbox(con, config.ROOT_DIR / "models", config.AS_OF, manual=manual)
    llm = GroqLLM(config.GROQ_API_KEY, config.GROQ_MODEL, config.GROQ_BASE_URL)

    print(f"Şu an: {config.AS_OF}  |  Model: {config.GROQ_MODEL}  |  Kılavuz araması: {config.MANUAL_SEARCH}")
    print(f"Soru: {question}")
    result = run_agent(question, toolbox, llm, on_event=show)
    print(f"\n{'=' * 60}\n{result.answer}\n{'=' * 60}")
    print(f"{len(result.steps)} araç çağrısı, {result.seconds:.1f} sn")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
