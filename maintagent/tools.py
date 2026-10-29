"""Ajanın veriye ulaştığı araçlar.

Kural: her araç yalnızca `as_of` anına kadarki veriyi görür. Ajan gelecekteki
arızaları, hataları ya da sensör değerlerini asla göremez.

Araçlar ham tablo değil özet döndürür. Hesaplamayı Python yapar, LLM yorumlar.
Bu hem daha ucuz hem de modelin sayıları yanlış hesaplama riskini azaltır.
"""

from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd

from maintagent.features import COMPS, SENSORS, features_at
from maintagent.manual import ManualSearch, component_specs
from maintagent.model import load, predict, top_factors
from maintagent.work_orders import WorkOrderStore

SENSOR_TR = {"volt": "voltaj", "rotate": "dönüş hızı", "pressure": "basınç", "vibration": "titreşim"}

# Veri seti bileşenlerin ve hata kodlarının ne olduğunu söylemez. İsimler kurgusaldır,
# ama eşleşmeler veriden gelir: her bileşenin arızasından önce hangi sensörün kaydığı
# ve hangi hata kodunun sıklaştığı (bkz. data/manual/kilavuz.md).
COMP_TR = {"comp1": "güç ünitesi", "comp2": "ana mil rulmanı",
           "comp3": "hidrolik valf bloğu", "comp4": "motor-mil kaplini"}
ERROR_TR = {"error1": "E1 - besleme gerilimi regülasyon uyarısı", "error2": "E2 - mil hızı hedefin altında",
            "error3": "E3 - motor aşırı yük", "error4": "E4 - hidrolik basınç üst sınır",
            "error5": "E5 - titreşim eşik aşımı"}


def describe_feature(name: str) -> str:
    """Model özellik adını insanın okuyacağı Türkçe açıklamaya çevirir."""
    parts = name.split("_")
    if parts[0] in SENSOR_TR:
        stat = "ortalaması" if parts[1] == "mean" else "dalgalanması"
        return f"{SENSOR_TR[parts[0]]} {parts[2].replace('h', ' saatlik')} {stat}"
    if parts[0] in ERROR_TR:
        return f"son 24 saatteki {ERROR_TR[parts[0]].split(' - ')[0]} ({parts[0]}) hata sayısı"
    if parts[0] in COMP_TR:
        return f"{parts[0]} ({COMP_TR[parts[0]]}) kaç gündür değişmedi"
    if name == "age":
        return "makinenin yaşı"
    return name


