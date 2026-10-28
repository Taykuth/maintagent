"""Bakım kılavuzunda arama.

Üç yöntem var. Hangisinin kullanılacağına ölçüm karar verdi (scripts/eval_retrieval.py):
  - bm25: kelime eşleşmesi. Hızlı, model gerektirmez; eş anlamlıları kaçırır.
  - embedding: anlam benzerliği (multilingual-e5-small). Eş anlamlıları yakalar; model indirmek gerekir.
  - hybrid: iki sıralamayı Reciprocal Rank Fusion (RRF) ile birleştirir.

Karar kuralı sonuçlar görülmeden konuldu: embedding ya da hibrit, doğru bölümü ilk 3'te bulmada
BM25'i en az 0,10 geçerse hibrit kullanılacak. 20 soruda BM25 0,85, embedding 0,90, hibrit 1,00
buldu; varsayılan bu yüzden hibrit.

Kılavuz küçük (~35 parça). Bu yüzden vektör veritabanı ya da FAISS yok: sorguyu
bütün parçalarla karşılaştırmak numpy ile milisaniyeler sürer.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

EMBED_MODEL = "intfloat/multilingual-e5-small"
METHODS = ("bm25", "embedding", "hybrid")

# Sorgularda sık geçen ama anlam taşımayan kelimeler
STOPWORDS = {"ve", "ile", "bir", "bu", "şu", "da", "de", "mi", "mı", "mu", "mü", "ne", "için", "ya",
             "ama", "veya", "gibi", "daha", "çok", "en", "her", "o", "ise", "hangi", "nasıl", "neden"}

Embedder = Callable[[list[str]], np.ndarray]


@dataclass
class Chunk:
    id: int
    title: str
    text: str


def load_chunks(path: Path) -> list[Chunk]:
    """Markdown'ı ### başlıklarına göre parçalara böler.

    Parça başlığı üstteki ## başlığını da içerir ("comp2 — Ana mil rulmanı › Kontrol adımları").
    Böylece "Kontrol adımları" gibi her bileşende tekrar eden bölümler birbirinden ayrılır.
    """
    chunks: list[Chunk] = []
    section, title, lines = "", None, []

    def flush():
        body = "\n".join(lines).strip()
        if title and body:
            chunks.append(Chunk(len(chunks), title, body))

    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            flush()
            section = title = line[3:].strip()
            lines = []
        elif line.startswith("### "):
            flush()
            title, lines = f"{section} › {line[4:].strip()}", []
        elif not line.startswith("# "):
            lines.append(line)
    flush()
    return chunks


def _lower_tr(text: str) -> str:
    # Python'un lower() fonksiyonu "I" harfini "i" yapar; Türkçede "ı" olmalı.
    return text.replace("I", "ı").replace("İ", "i").lower()


def tokenize(text: str, stem: bool = True) -> list[str]:
    """Küçük harfe çevirir, kelimelere böler ve her kelimenin ilk 5 harfini alır.

    Türkçe sondan eklemeli bir dil: "rulmanı", "rulmanda", "rulmanlar" ayrı kelimeler
    ama ilk 5 harfleri ("rulma") aynı. Bu basit kesmenin etkisi ölçüm scriptinde
    "kök kesme yok" satırıyla karşılaştırılır.
    """
    words = [w for w in re.findall(r"\w+", _lower_tr(text)) if w not in STOPWORDS]
    return [w[:5] for w in words] if stem else words


class BM25:
    """Okapi BM25. Bir kelime ne kadar nadirse (idf) ve parçada ne kadar sık geçiyorsa
    (tf) skor o kadar artar. b, uzun parçaların sırf uzun oldukları için öne
    geçmesini engeller; k1, aynı kelimenin tekrarının skoru sınırsız artırmasını önler."""

    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.tfs = [Counter(d) for d in docs]
        self.lens = np.array([len(d) for d in docs], dtype=float)
        self.avg_len = self.lens.mean()
        self.k1, self.b = k1, b
        n = len(docs)
        df = Counter(t for tf in self.tfs for t in tf)
        self.idf = {t: math.log((n - f + 0.5) / (f + 0.5) + 1) for t, f in df.items()}

    def scores(self, query: list[str]) -> np.ndarray:
        out = np.zeros(len(self.tfs))
        for i, tf in enumerate(self.tfs):
            norm = self.k1 * (1 - self.b + self.b * self.lens[i] / self.avg_len)
            out[i] = sum(self.idf[t] * tf[t] * (self.k1 + 1) / (tf[t] + norm) for t in query if t in tf)
        return out


def e5_embedder(model_name: str = EMBED_MODEL) -> Embedder:
    """Gerçek embedding modeli. İlk çalıştırmada modeli indirir (birkaç yüz MB)."""
    from sentence_transformers import SentenceTransformer  # ağır bağımlılık; sadece gerekince yükle

    model = SentenceTransformer(model_name)
    return lambda texts: model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)


def _order(scores: np.ndarray, positive_only: bool = False) -> list[int]:
    idx = np.argsort(-scores, kind="stable")
    return [int(i) for i in idx if not positive_only or scores[i] > 0]


def rrf(rankings: list[list[int]], k: int = 60) -> list[int]:
    """Reciprocal Rank Fusion: her listede r. sırada olan parçaya 1 / (k + r) puan ver, topla.

    Skorları değil sıraları birleştirir; BM25 skoru ile kosinüs benzerliği farklı
    ölçeklerde olduğu için doğrudan toplanamaz. k=60 literatürdeki standart değer.
    """
    score: Counter = Counter()
    for ranking in rankings:
        for r, i in enumerate(ranking, start=1):
            score[i] += 1 / (k + r)
    return [i for i, _ in score.most_common()]


class ManualSearch:
    def __init__(self, chunks: list[Chunk], method: str = "bm25", embed: Embedder | None = None,
                 stem: bool = True):
        if method not in METHODS:
            raise ValueError(f"Bilinmeyen arama yöntemi: {method}. Seçenekler: {METHODS}")
        self.chunks, self.method, self.stem = chunks, method, stem
        self._bm25 = BM25([tokenize(f"{c.title}\n{c.text}", stem) for c in chunks])
        self._embed, self._vectors = None, None
        if method != "bm25":
            self._embed = embed or e5_embedder()
            # e5 modelleri bu öneklerle eğitildi; önek olmadan sonuçlar kötüleşir.
            self._vectors = self._embed([f"passage: {c.title}\n{c.text}" for c in chunks])

    def ranking(self, query: str) -> list[int]:
        """Parça numaralarını en alakalıdan en alakasıza sıralar."""
        bm25 = _order(self._bm25.scores(tokenize(query, self.stem)), positive_only=True)
        if self.method == "bm25":
            return bm25
        emb = _order(self._vectors @ self._embed([f"query: {query}"])[0])
        return emb if self.method == "embedding" else rrf([bm25, emb])

    def search(self, query: str, k: int = 3) -> list[Chunk]:
        return [self.chunks[i] for i in self.ranking(query)[:k]]


def build_search(chunks: list[Chunk], method: str) -> tuple[ManualSearch, str]:
    """İstenen yöntemle arama kurar. sentence-transformers kurulu değilse BM25'e düşer ve bunu söyler.

    Gerçekte kullanılan yöntemi de döndürür; API bunu /api/health'te gösterir.
    """
    try:
        return ManualSearch(chunks, method), method
    except ImportError:
        print(f"Uyarı: '{method}' araması için sentence-transformers kurulu değil; BM25 kullanılıyor. "
              "Kurmak için: pip install -r requirements-embed.txt")
        return ManualSearch(chunks, "bm25"), "bm25"
