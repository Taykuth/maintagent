"""Değerlendirme: senaryo üretimi, uydurma sayı kontrolü ve puanlama. Gerçek LLM kullanılmaz."""

import json
from datetime import datetime, timedelta

import pytest
from conftest import ScriptedLLM, answer, call

from maintagent import config
from maintagent.evaluation import (append_record, is_grounded, load_records, make_scenarios, numbers_in_text,
                                   predicted_component, run_scenario, summarize, ungrounded_numbers)
from maintagent.manual import ManualSearch, load_chunks

START, END = datetime(2015, 6, 1), datetime(2015, 12, 31)


def test_numbers_in_text_reads_turkish_decimals_and_skips_codes():
    text = "Dönüş hızı 377,7; normalin %15.2 altında. E2, comp2, RL-02 ve model3 sayı değil. 4 saat."
    assert numbers_in_text(text) == [377.7, 15.2, 4.0]


@pytest.mark.parametrize("x, ok", [(377.7, True), (378.0, True), (15.2, True), (16.0, False), (999.0, False)])
def test_grounding_allows_rounding_only(x, ok):
    assert is_grounded(x, {377.68, 15.2}) is ok


def test_ungrounded_numbers_finds_the_invented_one():
    steps = [{"tool": "get_machine_report", "result": {"risk": 97.9, "not": "normal 445,6"}}]
    assert ungrounded_numbers("Risk %97,9; normal 446; ayrıca 123.", steps, extra=set()) == [123.0]


def test_predicted_component_prefers_the_draft():
    draft = [{"tool": "draft_work_order", "result": {"is_emri": {"component": "comp3"}}}]
    assert predicted_component("**Durum:** comp1 arızası", draft) == "comp3"
    assert predicted_component("**Durum:** comp4 riskli.\n**Kanıt:** comp1 normal", []) == "comp4"
    assert predicted_component("Risk düşük.", []) is None


@pytest.fixture(scope="module")
def scenarios(synthetic_env):
    con, _ = synthetic_env
    return make_scenarios(con, n_failure=3, n_error_no_failure=2, n_quiet=2, start=START, end=END)


def test_scenarios_match_the_ground_truth(synthetic_env, scenarios):
    con, _ = synthetic_env
    assert [s["tur"] for s in scenarios].count("ariza") == 3
    for s in scenarios:
        as_of, m = datetime.fromisoformat(s["as_of"]), s["machine_id"]
        horizon = 24 if s["tur"] == "ariza" else 72
        found = con.execute("SELECT DISTINCT comp FROM failures WHERE machine_id = $m AND ts > $a AND ts <= $b",
                            {"m": m, "a": as_of, "b": as_of + timedelta(hours=horizon)}).fetchall()
        if s["tur"] == "ariza":
            assert sorted(c for (c,) in found) == s["gercek_bilesenler"]
        else:
            assert found == []
        assert as_of.hour % 3 == 0 and START <= as_of <= END


def test_scenarios_are_reproducible(synthetic_env, scenarios):
    con, _ = synthetic_env
    assert make_scenarios(con, n_failure=3, n_error_no_failure=2, n_quiet=2, start=START, end=END) == scenarios


def test_run_scenario_scores_a_full_run(synthetic_env, scenarios):
    con, model_dir = synthetic_env
    sc = next(s for s in scenarios if s["tur"] == "ariza")
    comp = sc["gercek_bilesenler"][0]
    llm = ScriptedLLM([
        call("get_machine_report", machine_id=sc["machine_id"]),
        call("search_manual", query="kontrol adımları"),
        call("draft_work_order", machine_id=sc["machine_id"], component=comp, reason="r", steps=["Kilitle"]),
        answer(f"**Durum:** {comp} arızası bekleniyor.\n**Kanıt:** 4321 değeri\n**Öneri:** Kilitle, 4 saat."),
    ])
    manual = ManualSearch(load_chunks(config.MANUAL_PATH), "bm25")
    r = run_scenario(sc, con, model_dir, manual, llm, sleep=lambda s: None)
    assert r["taslak"] and r["ajan_bilesen"] == comp and r["bilesen_dogru"] is True
    assert r["dayanaksiz_sayilar"] == [4321.0]  # uydurma sayı yakalandı; "4 saat" kılavuzda geçiyor
    assert r["bicim_ok"] and r["yanlis_alarm"] is None and r["arac_sayisi"] == 3


def test_summary_and_records_roundtrip(tmp_path):
    rec = {"id": "a01", "tur": "ariza", "bilesen_dogru": True, "model_bilesen_dogru": True, "taslak": True,
           "model_risk": 99.0, "ajan_bilesen": "comp1", "model_bilesen": "comp1", "yanlis_alarm": None,
           "dayanaksiz_sayilar": [], "uydurma_birim": ["rpm"], "bicim_ok": True, "adim_kontrolu": False,
           "durdu": False, "arac_sayisi": 3, "token": 9000, "sure_sn": 12.0, "bekleme_sn": 2.0}
    neg = {**rec, "id": "h01", "tur": "hatali_arizasiz", "bilesen_dogru": None, "model_bilesen_dogru": None,
           "taslak": True, "yanlis_alarm": True, "model_risk": 10.0}
    path = tmp_path / "runs.jsonl"
    append_record(path, rec)
    append_record(path, neg)
    records = load_records(path)
    assert [r["id"] for r in records] == ["a01", "h01"]
    table = summarize(records)
    assert "| Bileşen doğru (ajan) | 1/1 (%100) |" in table
    assert "| Yanlış alarm: hatalı-arızasız | 1/1 (%100) |" in table
    assert "| Uydurma birim içeren cevap | 2/2 (%100) |" in table
    json.dumps(records)  # kayıtlar JSON'a çevrilebilir olmalı
