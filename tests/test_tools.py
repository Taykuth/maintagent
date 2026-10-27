"""Araçların doğru veri döndürdüğünü ve as_of sonrasını görmediğini kontrol eder."""

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from maintagent import config  # noqa: E402
from maintagent.agent import EVIDENCE_TOOLS, run_agent  # noqa: E402
from maintagent.db import load_all  # noqa: E402
from maintagent.features import build_features  # noqa: E402
from maintagent.manual import ManualSearch, load_chunks  # noqa: E402
from maintagent.model import save, train  # noqa: E402
from maintagent.synthetic import write_synthetic_csvs  # noqa: E402
from maintagent.tools import TOOL_SCHEMAS, Toolbox, describe_feature  # noqa: E402

AS_OF = datetime(2015, 6, 15, 12)


@pytest.fixture(scope="module")
def toolbox(tmp_path_factory):
    d = tmp_path_factory.mktemp("data")
    write_synthetic_csvs(d / "raw", n_machines=6, seed=3)
    con = load_all(d / "raw", d / "t.duckdb")
    model = train(build_features(con, datetime(2015, 1, 2), datetime(2015, 5, 1)))
    save(model, {}, d / "models")
    manual = ManualSearch(load_chunks(config.MANUAL_PATH), "bm25")
    return Toolbox(con, d / "models", AS_OF, manual=manual)


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
        tele = toolbox.get_telemetry_summary(1, hours=24)
        last_ts = con.execute("SELECT max(ts) FROM telemetry WHERE machine_id = 1 AND ts <= $a", {"a": AS_OF}).fetchone()[0]
        assert last_ts <= AS_OF and tele["pencere_saat"] == 24
    finally:
        con.execute("DELETE FROM errors WHERE error_id = 'error9'")
        con.execute("DELETE FROM maint WHERE ts = '2015-06-15 13:00:00' AND machine_id = 1")


def test_risk_prediction(toolbox):
    r = toolbox.predict_failure_risk(2)
    assert 0 <= r["ariza_riski_24_saat_yuzde"] <= 100
    assert r["en_olasi_bilesen"] in {"comp1", "comp2", "comp3", "comp4"}
    assert len(r["riski_en_cok_artiran_3_etken"]) == 3


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


# --- Ajan döngüsü: gerçek LLM yerine senaryolu sahte bir LLM ile -------------

class ScriptedLLM:
    """Önceden yazılmış cevapları sırayla döndürür ve gelen mesajları kaydeder."""

    def __init__(self, replies):
        self.replies, self.seen = list(replies), []

    def chat(self, messages, tools):
        self.seen.append(list(messages))
        return self.replies.pop(0)


def call(name, **args):
    return {"content": "", "tool_calls": [{"id": f"c_{name}", "name": name, "arguments": json.dumps(args)}]}


def test_agent_calls_tool_then_answers(toolbox):
    llm = ScriptedLLM([call("get_machine_info", machine_id=1), {"content": "Bitti.", "tool_calls": []}])
    events = []
    res = run_agent("Makine 1?", toolbox, llm, on_event=events.append)
    assert res.answer == "Bitti." and len(res.steps) == 1
    assert [e["type"] for e in events] == ["tool_call", "tool_result", "answer"]
    tool_msg = llm.seen[1][-1]
    assert tool_msg["role"] == "tool" and '"machine_id": 1' in tool_msg["content"]


def test_agent_survives_bad_tool_and_bad_args(toolbox):
    bad_name = {"content": "", "tool_calls": [{"id": "x", "name": "delete_everything", "arguments": "{}"}]}
    bad_args = {"content": "", "tool_calls": [{"id": "y", "name": "get_machine_info", "arguments": "{bozuk"}]}
    missing = call("get_machine_info", machine_id=999)
    llm = ScriptedLLM([bad_name, bad_args, missing, {"content": "Tamam.", "tool_calls": []}])
    res = run_agent("?", toolbox, llm)
    assert res.answer == "Tamam."
    assert all("hata" in s["result"] for s in res.steps)


def test_agent_requires_evidence_before_explaining_risk(toolbox):
    """Model riske bakıp hemen cevap verirse döngü geri çevirir ve eksik araçları söyler."""
    llm = ScriptedLLM([
        call("predict_failure_risk", machine_id=1),
        {"content": "Erken cevap.", "tool_calls": []},
        call("get_telemetry_summary", machine_id=1),
        call("get_recent_errors", machine_id=1),
        call("get_maintenance_history", machine_id=1),
        call("search_manual", query="rulman kontrol adımları"),
        {"content": "Tam cevap.", "tool_calls": []},
    ])
    events = []
    res = run_agent("Makine 1 neden riskli?", toolbox, llm, on_event=events.append)
    assert res.answer == "Tam cevap." and len(res.steps) == 5
    nudges = [e for e in events if e["type"] == "nudge"]
    assert len(nudges) == 1 and nudges[0]["missing"] == {1: [*EVIDENCE_TOOLS, "search_manual"]}
    nudge_msg = llm.seen[2][-1]
    assert nudge_msg["role"] == "user" and "get_telemetry_summary" in nudge_msg["content"]


def test_agent_nudges_only_once(toolbox):
    llm = ScriptedLLM([call("predict_failure_risk", machine_id=1),
                       {"content": "a", "tool_calls": []},
                       {"content": "b", "tool_calls": []}])
    events = []
    res = run_agent("?", toolbox, llm, on_event=events.append)
    assert res.answer == "b" and [e["type"] for e in events].count("nudge") == 1


def test_ranking_question_needs_no_extra_evidence(toolbox):
    llm = ScriptedLLM([call("rank_machines_by_risk", top_n=3), {"content": "Liste.", "tool_calls": []}])
    events = []
    res = run_agent("En riskli 3 makine?", toolbox, llm, on_event=events.append)
    assert res.answer == "Liste." and all(e["type"] != "nudge" for e in events)


def test_agent_stops_at_step_limit(toolbox):
    llm = ScriptedLLM([call("get_machine_info", machine_id=1)] * 3)
    res = run_agent("?", toolbox, llm, max_steps=3)
    assert res.stopped_early and len(res.steps) == 3
