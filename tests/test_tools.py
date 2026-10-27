"""Araçların doğru veri döndürdüğünü, as_of sonrasını görmediğini ve ajan döngüsünü kontrol eder."""

import pytest
from conftest import AS_OF, ScriptedLLM, answer, call

from maintagent import config
from maintagent.agent import RateLimited, run_agent
from maintagent.manual import ManualSearch, load_chunks
from maintagent.tools import TOOL_SCHEMAS, Toolbox, describe_feature
from maintagent.work_orders import WorkOrderStore


@pytest.fixture
def toolbox(synthetic_env, tmp_path):
    con, model_dir = synthetic_env
    manual = ManualSearch(load_chunks(config.MANUAL_PATH), "bm25")
    return Toolbox(con, model_dir, AS_OF, manual=manual, orders=WorkOrderStore(tmp_path / "orders.sqlite"))


def test_every_schema_has_a_method(toolbox):
    for t in TOOL_SCHEMAS:
        assert callable(getattr(toolbox, t["function"]["name"]))


def test_machine_info(toolbox):
    info = toolbox.get_machine_info(1)
    assert info["machine_id"] == 1 and info["model"].startswith("model")


def test_unknown_machine_raises(toolbox):
    with pytest.raises(ValueError):
        toolbox.get_machine_info(999)


def test_telemetry_summary_has_all_sensors(toolbox):
    s = toolbox.get_telemetry_summary(1, hours=24)
    assert set(s["sensorler"]) == {"volt", "rotate", "pressure", "vibration"}
    assert all("sapma_z" in v for v in s["sensorler"].values())


def test_tools_do_not_see_the_future(toolbox):
    """as_of sonrasına bir hata ve bakım kaydı ekle; araçlar bunları görmemeli."""
    con = toolbox.con
    con.execute("INSERT INTO errors VALUES ('2015-06-15 13:00:00', 1, 'error9')")
    con.execute("INSERT INTO maint VALUES ('2015-06-15 13:00:00', 1, 'comp1')")
    try:
        errors = toolbox.get_recent_errors(1, days=30)
        assert all(e["hata"] != "error9" for e in errors["hatalar"])
        hist = toolbox.get_maintenance_history(1)
        comp1 = next(c for c in hist["bilesenler"] if c["bilesen"] == "comp1")
        assert comp1["son_degisim"] is None or comp1["son_degisim"] < "2015-06-15 13:00:00"
        series = toolbox.telemetry_series(1, hours=48)
        assert max(p["ts"] for p in series["points"]) <= "2015-06-15 12:00:00"
        assert all(e["kod"] != "error9" for e in series["events"])
    finally:
        con.execute("DELETE FROM errors WHERE error_id = 'error9'")
        con.execute("DELETE FROM maint WHERE ts = '2015-06-15 13:00:00' AND machine_id = 1")


def test_risk_prediction(toolbox):
    r = toolbox.predict_failure_risk(2)
    assert 0 <= r["ariza_riski_24_saat_yuzde"] <= 100
    assert r["en_olasi_bilesen"] in {"comp1", "comp2", "comp3", "comp4"}
    assert len(r["riski_en_cok_artiran_3_etken"]) == 3


def test_machine_report_combines_evidence(toolbox):
    r = toolbox.get_machine_report(2)
    assert set(r) == {"makine", "risk", "sensorler_son_24_saat", "normalden_belirgin_sapan",
                      "hatalar_son_7_gun", "bilesen_degisimleri"}
    assert set(r["sensorler_son_24_saat"]) == {"voltaj", "dönüş hızı", "basınç", "titreşim"}
    assert len(r["bilesen_degisimleri"]) == 4


def test_ranking_is_sorted(toolbox):
    ranks = [m["ariza_riski_yuzde"] for m in toolbox.rank_machines_by_risk(top_n=6)["makineler"]]
    assert ranks == sorted(ranks, reverse=True) and len(ranks) == 6


def test_describe_feature():
    assert describe_feature("vibration_mean_24h") == "titreşim 24 saatlik ortalaması"
    assert describe_feature("comp2_days") == "comp2 (ana mil rulmanı) kaç gündür değişmedi"
    assert describe_feature("error4_24h") == "son 24 saatteki E4 (error4) hata sayısı"


def test_search_manual(toolbox):
    r = toolbox.search_manual("ana mil rulmanı kontrol", k=3)
    assert len(r["sonuclar"]) == 3
    assert any("comp2" in s["bolum"] for s in r["sonuclar"])


def test_search_manual_rejects_empty_query(toolbox):
    with pytest.raises(ValueError):
        toolbox.search_manual("   ")


# --- İş emri taslağı ----------------------------------------------------------

def draft(toolbox, **overrides):
    args = {"machine_id": 1, "component": "comp2", "reason": "Risk %90, dönüş hızı %17 düşük",
            "steps": ["Kilitle", "Rulmanı değiştir"], "parts": ["RL-02"], "estimated_hours": 4}
    return toolbox.draft_work_order(**{**args, **overrides})


