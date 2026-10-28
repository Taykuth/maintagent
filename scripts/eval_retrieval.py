"""Kılavuz aramasında yöntemleri karşılaştırır: BM25, embedding, hibrit.

Ölçütler (20 soru, data/manual/eval_questions.json):
  - isabet@1: doğru bölüm ilk sırada mı?
  - isabet@3: doğru bölüm ilk 3'te mü? (ajan 3 sonuç görür, asıl ölçüt bu)
  - MRR: doğru bölümün sırasının tersinin ortalaması (1. sıra = 1, 2. sıra = 0.5 ...)

Not: Soruları ve kılavuzu aynı kişi yazdı; bu, kelime eşleşmesine (BM25) avantaj
sağlayabilir. Bazı sorular bilerek eş anlamlı kelimelerle yazıldı ("sarsıntı",
"hizasızlık"). Küçük bir set; sonuçlar yön gösterir, kesin değildir.

Kullanım:
    pip install -r requirements-embed.txt   # embedding için, bir kere
    python scripts/eval_retrieval.py
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from maintagent import config  # noqa: E402
from maintagent.manual import ManualSearch, e5_embedder, load_chunks  # noqa: E402


def evaluate(search: ManualSearch, questions: list[dict]) -> dict:
    hit1 = hit3 = rr = 0.0
    misses = []
    t0 = time.perf_counter()
    for q in questions:
        titles = [search.chunks[i].title for i in search.ranking(q["soru"])]
        ranks = [r for r, t in enumerate(titles) if t in q["beklenen"]]
        first = ranks[0] if ranks else None
        hit1 += first == 0
        hit3 += first is not None and first < 3
        rr += 1 / (first + 1) if first is not None else 0
        if first is None or first >= 3:
            misses.append(q["soru"])
    n = len(questions)
    return {"isabet@1": hit1 / n, "isabet@3": hit3 / n, "MRR": rr / n,
            "ms_soru": (time.perf_counter() - t0) * 1000 / n, "kaçan": misses}


def main() -> int:
    chunks = load_chunks(config.MANUAL_PATH)
    questions = json.loads((config.MANUAL_PATH.parent / "eval_questions.json").read_text(encoding="utf-8"))
    print(f"{len(chunks)} kılavuz parçası, {len(questions)} soru\n")

    searches = {
        "BM25 (kök kesme yok)": ManualSearch(chunks, "bm25", stem=False),
        "BM25": ManualSearch(chunks, "bm25"),
    }
    try:
        print("Embedding modeli yükleniyor (ilk seferde indirilir)...")
        embed = e5_embedder()
        searches["Embedding (e5-small)"] = ManualSearch(chunks, "embedding", embed=embed)
        searches["Hibrit (BM25 + embedding)"] = ManualSearch(chunks, "hybrid", embed=embed)
    except ImportError:
        print("sentence-transformers kurulu değil; sadece BM25 ölçülüyor.")
        print("Kurmak için: pip install -r requirements-embed.txt\n")

    results = {name: evaluate(s, questions) for name, s in searches.items()}

    print("\n| Yöntem | isabet@1 | isabet@3 | MRR | ms/soru |")
    print("|---|---|---|---|---|")
    for name, r in results.items():
        print(f"| {name} | {r['isabet@1']:.2f} | {r['isabet@3']:.2f} | {r['MRR']:.2f} | {r['ms_soru']:.1f} |")

    for name, r in results.items():
        if r["kaçan"]:
            print(f"\n{name} ilk 3'te bulamadı:")
            for q in r["kaçan"]:
                print(f"  - {q}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
