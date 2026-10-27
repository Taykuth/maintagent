"""HTTP API. Arayüz (Next.js) bu uç noktaları kullanır.

Çalıştırma:
    uvicorn maintagent.api:create_app --factory --reload

Uç noktalar:
    GET  /api/health                      durum ve ayarlar
    GET  /api/machines                    tüm makineler, riske göre sıralı
    GET  /api/machines/{id}               tek makinenin raporu
    GET  /api/machines/{id}/telemetry     grafik için saatlik sensör verisi ve olaylar
    POST /api/ask                         ajana soru; adımlar SSE ile canlı akar
    GET  /api/work-orders                 iş emri taslakları ve kararlar
    POST /api/work-orders/{id}/approve    insan onayı
    POST /api/work-orders/{id}/reject     insan reddi

Tasarım notları:
  - Ajan senkron çalışır; ayrı bir iş parçacığında koşar ve olayları bir kuyruğa
    yazar. Yanıt bu kuyruğu Server-Sent Events olarak akıtır.
  - Aynı anda tek ajan çalışır. Groq ücretsiz katmanında dakikalık token sınırı
    düşük; iki ajan aynı anda çalışırsa ikisi de sınıra takılır.
  - DuckDB bağlantısı iş parçacıkları arasında paylaşılmaz; her istek cursor() ile
    kendi bağlantısını alır.
"""

import json
import logging
import queue
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import duckdb
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from maintagent.agent import DRAFT_RISK_THRESHOLD, LLM, GroqLLM, LLMError, run_agent
from maintagent.manual import ManualSearch, load_chunks
from maintagent.model import load
from maintagent.tools import COMP_TR, Toolbox
from maintagent.work_orders import STATUSES, WorkOrderStore

log = logging.getLogger("maintagent.api")


@dataclass
class AppState:
    con: duckdb.DuckDBPyConnection
    model_dir: Path
    as_of: datetime
    manual: ManualSearch
    orders: WorkOrderStore
    make_llm: Callable[[], LLM]
    llm_name: str = ""
    manual_method: str = ""
    draft_threshold: float = DRAFT_RISK_THRESHOLD
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:3000"])
    agent_lock: threading.Lock = field(default_factory=threading.Lock)
    _model: object = None
    _machines: list[dict] | None = None
    _cache_lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def from_config(cls) -> "AppState":
        from maintagent import config

        if not config.DB_PATH.exists():
            raise RuntimeError(f"Veritabanı yok: {config.DB_PATH}. Önce python scripts/load_data.py çalıştır.")
        return cls(
            con=duckdb.connect(str(config.DB_PATH), read_only=True),
            model_dir=config.ROOT_DIR / "models",
            as_of=config.AS_OF,
            manual=ManualSearch(load_chunks(config.MANUAL_PATH), config.MANUAL_SEARCH),
            orders=WorkOrderStore(config.WORK_ORDERS_DB),
            make_llm=lambda: GroqLLM(config.GROQ_API_KEY, config.GROQ_MODEL, config.GROQ_BASE_URL),
            llm_name=config.GROQ_MODEL,
            manual_method=config.MANUAL_SEARCH,
            cors_origins=config.CORS_ORIGINS,
        )

    def toolbox(self) -> Toolbox:
        if self._model is None and (self.model_dir / "risk_model.txt").exists():
            self._model = load(self.model_dir)
        return Toolbox(self.con.cursor(), self.model_dir, self.as_of, manual=self.manual,
                       orders=self.orders, model=self._model)

    def machines(self) -> list[dict]:
        """Tüm makinelerin riski. 'Şu an' sabit olduğu için bir kez hesaplanır."""
        with self._cache_lock:
            if self._machines is None:
                df = self.toolbox().all_risks()
                self._machines = [
                    {"machine_id": int(r.machine_id), "model": r.model, "age": int(r.age),
                     "risk_pct": round(float(r.risk) * 100, 1), "likely_comp": r.likely_comp,
                     "comp_name": COMP_TR[r.likely_comp]}
                    for r in df.itertuples()]
            return self._machines


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class DecisionBody(BaseModel):
    note: str = Field(default="", max_length=500)


def create_app(state: AppState | None = None) -> FastAPI:
    state = state or AppState.from_config()
    app = FastAPI(title="MaintAgent API")
    app.add_middleware(CORSMiddleware, allow_origins=state.cors_origins, allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(RuntimeError)
    def not_ready(request, exc: RuntimeError):
        # Örneğin model dosyası yoksa: sunucu çalışıyor ama hizmet veremiyor.
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    def machine_or_404(fn, machine_id: int, *args):
        try:
            return fn(machine_id, *args)
        except ValueError as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/api/health")
    def health():
        return {"ok": True, "as_of": str(state.as_of), "llm": state.llm_name, "manual_search": state.manual_method,
                "draft_threshold": state.draft_threshold}

    @app.get("/api/machines")
    def machines():
        return state.machines()

    @app.get("/api/machines/{machine_id}")
    def machine(machine_id: int):
        return machine_or_404(state.toolbox().get_machine_report, machine_id)

    @app.get("/api/machines/{machine_id}/telemetry")
    def telemetry(machine_id: int, hours: int = 168):
        return machine_or_404(state.toolbox().telemetry_series, machine_id, hours)

    @app.post("/api/ask")
    def ask(body: AskBody):
        if not state.agent_lock.acquire(blocking=False):
            raise HTTPException(429, "Ajan şu an başka bir soruyu cevaplıyor; biraz sonra tekrar dene.")
        events: queue.Queue = queue.Queue()

        def work():
            try:
                run_agent(body.question, state.toolbox(), state.make_llm(), on_event=events.put,
                          draft_threshold=state.draft_threshold)
            except LLMError as e:
                events.put({"type": "error", "message": str(e)})
            except Exception:  # noqa: BLE001
                # API sınırında her hatayı yakalıyoruz: kullanıcı yarım kalmış bir akış yerine
                # anlamlı bir mesaj görsün. Hata gizlenmiyor; ayrıntısı loga yazılıyor.
                log.exception("Ajan çalıştırması başarısız")
                events.put({"type": "error", "message": "Beklenmeyen bir hata oluştu."})
            finally:
                state.agent_lock.release()
                events.put(None)  # akışın bittiğini bildirir

        threading.Thread(target=work, daemon=True).start()

        def stream():
            while (event := events.get()) is not None:
                data = json.dumps(event, ensure_ascii=False, default=str)
                yield f"event: {event['type']}\ndata: {data}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/work-orders")
    def work_orders(status: str | None = None):
        if status and status not in STATUSES:
            raise HTTPException(400, f"Geçersiz durum. Seçenekler: {STATUSES}")
        return state.orders.list(status)

    def decide(order_id: int, approve: bool, note: str):
        try:
            return state.orders.decide(order_id, approve, note)
        except KeyError as e:
            raise HTTPException(404, f"İş emri {order_id} bulunamadı.") from e
        except ValueError as e:
            raise HTTPException(409, str(e)) from e

    @app.post("/api/work-orders/{order_id}/approve")
    def approve(order_id: int, body: DecisionBody | None = None):
        return decide(order_id, True, body.note if body else "")

    @app.post("/api/work-orders/{order_id}/reject")
    def reject(order_id: int, body: DecisionBody | None = None):
        return decide(order_id, False, body.note if body else "")

    return app
