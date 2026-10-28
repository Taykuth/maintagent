"""API uç noktaları. Gerçek LLM yerine senaryolu sahte LLM kullanılır."""

import json

import pytest
from conftest import AS_OF, ScriptedLLM, answer, call
from fastapi.testclient import TestClient

from maintagent import config
from maintagent.agent import LLMError, RateLimited
from maintagent.api import AppState, create_app
from maintagent.manual import ManualSearch, load_chunks
from maintagent.work_orders import WorkOrderStore


OK = "**Durum:** riskli.\n**Kanıt:** rapor\n**Öneri:** taslak hazırlandı, onay bekliyor"


@pytest.fixture
def state(synthetic_env, tmp_path):
    con, model_dir = synthetic_env
    return AppState(con=con, model_dir=model_dir, as_of=AS_OF,
                    manual=ManualSearch(load_chunks(config.MANUAL_PATH), "bm25"),
                    orders=WorkOrderStore(tmp_path / "orders.sqlite"),
                    make_llm=lambda: ScriptedLLM([answer(OK)]), llm_name="sahte", manual_method="bm25")


@pytest.fixture
def client(state):
    return TestClient(create_app(state))


def sse_events(text: str) -> list[dict]:
    return [json.loads(line[len("data: "):]) for line in text.splitlines() if line.startswith("data: ")]


def test_health(client):
    r = client.get("/api/health").json()
    assert r["ok"] and r["as_of"] == str(AS_OF) and r["manual_search"] == "bm25"


def test_machines_sorted_by_risk(client):
    machines = client.get("/api/machines").json()
    assert len(machines) == 6
    risks = [m["risk_pct"] for m in machines]
    assert risks == sorted(risks, reverse=True)
    assert {"machine_id", "model", "age", "risk_pct", "likely_comp", "comp_name"} <= set(machines[0])


def test_machine_report_and_404(client):
    assert client.get("/api/machines/1").json()["makine"]["id"] == 1
    assert client.get("/api/machines/999").status_code == 404


def test_telemetry_series_stops_at_as_of(client):
    r = client.get("/api/machines/1/telemetry", params={"hours": 48}).json()
    assert len(r["points"]) == 48
    assert r["points"][-1]["ts"] == "2015-06-15 12:00:00"


def test_ask_streams_steps_and_creates_draft(client, state):
    state.make_llm = lambda: ScriptedLLM([
        call("get_machine_report", machine_id=1),
        call("search_manual", query="ana mil rulmanı kontrol adımları"),
        call("draft_work_order", machine_id=1, component="comp2", reason="Risk yüksek", steps=["Kilitle"]),
        answer(OK),
    ])
    r = client.post("/api/ask", json={"question": "Makine 1 neden riskli?"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = sse_events(r.text)
    assert [e["type"] for e in events] == ["tool_call", "tool_result"] * 3 + ["answer"]
    assert events[-1]["content"] == OK

    drafts = client.get("/api/work-orders", params={"status": "taslak"}).json()
    assert len(drafts) == 1 and drafts[0]["machine_id"] == 1


def test_human_approves_draft_once(client, state):
    order = state.orders.create(machine_id=1, component="comp2", risk_pct=90, reason="r", steps=["s"],
                                parts=[], estimated_hours=None, manual_section=None)
    ok = client.post(f"/api/work-orders/{order['id']}/approve", json={"note": "Yarın sabah"})
    assert ok.status_code == 200 and ok.json()["status"] == "onaylandi" and ok.json()["note"] == "Yarın sabah"
    assert client.post(f"/api/work-orders/{order['id']}/reject").status_code == 409  # karar bir kez verilir
    assert client.post("/api/work-orders/9999/approve").status_code == 404


def test_ask_reports_llm_errors_as_events(client, state):
    state.make_llm = lambda: ScriptedLLM([RateLimited(3600)])
    events = sse_events(client.post("/api/ask", json={"question": "?"}).text)
    assert events[-1]["type"] == "error" and "sınır" in events[-1]["message"]

    def no_key():
        raise LLMError("GROQ_API_KEY tanımlı değil")
    state.make_llm = no_key
    events = sse_events(client.post("/api/ask", json={"question": "?"}).text)
    assert events == [{"type": "error", "message": "GROQ_API_KEY tanımlı değil"}]


def test_only_one_agent_at_a_time(client, state):
    state.agent_lock.acquire()
    try:
        assert client.post("/api/ask", json={"question": "?"}).status_code == 429
    finally:
        state.agent_lock.release()
    assert client.post("/api/ask", json={"question": "?"}).status_code == 200  # kilit açılınca çalışır


def test_ask_validates_question(client):
    assert client.post("/api/ask", json={"question": ""}).status_code == 422
