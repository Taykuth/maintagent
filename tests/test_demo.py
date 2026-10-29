"""Herkese açık demo için: canlı soru sınırı ve kayıtlı çalıştırmaların oynatılması."""

import json

import pytest
from conftest import AS_OF, ScriptedLLM, answer
from fastapi.testclient import TestClient

from maintagent import config
from maintagent.api import AppState, create_app
from maintagent.examples import load_examples, replay_events
from maintagent.manual import ManualSearch, load_chunks
from maintagent.quota import LiveQuota
from maintagent.work_orders import WorkOrderStore

OK = "**Durum:** -\n**Kanıt:** -\n**Öneri:** -"

ORDER = {"id": 7, "machine_id": 1, "component": "comp2", "risk_pct": 99.0, "reason": "r", "steps": ["Kilitle"],
         "parts": [], "estimated_hours": 4.0, "manual_section": None, "priority": "acil", "status": "taslak"}
EXAMPLE = {
    "id": "makine-1", "question": "Makine 1 neden riskli?", "as_of": str(AS_OF), "recorded_at": "2026-10-29T10:00",
    "llm": "openai/gpt-oss-120b",
    "events": [
        {"type": "tool_call", "tool": "draft_work_order", "arguments": "{}", "t": 1.0},
        {"type": "waiting", "seconds": 40, "t": 1.5},
        {"type": "tool_result", "tool": "draft_work_order", "arguments": "{}", "ms": 3,
         "result": {"is_emri": ORDER}, "t": 45.0},
        {"type": "answer", "content": "Taslak #7 hazırlandı, onay bekliyor.", "tokens": 9000, "seconds": 46.0,
         "stopped_early": False, "t": 46.0},
    ],
}


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_quota_limits_per_ip_and_per_day():
    clock = Clock()
    q = LiveQuota(per_ip_per_hour=2, per_day=3, clock=clock)
    assert q.try_take("a") is None and q.try_take("a") is None
    assert "saat" in q.try_take("a")            # aynı IP saatte 2'den fazla soramaz
    assert q.try_take("b") is None              # başka IP sorabilir
    assert "Bugünkü" in q.try_take("c")         # günlük toplam 3 doldu
    assert q.remaining_today() == 0
    clock.now = 24 * 3600 + 1                   # bir gün sonra hak geri gelir
    assert q.try_take("a") is None and q.remaining_today() == 2


def test_quota_zero_means_unlimited():
    q = LiveQuota()
    assert all(q.try_take("a") is None for _ in range(100)) and q.remaining_today() is None


def test_replay_skips_waits_creates_the_draft_and_fixes_its_number(tmp_path):
    store = WorkOrderStore(tmp_path / "o.sqlite")
    store.create(machine_id=5, component="comp1", risk_pct=90, reason="başka", steps=["x"], parts=[],
                 estimated_hours=None, manual_section=None)  # canlı kayıtta zaten 1 numara var
    slept = []
    events = list(replay_events(EXAMPLE, store, max_gap=1.2, sleep=slept.append))
    assert [e["type"] for e in events] == ["replay", "tool_call", "tool_result", "answer"]
    assert all(s <= 1.2 for s in slept)        # 43 saniyelik Groq beklemesi oynatılmaz
    new_id = events[2]["result"]["is_emri"]["id"]
    assert new_id != 7 and store.get(new_id)["status"] == "taslak"
    assert events[3]["content"] == f"Taslak #{new_id} hazırlandı, onay bekliyor."
    assert all("t" not in e for e in events)


def test_examples_from_another_date_are_not_offered(tmp_path):
    path = tmp_path / "examples.json"
    path.write_text(json.dumps([EXAMPLE, {**EXAMPLE, "id": "eski", "as_of": "2015-01-01 00:00:00"}]), encoding="utf-8")
    assert [e["id"] for e in load_examples(path, AS_OF)] == ["makine-1"]
    assert load_examples(tmp_path / "yok.json", AS_OF) == []


@pytest.fixture
def client(synthetic_env, tmp_path):
    con, model_dir = synthetic_env
    state = AppState(con=con, model_dir=model_dir, as_of=AS_OF,
                     manual=ManualSearch(load_chunks(config.MANUAL_PATH), "bm25"),
                     orders=WorkOrderStore(tmp_path / "orders.sqlite"),
                     make_llm=lambda: ScriptedLLM([answer(OK)]), llm_name="sahte", manual_method="bm25",
                     quota=LiveQuota(per_ip_per_hour=1, per_day=10), examples=[EXAMPLE])
    return TestClient(create_app(state))


def test_api_lists_and_replays_examples(client):
    assert client.get("/api/examples").json() == [{"id": "makine-1", "question": "Makine 1 neden riskli?"}]
    r = client.post("/api/examples/makine-1/replay")
    events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
    assert events[0]["type"] == "replay" and events[-1]["type"] == "answer"
    assert len(client.get("/api/work-orders", params={"status": "taslak"}).json()) == 1
    assert client.post("/api/examples/yok/replay").status_code == 404


def test_api_enforces_live_quota(client):
    assert client.get("/api/health").json()["live_left_today"] == 10
    assert client.post("/api/ask", json={"question": "?"}).status_code == 200
    second = client.post("/api/ask", json={"question": "?"}, headers={"x-forwarded-for": "testclient"})
    assert second.status_code == 429 and "Kayıtlı" in second.json()["detail"]
    other_ip = client.post("/api/ask", json={"question": "?"}, headers={"x-forwarded-for": "10.0.0.9, 1.2.3.4"})
    assert other_ip.status_code == 200
    assert client.get("/api/health").json()["live_left_today"] == 8


def test_static_export_writes_what_the_api_serves(synthetic_env, tmp_path):
    from maintagent.static_export import export_static

    con, model_dir = synthetic_env
    state = AppState(con=con, model_dir=model_dir, as_of=AS_OF,
                     manual=ManualSearch(load_chunks(config.MANUAL_PATH), "bm25"),
                     orders=WorkOrderStore(tmp_path / "orders.sqlite"), make_llm=lambda: ScriptedLLM([]),
                     llm_name="sahte", manual_method="bm25", quota=LiveQuota(per_day=10), examples=[EXAMPLE])
    out = tmp_path / "demo"
    (out / "eski.json").parent.mkdir(parents=True)
    (out / "eski.json").write_text("{}")
    summary = export_static(state, out)

    read = lambda p: json.loads((out / p).read_text(encoding="utf-8"))  # noqa: E731
    machines = read("machines.json")
    assert summary["machines"] == len(machines) > 0 and summary["examples"] == 1
    assert read("health.json")["live_left_today"] is None   # statik demoda canlı soru yok
    first = machines[0]["machine_id"]
    assert read(f"machines/{first}.json")["makine"]["id"] == first
    assert read(f"telemetry/{first}.json")["points"]
    assert read("examples.json")[0]["events"][-1]["type"] == "answer"
    assert not (out / "eski.json").exists()                  # önceki dışa aktarımdan kalan dosya silinir