def test_draft_work_order_sets_priority_from_risk(toolbox):
    order = draft(toolbox)["is_emri"]
    risk = toolbox.predict_failure_risk(1)["ariza_riski_24_saat_yuzde"]
    expected = "acil" if risk >= 80 else "yuksek" if risk >= 50 else "normal"
    assert order["status"] == "taslak" and order["priority"] == expected
    assert order["steps"] == ["Kilitle", "Rulmanı değiştir"]


def test_second_draft_for_same_machine_returns_existing(toolbox):
    first = draft(toolbox)["is_emri"]
    second = draft(toolbox, reason="Başka gerekçe")
    assert second["is_emri"]["id"] == first["id"] and len(toolbox.orders.list()) == 1


@pytest.mark.parametrize("bad", [{"component": "comp9"}, {"steps": []}, {"reason": " "}, {"machine_id": 999}])
def test_draft_rejects_bad_input(toolbox, bad):
    with pytest.raises(ValueError):
        draft(toolbox, **bad)


# --- Ajan döngüsü: gerçek LLM yerine senaryolu sahte LLM ile --------------------

def test_agent_calls_tool_then_answers(toolbox):
    llm = ScriptedLLM([call("rank_machines_by_risk", top_n=3), answer("Bitti.")])
    events = []
    res = run_agent("En riskli 3?", toolbox, llm, on_event=events.append)
    assert res.answer == "Bitti." and len(res.steps) == 1
    assert [e["type"] for e in events] == ["tool_call", "tool_result", "answer"]
    tool_msg = llm.seen[1][-1]
    assert tool_msg["role"] == "tool" and '"makineler":' in tool_msg["content"]  # boşluksuz JSON


def test_agent_survives_bad_tool_and_bad_args(toolbox):
    bad_name = {"content": "", "tool_calls": [{"id": "x", "name": "delete_everything", "arguments": "{}"}]}
    bad_args = {"content": "", "tool_calls": [{"id": "y", "name": "get_machine_report", "arguments": "{bozuk"}]}
    private = {"content": "", "tool_calls": [{"id": "z", "name": "_q", "arguments": '{"sql": "DROP TABLE machines"}'}]}
    missing = call("get_machine_report", machine_id=999)
    llm = ScriptedLLM([bad_name, bad_args, private, missing, answer("Tamam.")])
    res = run_agent("?", toolbox, llm)
    assert res.answer == "Tamam."
    assert all("hata" in s["result"] for s in res.steps)


def test_agent_requires_manual_and_draft_for_risky_machine(toolbox):
    """Rapora bakıp hemen cevap verirse döngü geri çevirir ve eksik adımları söyler."""
    llm = ScriptedLLM([
        call("get_machine_report", machine_id=1),
        answer("Erken cevap."),
        call("search_manual", query="rulman kontrol adımları"),
        call("draft_work_order", machine_id=1, component="comp2", reason="r", steps=["Kilitle"]),
        answer("Tam cevap."),
    ])
    events = []
    res = run_agent("Makine 1 neden riskli?", toolbox, llm, on_event=events.append, draft_threshold=0)
    assert res.answer == "Tam cevap." and len(res.steps) == 3
    nudges = [e for e in events if e["type"] == "nudge"]
    assert len(nudges) == 1 and nudges[0]["missing"] == {1: ["search_manual", "draft_work_order"]}
    assert llm.seen[2][-1]["role"] == "user" and "draft_work_order" in llm.seen[2][-1]["content"]
    assert len(toolbox.orders.list("taslak")) == 1


def test_low_risk_machine_needs_no_draft(toolbox):
    llm = ScriptedLLM([call("get_machine_report", machine_id=1), call("search_manual", query="rulman"),
                       answer("Risk düşük.")])
    events = []
    run_agent("Makine 1?", toolbox, llm, on_event=events.append, draft_threshold=101)
    assert all(e["type"] != "nudge" for e in events)


def test_agent_nudges_only_once(toolbox):
    llm = ScriptedLLM([call("get_machine_report", machine_id=1), answer("a"), answer("b")])
    events = []
    res = run_agent("?", toolbox, llm, on_event=events.append)
    assert res.answer == "b" and [e["type"] for e in events].count("nudge") == 1


def test_agent_waits_when_rate_limited(toolbox):
    slept = []
    llm = ScriptedLLM([RateLimited(7), answer("Sonunda.")])
    events = []
    res = run_agent("?", toolbox, llm, on_event=events.append, sleep=slept.append)
    assert res.answer == "Sonunda." and slept == [7]
    assert events[0] == {"type": "waiting", "seconds": 7}


def test_agent_gives_up_on_long_rate_limit(toolbox):
    llm = ScriptedLLM([RateLimited(3600)])  # ör. günlük sınır doldu
    with pytest.raises(RateLimited):
        run_agent("?", toolbox, llm, sleep=lambda s: None)


def test_agent_stops_at_step_limit(toolbox):
    llm = ScriptedLLM([call("rank_machines_by_risk")] * 3)
    res = run_agent("?", toolbox, llm, max_steps=3)
    assert res.stopped_early and len(res.steps) == 3
