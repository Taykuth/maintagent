"""Modelin neden bu kadar iyi skor aldığını araştıran deney.

Gerçek veride model PR-AUC 0.999 alıyor. Bu kadar yüksek bir skor ya veri
sızıntısına ya da veri setindeki yapay bir desene işaret eder. Bu script iki
soruyu cevaplar:

  1. Hangi özellik grubu skoru taşıyor? (hepsi / hata özellikleri hariç /
     sadece hatalar / sadece telemetri)
  2. Daha ileriyi tahmin etmeye çalışınca skor ne oluyor? (0-24, 24-48,
     48-72 saat sonrası)

Sonuç tablosu README'deki "Sonuçlar neden bu kadar yüksek?" bölümüne girer.

Kullanım:  python scripts/ablation.py
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb  # noqa: E402
import lightgbm as lgb  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.metrics import average_precision_score  # noqa: E402

from maintagent import config  # noqa: E402
from maintagent.features import ERRORS, FEATURES, SENSORS, build_features  # noqa: E402

ERR = [f"{e}_24h" for e in ERRORS]
FEATURE_SETS = {
    "tümü": FEATURES,
    "hatalar hariç": [f for f in FEATURES if f not in ERR],
    "sadece hatalar": ERR,
    "sadece telemetri": [f for f in FEATURES if f.split("_")[0] in SENSORS],
}
HORIZONS = {"0-24 saat": (0, 24), "24-48 saat": (24, 48), "48-72 saat": (48, 72)}


def label_window(df: pd.DataFrame, failures: pd.DataFrame, lo: int, hi: int) -> np.ndarray:
    """(t + lo saat, t + hi saat] aralığında arıza varsa 1, yoksa 0."""
    d = df[["machine_id", "ts"]].copy()
    d["idx"] = np.arange(len(d))
    d["start"] = d.ts + pd.Timedelta(hours=lo)
    m = pd.merge_asof(d.sort_values("start"), failures, left_on="start", right_on="f_ts",
                      by="machine_id", direction="forward", allow_exact_matches=False).sort_values("idx")
    return (m.f_ts <= m.ts + pd.Timedelta(hours=hi)).astype(int).values


def main() -> int:
    con = duckdb.connect(str(config.DB_PATH), read_only=True)
    failures = con.execute("SELECT machine_id, ts AS f_ts FROM failures ORDER BY ts").df()
    print("Özellikler hesaplanıyor...")
    train = build_features(con, datetime(2015, 1, 2), datetime(2015, 8, 1), with_label=False)
    test = build_features(con, datetime(2015, 8, 2), datetime(2015, 12, 31), with_label=False)

    print("\nTest PR-AUC (rastgele tahmin = pozitif oranı):\n")
    print("| Tahmin aralığı | Pozitif oranı | " + " | ".join(FEATURE_SETS) + " |")
    print("|---" * (len(FEATURE_SETS) + 2) + "|")
    for name, (lo, hi) in HORIZONS.items():
        y_tr, y_te = label_window(train, failures, lo, hi), label_window(test, failures, lo, hi)
        cells = []
        for cols in FEATURE_SETS.values():
            clf = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=31, subsample=0.8,
                                     subsample_freq=1, colsample_bytree=0.8, random_state=0, verbose=-1)
            clf.fit(train[cols], y_tr)
            cells.append(f"{average_precision_score(y_te, clf.predict_proba(test[cols])[:, 1]):.3f}")
        print(f"| {name} | {y_te.mean():.4f} | " + " | ".join(cells) + " |", flush=True)

    print("\nArızadan kaç saat önce hata kaydı düşüyor (ilk 5):")
    print(con.execute("""
        SELECT date_diff('hour', e.ts, f.ts) AS saat_once, count(*) AS hata_sayisi
        FROM failures f JOIN errors e
          ON e.machine_id = f.machine_id AND e.ts BETWEEN f.ts - INTERVAL 48 HOUR AND f.ts
        GROUP BY 1 ORDER BY 2 DESC LIMIT 5""").df().to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