class Toolbox:
    def __init__(self, con: duckdb.DuckDBPyConnection, model_dir: Path, as_of: datetime,
                 manual: ManualSearch | None = None, orders: WorkOrderStore | None = None, model=None):
        self.con = con
        self.as_of = as_of
        self.model_dir = model_dir
        self.manual = manual
        self.orders = orders
        self._model = model  # API, modeli bir kez yükleyip her isteğe paylaştırır

    # --- yardımcılar ---------------------------------------------------------

    def _model_or_error(self):
        if self._model is None:
            if not (self.model_dir / "risk_model.txt").exists():
                raise RuntimeError("Model dosyası yok. Önce python scripts/train_model.py çalıştır.")
            self._model = load(self.model_dir)
        return self._model

    def _check_machine(self, machine_id: int) -> None:
        n = self.con.execute("SELECT count(*) FROM machines WHERE machine_id = $m", {"m": int(machine_id)}).fetchone()[0]
        if not n:
            raise ValueError(f"Makine {machine_id} bulunamadı. Geçerli numaralar 1-100 arası.")

    def _q(self, sql: str, **params) -> pd.DataFrame:
        # DuckDB, SQL'de kullanılmayan parametre gönderilince hata verir; sadece kullanılanları geç.
        params = {"as_of": self.as_of, **params}
        return self.con.execute(sql, {k: v for k, v in params.items() if f"${k}" in sql}).df()

    # --- araçlar -------------------------------------------------------------

    def get_machine_info(self, machine_id: int) -> dict:
        self._check_machine(machine_id)
        row = self._q("SELECT model, age FROM machines WHERE machine_id = $m", m=machine_id).iloc[0]
        return {"machine_id": machine_id, "model": row.model, "age_years": int(row.age)}

    def get_telemetry_summary(self, machine_id: int, hours: int = 48) -> dict:
        """Son `hours` saatin ortalamasını, makinenin önceki 30 günlük normaliyle karşılaştırır."""
        self._check_machine(machine_id)
        hours = max(1, min(int(hours), 168))
        window_start = self.as_of - timedelta(hours=hours)
        base_start = window_start - timedelta(days=30)
        aggs = ", ".join(
            f"avg({s}) FILTER (WHERE ts > $ws) AS {s}_recent, "
            f"avg({s}) FILTER (WHERE ts <= $ws) AS {s}_base, "
            f"stddev_samp({s}) FILTER (WHERE ts <= $ws) AS {s}_base_std, "
            f"arg_max({s}, ts) AS {s}_last"
            for s in SENSORS
        )
        r = self._q(f"SELECT {aggs} FROM telemetry WHERE machine_id = $m AND ts > $bs AND ts <= $as_of",
                    m=machine_id, ws=window_start, bs=base_start).iloc[0]
        sensors = {}
        for s in SENSORS:
            z = (r[f"{s}_recent"] - r[f"{s}_base"]) / r[f"{s}_base_std"] if r[f"{s}_base_std"] else 0.0
            sensors[s] = {
                "son_deger": round(float(r[f"{s}_last"]), 1),
                f"son_{hours}_saat_ortalama": round(float(r[f"{s}_recent"]), 1),
                "normal_ortalama_30_gun": round(float(r[f"{s}_base"]), 1),
                "normale_gore_degisim_yuzde": round(float((r[f"{s}_recent"] / r[f"{s}_base"] - 1) * 100), 1),
                "sapma_z": round(float(z), 2),
            }
        flagged = [SENSOR_TR[s] for s, v in sensors.items()
                   if abs(v["sapma_z"]) >= 1 or abs(v["normale_gore_degisim_yuzde"]) >= 10]
        return {"machine_id": machine_id, "pencere_saat": hours, "sensorler": sensors,
                "normalden_belirgin_sapan": flagged,
                "not": "Normal = önceki 30 günün ortalaması. Değişim %10'u ya da sapma 1 standart sapmayı geçerse belirgin sayılır."}

    def get_recent_errors(self, machine_id: int, days: int = 7) -> dict:
        self._check_machine(machine_id)
        days = max(1, min(int(days), 90))
        df = self._q("""
            SELECT error_id, count(*) AS adet, max(ts) AS son_gorulme
            FROM errors WHERE machine_id = $m AND ts > $as_of - to_days($d) AND ts <= $as_of
            GROUP BY error_id ORDER BY adet DESC""", m=machine_id, d=days)
        return {"machine_id": machine_id, "son_gun": days, "toplam_hata": int(df.adet.sum()) if len(df) else 0,
                "hatalar": [{"hata": r.error_id, "anlami": ERROR_TR.get(r.error_id, "bilinmiyor"),
                             "adet": int(r.adet), "son_gorulme": str(r.son_gorulme)} for r in df.itertuples()]}

    def get_maintenance_history(self, machine_id: int) -> dict:
        """Her bileşenin en son ne zaman ve neden (planlı/arıza) değiştirildiğini döndürür."""
        self._check_machine(machine_id)
        df = self._q("""
            SELECT m.comp, max(m.ts) AS son_degisim
            FROM maint m WHERE m.machine_id = $m AND m.ts <= $as_of GROUP BY m.comp""", m=machine_id)
        fails = self._q("SELECT comp, ts FROM failures WHERE machine_id = $m AND ts <= $as_of", m=machine_id)
        fail_set = {(r.comp, r.ts) for r in fails.itertuples()}
        last = {r.comp: r.son_degisim for r in df.itertuples()}
        comps = []
        for c in COMPS:
            ts = last.get(c)
            comps.append({
                "bilesen": c,
                "ad": COMP_TR[c],
                "son_degisim": str(ts) if ts is not None else None,
                "kac_gundur_degismedi": round((self.as_of - ts).total_seconds() / 86400, 1) if ts is not None else None,
                "son_degisim_nedeni": None if ts is None else ("arıza" if (c, ts) in fail_set else "planlı bakım"),
            })
        return {"machine_id": machine_id, "bilesenler": comps, "gecmis_ariza_sayisi": len(fails)}

    def predict_failure_risk(self, machine_id: int) -> dict:
        self._check_machine(machine_id)
        machine_id = int(machine_id)
        model = self._model_or_error()
        row = features_at(self.con, self.as_of)
        row = row[row.machine_id == machine_id]
        p = predict(model, row).iloc[0]
        factors = top_factors(model, row, p.likely_comp, k=3)
        return {
            "machine_id": machine_id,
            "ariza_riski_24_saat_yuzde": round(float(p.risk) * 100, 1),
            "en_olasi_bilesen": p.likely_comp,
            "bilesen_adi": COMP_TR[p.likely_comp],
            "riski_en_cok_artiran_3_etken": [
                {"etken": describe_feature(f["feature"]), "deger": round(f["value"], 2)} for f in factors
            ],
            "not": "Risk, modelin önümüzdeki 24 saatte herhangi bir bileşenin arızalanma olasılığıdır.",
        }

    def rank_machines_by_risk(self, top_n: int = 5) -> dict:
        model = self._model_or_error()
        top_n = max(1, min(int(top_n), 20))
        preds = predict(model, features_at(self.con, self.as_of)).sort_values("risk", ascending=False).head(top_n)
        return {"an": str(self.as_of), "makineler": [
            {"machine_id": int(r.machine_id), "ariza_riski_yuzde": round(float(r.risk) * 100, 1),
             "en_olasi_bilesen": r.likely_comp, "bilesen_adi": COMP_TR[r.likely_comp]}
            for r in preds.itertuples()]}

    def search_manual(self, query: str, k: int = 3) -> dict:
        """Bakım kılavuzunda arar; en alakalı k bölümü döndürür."""
        if self.manual is None:
            raise RuntimeError("Kılavuz araması yüklenmedi.")
        if not query or not query.strip():
            raise ValueError("Arama sorgusu boş olamaz.")
        found = self.manual.search(query, k=max(1, min(int(k), 5)))
        if not found:
            return {"sorgu": query, "sonuclar": [], "not": "Kılavuzda eşleşen bölüm bulunamadı; farklı kelimelerle dene."}
        return {"sorgu": query, "sonuclar": [{"bolum": c.title, "metin": c.text} for c in found]}

    def get_machine_report(self, machine_id: int) -> dict:
        """Ajanın bir makine için ihtiyaç duyduğu kanıt tek çağrıda: risk, sensörler, hatalar, bakım.

        Önce bunlar beş ayrı araçtı. Her araç çağrısı LLM'e bir tur daha demek ve her turda
        bütün konuşma yeniden gönderiliyor; Groq'un dakikalık token sınırına takılıyorduk.
        Sık birlikte çağrılan araçları birleştirmek tur sayısını ve tokenı azaltır.
        """
        info = self.get_machine_info(machine_id)
        risk = self.predict_failure_risk(machine_id)
        tele = self.get_telemetry_summary(machine_id, hours=24)
        errors = self.get_recent_errors(machine_id, days=7)
        maint = self.get_maintenance_history(machine_id)
        return {
            "makine": {"id": info["machine_id"], "model": info["model"], "yas": info["age_years"]},
            "risk": {k: risk[k] for k in ("ariza_riski_24_saat_yuzde", "en_olasi_bilesen", "bilesen_adi",
                                          "riski_en_cok_artiran_3_etken")},
            "sensorler_son_24_saat": {
                SENSOR_TR[s]: {"ortalama": v["son_24_saat_ortalama"], "normal_30_gun": v["normal_ortalama_30_gun"],
                               "degisim_yuzde": v["normale_gore_degisim_yuzde"]}
                for s, v in tele["sensorler"].items()},
            "normalden_belirgin_sapan": tele["normalden_belirgin_sapan"],
            "hatalar_son_7_gun": [{"kod": e["hata"], "anlami": e["anlami"], "adet": e["adet"]} for e in errors["hatalar"]],
            "bilesen_degisimleri": [{"bilesen": c["bilesen"], "ad": c["ad"], "kac_gundur": c["kac_gundur_degismedi"],
                                     "son_neden": c["son_degisim_nedeni"]} for c in maint["bilesenler"]],
        }

    def draft_work_order(self, machine_id: int, component: str, reason: str, steps: list[str],
                         manual_section: str | None = None, **ignored) -> dict:
        """Bakım şefinin onayına sunulacak iş emri taslağı oluşturur. Onaylamaz.

        Model sadece gerekçeyi ve adımları yazar. Öncelik modelin riskinden kılavuz kuralıyla,
        süre ve parçalar kılavuzun "Süre, parça ve öncelik" bölümünden kodla belirlenir.
        Model yine de süre ya da parça gönderirse (ignored) dikkate alınmaz.
        """
        if self.orders is None:
            raise RuntimeError("İş emri kaydı yapılandırılmadı.")
        self._check_machine(machine_id)
        machine_id = int(machine_id)
        if component not in COMP_TR:
            raise ValueError(f"Bilinmeyen bileşen: {component}. Seçenekler: {sorted(COMP_TR)}")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("Gerekçe boş olamaz; risk, sensör ve hata kodlarını sayılarla yaz.")
        if not isinstance(steps, list) or not steps or not all(isinstance(s, str) and s.strip() for s in steps):
            raise ValueError("En az bir adım yaz (metin listesi).")
        existing = self.orders.open_draft(machine_id, component)
        if existing:
            return {"is_emri": existing, "not": "Bu makine ve bileşen için onay bekleyen bir taslak zaten var; yenisi açılmadı."}
        risk = self.predict_failure_risk(machine_id)["ariza_riski_24_saat_yuzde"]
        spec = self._specs().get(component, {})
        order = self.orders.create(
            machine_id=machine_id, component=component, risk_pct=risk, reason=reason.strip(),
            steps=[s.strip() for s in steps], parts=spec.get("parcalar", []),
            estimated_hours=spec.get("saat"), manual_section=manual_section or spec.get("bolum"))
        note = "Taslak oluşturuldu ve bakım şefinin onayını bekliyor."
        if spec:
            note += f" Süre ({spec['saat']:g} saat, {spec['ekip']}) ve parçalar kılavuzdan eklendi."
        return {"is_emri": order, "not": note}

    def _specs(self) -> dict[str, dict]:
        if not hasattr(self, "_spec_cache"):
            self._spec_cache = component_specs(self.manual.chunks) if self.manual else {}
        return self._spec_cache

    # --- arayüz için (ajan aracı değil) --------------------------------------

    def all_risks(self) -> pd.DataFrame:
        """Tüm makinelerin riski, modeli ve yaşı; riske göre sıralı."""
        preds = predict(self._model_or_error(), features_at(self.con, self.as_of))
        machines = self._q("SELECT machine_id, model, age FROM machines")
        return preds.merge(machines, on="machine_id").sort_values("risk", ascending=False)

    def telemetry_series(self, machine_id: int, hours: int = 168) -> dict:
        """Grafik için saatlik sensör değerleri ve aynı penceredeki hata/bakım olayları."""
        self._check_machine(machine_id)
        hours = max(1, min(int(hours), 24 * 30))
        start = self.as_of - timedelta(hours=hours)
        points = self._q("""SELECT ts, volt, rotate, pressure, vibration FROM telemetry
                            WHERE machine_id = $m AND ts > $s AND ts <= $as_of ORDER BY ts""", m=machine_id, s=start)
        events = self._q("""
            SELECT ts, 'hata' AS tur, error_id AS kod FROM errors WHERE machine_id = $m AND ts > $s AND ts <= $as_of
            UNION ALL
            SELECT ts, 'bakim', comp FROM maint WHERE machine_id = $m AND ts > $s AND ts <= $as_of
            ORDER BY ts""", m=machine_id, s=start)
        points["ts"] = points.ts.astype(str)
        events["ts"] = events.ts.astype(str)
        return {"machine_id": int(machine_id), "points": points.round(2).to_dict("records"),
                "events": events.to_dict("records")}


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": required}}}


