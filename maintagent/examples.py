"""Kayıtlı ajan çalıştırmaları.

Demo ziyaretçisi, öneri düğmelerine bastığında gerçek bir çalıştırmanın kaydını izler:
beklemez ve Groq'un günlük token hakkını harcamaz. Kayıtlar scripts/record_examples.py ile
gerçek LLM'le alınır ve arayüzde "kayıtlı çalıştırma" diye açıkça işaretlenir.
Elle yazılmış ya da düzenlenmiş kayıt yoktur.
"""

import json
import re
import time
from pathlib import Path
from typing import Callable, Iterator

from maintagent.work_orders import WorkOrderStore

MAX_GAP_SECONDS = 1.2  # adımlar arası bekleme kısaltılır; ziyaretçi Groq sınırını beklemesin


def load_examples(path: Path, as_of) -> list[dict]:
    """Sadece uygulamanın 'şu an'ıyla aynı anda kaydedilmiş örnekler (başka tarihin verisiyle çelişmesin)."""
    if not path.exists():
        return []
    examples = json.loads(path.read_text(encoding="utf-8"))
    return [e for e in examples if e.get("as_of") == str(as_of)]


def replay_events(example: dict, orders: WorkOrderStore, max_gap: float = MAX_GAP_SECONDS,
                  sleep: Callable[[float], None] = time.sleep) -> Iterator[dict]:
    """Kaydı olay olay yeniden üretir.

    Kayıttaki iş emri taslağı canlı kayda da eklenir; böylece ziyaretçi onay akışını
    deneyebilir. Cevaptaki taslak numarası yeni numarayla değiştirilir.
    """
    yield {"type": "replay", "question": example["question"], "recorded_at": example["recorded_at"],
           "llm": example["llm"]}
    previous, id_map = 0.0, {}
    for event in example["events"]:
        if event["type"] == "waiting":  # kayıttaki Groq beklemeleri tekrar oynatılmaz
            continue
        t = event.get("t", previous)
        sleep(min(max(t - previous, 0.0), max_gap))
        previous = t
        out = {k: v for k, v in event.items() if k != "t"}
        if out["type"] == "tool_result" and out["tool"] == "draft_work_order" \
                and isinstance(out["result"].get("is_emri"), dict):
            old = out["result"]["is_emri"]
            new = orders.open_draft(old["machine_id"], old["component"]) or orders.create(
                machine_id=old["machine_id"], component=old["component"], risk_pct=old["risk_pct"],
                reason=old["reason"], steps=old["steps"], parts=old["parts"],
                estimated_hours=old["estimated_hours"], manual_section=old["manual_section"])
            id_map[old["id"]] = new["id"]
            out = {**out, "result": {**out["result"], "is_emri": new}}
        if out["type"] == "answer" and id_map:
            out["content"] = re.sub(r"#(\d+)", lambda m: f"#{id_map.get(int(m.group(1)), m.group(1))}",
                                    out["content"])
        yield out
