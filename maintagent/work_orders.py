"""İş emri taslakları ve onay kaydı.

Ajan yalnızca taslak oluşturabilir. Onay ya da ret insan tarafından API üzerinden
verilir; ajanın araçları arasında onaylama yoktur.

Analiz verisi DuckDB'de salt okunur durur. İş emirleri ise küçük, sık yazılan
kayıtlar olduğu için ayrı bir SQLite dosyasında tutulur (Python ile birlikte gelir,
ek kurulum gerektirmez).
"""

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

DRAFT, APPROVED, REJECTED = "taslak", "onaylandi", "reddedildi"
STATUSES = (DRAFT, APPROVED, REJECTED)


def priority_for(risk_pct: float) -> str:
    """Kılavuzdaki öncelik kuralı (İş emri kuralları › Öncelik seviyeleri).

    Önceliği LLM seçmez; kural kodda. LLM'in yanlış öncelik yazma ihtimali kalmaz.
    """
    if risk_pct >= 80:
        return "acil"
    if risk_pct >= 50:
        return "yuksek"
    return "normal"


class WorkOrderStore:
    def __init__(self, path: Path | str):
        # API istekleri farklı iş parçacıklarından gelir; tek bağlantıyı kilitle koruyoruz.
        self._lock = threading.Lock()
        self._con = sqlite3.connect(str(path), check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._con.execute("""
            CREATE TABLE IF NOT EXISTS work_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                machine_id INTEGER NOT NULL,
                component TEXT NOT NULL,
                priority TEXT NOT NULL,
                risk_pct REAL NOT NULL,
                reason TEXT NOT NULL,
                steps TEXT NOT NULL,
                parts TEXT NOT NULL,
                estimated_hours REAL,
                manual_section TEXT,
                status TEXT NOT NULL,
                decided_at TEXT,
                note TEXT
            )""")
        self._con.commit()

    def create(self, *, machine_id: int, component: str, risk_pct: float, reason: str, steps: list[str],
               parts: list[str], estimated_hours: float | None, manual_section: str | None) -> dict:
        with self._lock:
            cur = self._con.execute(
                """INSERT INTO work_orders (created_at, machine_id, component, priority, risk_pct, reason,
                       steps, parts, estimated_hours, manual_section, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (_now(), machine_id, component, priority_for(risk_pct), risk_pct, reason,
                 json.dumps(steps, ensure_ascii=False), json.dumps(parts, ensure_ascii=False),
                 estimated_hours, manual_section, DRAFT))
            self._con.commit()
            return self._get(cur.lastrowid)

    def get(self, order_id: int) -> dict | None:
        with self._lock:
            return self._get(order_id)

    def list(self, status: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM work_orders", ()
        if status:
            sql, args = sql + " WHERE status = ?", (status,)
        with self._lock:
            return [_row(r) for r in self._con.execute(sql + " ORDER BY id DESC", args)]

    def open_draft(self, machine_id: int, component: str) -> dict | None:
        """Aynı makine ve bileşen için onay bekleyen taslak varsa onu döndürür."""
        with self._lock:
            r = self._con.execute("SELECT * FROM work_orders WHERE machine_id = ? AND component = ? AND status = ?",
                                  (machine_id, component, DRAFT)).fetchone()
            return _row(r) if r else None

    def decide(self, order_id: int, approve: bool, note: str = "") -> dict:
        """Taslağı onaylar ya da reddeder. Sadece taslaklar karar alabilir."""
        with self._lock:
            order = self._get(order_id)
            if order is None:
                raise KeyError(order_id)
            if order["status"] != DRAFT:
                raise ValueError(f"İş emri {order_id} zaten '{order['status']}' durumunda.")
            self._con.execute("UPDATE work_orders SET status = ?, decided_at = ?, note = ? WHERE id = ?",
                              (APPROVED if approve else REJECTED, _now(), note, order_id))
            self._con.commit()
            return self._get(order_id)

    def _get(self, order_id: int) -> dict | None:
        r = self._con.execute("SELECT * FROM work_orders WHERE id = ?", (order_id,)).fetchone()
        return _row(r) if r else None


def _row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["steps"], d["parts"] = json.loads(d["steps"]), json.loads(d["parts"])
    return d


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