MACHINE = {"machine_id": {"type": "integer"}}

# LLM'e gösterilen araçlar. Her tanım her turda yeniden gönderildiği için kısa tutuldu.
# get_machine_info, predict_failure_risk ve get_maintenance_history metot olarak duruyor
# (rapor ve API kullanıyor) ama ajana ayrı araç olarak verilmiyor.
TOOL_SCHEMAS = [
    _fn("get_machine_report",
        "Bir makinenin tam durumu: 24 saatlik arıza riski ve etkenleri, sensörlerin normale göre değişimi, "
        "son 7 günün hata kodları, bileşenlerin kaç gündür değişmediği.", MACHINE, ["machine_id"]),
    _fn("get_telemetry_summary", "Sensör ortalamalarını özel bir pencerede (saat) normalle karşılaştırır.",
        {**MACHINE, "hours": {"type": "integer", "description": "1-168"}}, ["machine_id"]),
    _fn("get_recent_errors", "Son N günün hata kodları ve sayıları.",
        {**MACHINE, "days": {"type": "integer", "description": "1-90"}}, ["machine_id"]),
    _fn("rank_machines_by_risk", "Makineleri arıza riskine göre sıralar.",
        {"top_n": {"type": "integer", "description": "1-20, varsayılan 5"}}, []),
    _fn("search_manual",
        "Bakım kılavuzunda arar: arıza belirtileri, kontrol adımları, değişim prosedürü, süre ve parça, "
        "hata kodları, güvenlik, iş emri kuralları.",
        {"query": {"type": "string", "description": "ör. 'ana mil rulmanı kontrol adımları'"},
         "k": {"type": "integer", "description": "1-5, varsayılan 3"}}, ["query"]),
    _fn("draft_work_order",
        "Bakım şefinin onayına iş emri taslağı oluşturur. Öncelik, süre ve parçalar otomatik eklenir. Onaylamaz.",
        {**MACHINE,
         "component": {"type": "string", "enum": COMPS},
         "reason": {"type": "string", "description": "Sayılarla gerekçe: risk, sensör sapması, hata kodları"},
         "steps": {"type": "array", "items": {"type": "string"}, "description": "Kılavuzdaki adımlar"},
         "manual_section": {"type": "string", "description": "Adımların alındığı kılavuz bölümü"}},
        ["machine_id", "component", "reason", "steps"]),
]
