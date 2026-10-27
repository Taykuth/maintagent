"""Testlerin paylaştığı hazırlık: sentetik veri, veritabanı, eğitilmiş model ve sahte LLM.

Sentetik veri ve model bir kez hazırlanır (scope="session"); her test dosyası
yeniden eğitmek zorunda kalmaz.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from maintagent.db import load_all  # noqa: E402
from maintagent.features import build_features  # noqa: E402
from maintagent.model import save, train  # noqa: E402
from maintagent.synthetic import write_synthetic_csvs  # noqa: E402

AS_OF = datetime(2015, 6, 15, 12)


@pytest.fixture(scope="session")
def synthetic_env(tmp_path_factory):
    d = tmp_path_factory.mktemp("env")
    write_synthetic_csvs(d / "raw", n_machines=6, seed=3)
    con = load_all(d / "raw", d / "t.duckdb")
    model = train(build_features(con, datetime(2015, 1, 2), datetime(2015, 5, 1)))
    save(model, {}, d / "models")
    return con, d / "models"


class ScriptedLLM:
    """Önceden yazılmış cevapları sırayla döndürür ve gelen mesajları kaydeder.

    Listede bir istisna (Exception) varsa döndürmek yerine onu fırlatır; böylece
    Groq'un 429 gibi hataları internetsiz test edilebilir.
    """

    def __init__(self, replies):
        self.replies, self.seen = list(replies), []

    def chat(self, messages, tools):
        self.seen.append(list(messages))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def call(name, **args):
    """Tek araç çağrısı yapan LLM cevabı."""
    return {"content": "", "tool_calls": [{"id": f"c_{name}", "name": name, "arguments": json.dumps(args)}]}


def answer(text):
    return {"content": text, "tool_calls": []}
