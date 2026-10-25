"""Model için özellik (feature) ve etiket üretimi.

Her örnek bir (makine, zaman) çiftidir ve 3 saatte bir alınır. Özellikler o ana
kadarki veriden hesaplanır, etiket ise SONRAKİ 24 saatten:

    özellikler: (t - 24 saat, t]   -> geçmiş
    etiket:     (t, t + 24 saat]   -> gelecek, sadece eğitimde kullanılır

Bu ayrım bozulursa model geleceği görür ve test sonuçları gerçek dışı çıkar.
tests/test_features.py bunu kontrol eder.
"""

from datetime import datetime, timedelta

import duckdb
import pandas as pd

SENSORS = ["volt", "rotate", "pressure", "vibration"]
ERRORS = ["error1", "error2", "error3", "error4", "error5"]
COMPS = ["comp1", "comp2", "comp3", "comp4"]
MODELS = ["model1", "model2", "model3", "model4"]

FEATURES = (
    [f"{s}_{stat}_{w}" for s in SENSORS for w in ("3h", "24h") for stat in ("mean", "std")]
    + [f"{e}_24h" for e in ERRORS]
    + [f"{c}_days" for c in COMPS]
    + ["age"]
    + [f"is_{m}" for m in MODELS]
)


def build_features(con: duckdb.DuckDBPyConnection, start: datetime, end: datetime,
                   step_hours: int = 3, with_label: bool = True) -> pd.DataFrame:
    """[start, end] aralığında, step_hours'ta bir, her makine için özellik satırı üretir.

    Pencere hesapları için start'tan 24 saat öncesine kadar veri okunur; böylece
    aralığın ilk örnekleri de tam 24 saatlik geçmişle hesaplanır.
    """
    read_from = start - timedelta(hours=24)

    sensor_cols = ",\n".join(
        f"{agg}({s}) OVER w{w} AS {s}_{name}_{w}h"
        for s in SENSORS for w in (3, 24) for name, agg in (("mean", "avg"), ("std", "stddev_samp"))
    )
    err_pivot = ", ".join(f"count(*) FILTER (WHERE error_id = '{e}') AS {e}" for e in ERRORS)
    err_cols = ", ".join(f"coalesce(err.{e}, 0) AS {e}" for e in ERRORS)
    err_roll = ", ".join(f"sum({e}) OVER w24 AS {e}_24h" for e in ERRORS)
    maint_joins = "\n".join(
        f"ASOF LEFT JOIN (SELECT machine_id, ts AS {c}_ts FROM maint WHERE comp = '{c}') {c} "
        f"ON s.machine_id = {c}.machine_id AND s.ts >= {c}.{c}_ts"
        for c in COMPS
    )
    maint_cols = ", ".join(f"date_diff('hour', {c}.{c}_ts, s.ts) / 24.0 AS {c}_days" for c in COMPS)
    model_cols = ", ".join(f"CAST(m.model = '{mo}' AS INTEGER) AS is_{mo}" for mo in MODELS)

    label_join = label_col = ""
    if with_label:
        # En yakın SONRAKİ arıza; 24 saat içindeyse etiketi o bileşen olur.
        label_join = ("ASOF LEFT JOIN (SELECT machine_id, ts AS f_ts, comp AS f_comp FROM failures) f "
                      "ON s.machine_id = f.machine_id AND s.ts < f.f_ts")
        label_col = (", CASE WHEN f.f_ts <= s.ts + INTERVAL 24 HOUR THEN f.f_comp ELSE 'none' END AS label"
                     ", f.f_ts AS next_failure_ts")

    sql = f"""
    WITH err AS (
        SELECT machine_id, date_trunc('hour', ts) AS ts, {err_pivot}
        FROM errors GROUP BY ALL
    ),
    grid AS (
        SELECT t.ts, t.machine_id, {", ".join("t." + s for s in SENSORS)}, {err_cols}
        FROM telemetry t LEFT JOIN err USING (machine_id, ts)
        WHERE t.ts > $read_from AND t.ts <= $end
    ),
    rolled AS (
        SELECT ts, machine_id, {sensor_cols}, {err_roll}
        FROM grid
        WINDOW w3 AS (PARTITION BY machine_id ORDER BY ts RANGE BETWEEN INTERVAL 2 HOUR PRECEDING AND CURRENT ROW),
               w24 AS (PARTITION BY machine_id ORDER BY ts RANGE BETWEEN INTERVAL 23 HOUR PRECEDING AND CURRENT ROW)
    ),
    s AS (
        SELECT * FROM rolled
        WHERE ts >= $start AND ts <= $end AND hour(ts) % {step_hours} = 0
    )
    SELECT s.*, {maint_cols}, m.age, {model_cols} {label_col}
    FROM s
    {maint_joins}
    LEFT JOIN machines m ON s.machine_id = m.machine_id
    {label_join}
    ORDER BY s.machine_id, s.ts
    """
    return con.execute(sql, {"read_from": read_from, "start": start, "end": end}).df()


def features_at(con: duckdb.DuckDBPyConnection, as_of: datetime) -> pd.DataFrame:
    """Her makine için as_of anındaki (ya da hemen öncesindeki) özellik satırı. Etiket yok."""
    df = build_features(con, as_of - timedelta(hours=1), as_of, step_hours=1, with_label=False)
    return df.sort_values("ts").groupby("machine_id").tail(1).reset_index(drop=True)
