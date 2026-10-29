"""Herkese açık demo için statik dışa aktarım.

Uygulamanın "şu an"ı sabit (veri setinin bir tarihi). Bu yüzden makine listesi, raporlar ve
grafik verisi hiç değişmez; bir kez hesaplanıp JSON olarak arayüzün içine konabilir. Böylece
demo sunucusuz çalışır: ücretsiz, uyumaz, anında açılır.

Ajan tarafı, gerçek LLM'le alınmış kayıtlı çalıştırmalarla gösterilir (scripts/record_examples.py).
Canlı soru bu modda yoktur; onun için proje yerelde çalıştırılır.

Dosyalar API'nin kendisinden alınır (FastAPI TestClient). Arayüzün canlı ve statik modda
gördüğü veri bu yüzden birebir aynıdır.
"""

import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from maintagent.api import AppState, create_app

# Arayüz grafik için son 7 günü ve bir önceki günü ister (MachineView: 7 * 24 + 23 saat)
TELEMETRY_HOURS = 7 * 24 + 23


def _write(path: Path, data) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


def export_static(state: AppState, out_dir: Path) -> dict:
    """API yanıtlarını out_dir altına yazar. Eski dosyalar silinir. Özet döndürür."""
    client = TestClient(create_app(state))

    def get(path: str):
        r = client.get(path)
        r.raise_for_status()
        return r.json()

    if out_dir.exists():
        shutil.rmtree(out_dir)
    size = 0
    health = get("/api/health")
    # Statik demoda canlı soru yok; arayüz bunu NEXT_PUBLIC_DEMO_MODE=static ile bilir.
    size += _write(out_dir / "health.json", {**health, "live_left_today": None})
    machines = get("/api/machines")
    size += _write(out_dir / "machines.json", machines)
    for m in machines:
        mid = m["machine_id"]
        size += _write(out_dir / "machines" / f"{mid}.json", get(f"/api/machines/{mid}"))
        size += _write(out_dir / "telemetry" / f"{mid}.json",
                       get(f"/api/machines/{mid}/telemetry?hours={TELEMETRY_HOURS}"))
    # Kayıtlar olayları ve zamanlarıyla birlikte; oynatma tarayıcıda yapılır.
    size += _write(out_dir / "examples.json", state.examples)
    return {"machines": len(machines), "examples": len(state.examples), "bytes": size}
