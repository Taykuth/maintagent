"""Kılavuz bölme, Türkçe kelime işleme ve arama yöntemleri.

Embedding testleri gerçek model yerine sahte bir embedder kullanır; böylece testler
internetsiz ve hızlı çalışır. Gerçek modelin kalitesini scripts/eval_retrieval.py ölçer.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from maintagent import config  # noqa: E402
from maintagent.manual import ManualSearch, load_chunks, rrf, tokenize  # noqa: E402
from maintagent.tools import COMP_TR  # noqa: E402

SECTIONS = ["Görevi", "Arıza belirtileri", "Olası nedenler", "Kontrol adımları",
            "Değişim prosedürü", "Süre, parça ve öncelik"]


@pytest.fixture(scope="module")
def chunks():
    return load_chunks(config.MANUAL_PATH)


def test_every_component_has_all_sections(chunks):
    titles = {c.title for c in chunks}
    assert len(titles) == len(chunks)  # başlıklar tekrar etmiyor
    for comp, name in COMP_TR.items():
        section = f"{comp} — {name[0].upper()}{name[1:]}"
        for s in SECTIONS:
            assert f"{section} › {s}" in titles, f"Eksik bölüm: {section} › {s}"


def test_eval_questions_point_to_existing_sections(chunks):
    titles = {c.title for c in chunks}
    questions = json.loads((config.MANUAL_PATH.parent / "eval_questions.json").read_text(encoding="utf-8"))
    for q in questions:
        for t in q["beklenen"]:
            assert t in titles, f"Test setinde olmayan bölüm: {t}"


def test_tokenize_handles_turkish():
    assert tokenize("Rulmanı RULMANDA İzle Işık") == ["rulma", "rulma", "izle", "ışık"]
    assert tokenize("hangi rulman ve kaplin") == ["rulma", "kapli"]  # bağlaçlar atılır
    assert tokenize("Rulmanları", stem=False) == ["rulmanları"]


def test_bm25_finds_the_right_component(chunks):
    s = ManualSearch(chunks, "bm25")
    assert s.search("hidrolik valf değişim süresi ve parçalar", k=1)[0].title.startswith("comp3")
    assert s.search("titreşim arttı kaplin", k=1)[0].title.startswith("comp4")


def test_bm25_returns_nothing_without_matching_words(chunks):
    assert ManualSearch(chunks, "bm25").search("xyzzy qwerty") == []


def test_rrf_rewards_documents_ranked_high_in_both_lists():
    # 0 iki listede de üst sıralarda, 1 ikisinde de alt sıralarda
    assert rrf([[0, 1, 2], [2, 0, 1]]) == [0, 2, 1]


class FakeEmbedder:
    """Gelen metinleri kaydeder; her metni sabit bir vektöre çevirir."""

    def __init__(self):
        self.seen = []

    def __call__(self, texts):
        self.seen.extend(texts)
        rng = np.random.default_rng(len(self.seen))
        v = rng.normal(size=(len(texts), 8))
        return v / np.linalg.norm(v, axis=1, keepdims=True)


def test_embedding_uses_e5_prefixes(chunks):
    fake = FakeEmbedder()
    s = ManualSearch(chunks, "hybrid", embed=fake)
    s.search("rulman")
    assert all(t.startswith("passage: ") for t in fake.seen[:len(chunks)])
    assert fake.seen[-1] == "query: rulman"


def test_hybrid_returns_every_chunk_once(chunks):
    s = ManualSearch(chunks, "hybrid", embed=FakeEmbedder())
    r = s.ranking("rulman değişimi")
    assert sorted(r) == list(range(len(chunks)))


def test_unknown_method_is_rejected(chunks):
    with pytest.raises(ValueError):
        ManualSearch(chunks, "faiss")


def test_build_search_falls_back_to_bm25_without_embeddings(chunks, monkeypatch):
    import maintagent.manual as manual_mod

    def missing():
        raise ImportError("sentence_transformers")

    monkeypatch.setattr(manual_mod, "e5_embedder", missing)
    search, method = manual_mod.build_search(chunks, "hybrid")
    assert method == "bm25" and search.method == "bm25"
