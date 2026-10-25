"""Azure veri setiyle aynı yapıda küçük, sentetik bir veri seti üretir.

Gerçek veri Kaggle'dan indirildiği için repoya konmaz. Testler ve GitHub Actions
bu üreteçle çalışır. Gerçek veride olduğu gibi her bileşenin arızasından önce
belirli bir sensör kayar ve belirli bir hata tipi sıklaşır:

    comp1 -> volt artar,      error1
    comp2 -> rotate düşer,    error2
    comp3 -> pressure artar,  error3
    comp4 -> vibration artar, error4
"""

from pathlib import Path

import numpy as np
import pandas as pd

COMPS = ["comp1", "comp2", "comp3", "comp4"]
_DRIFT = {"comp1": ("volt", 25.0), "comp2": ("rotate", -60.0), "comp3": ("pressure", 20.0), "comp4": ("vibration", 12.0)}
_BASE = {"volt": (170.0, 15.0), "rotate": (450.0, 50.0), "pressure": (100.0, 10.0), "vibration": (40.0, 5.0)}


def write_synthetic_csvs(out_dir: Path, n_machines: int = 10, seed: int = 0,
                         start: str = "2015-01-01 06:00:00", end: str = "2016-01-01 06:00:00") -> None:
    rng = np.random.default_rng(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    hours = pd.date_range(start, end, freq="h")

    machines = pd.DataFrame({
        "machineID": np.arange(1, n_machines + 1),
        "model": rng.choice(["model1", "model2", "model3", "model4"], n_machines),
        "age": rng.integers(0, 21, n_machines),
    })

    tele, errors, maint, failures = [], [], [], []
    for m in machines.machineID:
        df = pd.DataFrame({"datetime": hours, "machineID": m})
        for col, (mu, sd) in _BASE.items():
            df[col] = rng.normal(mu, sd, len(hours))

        # Yılda 2-4 arıza; her biri öncesinde 48 saatlik kademeli sensör kayması.
        # Gerçek veride olduğu gibi arıza ve bakım kayıtları saat 06:00'da.
        for _ in range(rng.integers(2, 5)):
            idx = 24 * int(rng.integers(3, len(hours) // 24 - 1))
            comp = str(rng.choice(COMPS))
            col, shift = _DRIFT[comp]
            df.loc[idx - 48:idx - 1, col] += np.linspace(0, shift, 48)
            t = hours[idx]
            failures.append((t, m, comp))
            maint.append((t, m, comp))
            for k in range(int(rng.integers(2, 5))):
                errors.append((hours[idx - int(rng.integers(1, 40))], m, "error" + comp[-1]))

        # Planlı bakımlar: 2014 ortasından itibaren yaklaşık 3 ayda bir
        for t in pd.date_range("2014-06-01 06:00:00", end, freq="90D"):
            maint.append((t + pd.Timedelta(days=int(rng.integers(0, 20))), m, str(rng.choice(COMPS))))
        # Arızayla ilgisiz rastgele hatalar
        for t in rng.choice(hours, 15, replace=False):
            errors.append((t, m, "error5"))
        tele.append(df)

    fmt = "%Y-%m-%d %H:%M:%S"
    pd.concat(tele).assign(datetime=lambda d: d.datetime.dt.strftime(fmt)).to_csv(out_dir / "PdM_telemetry.csv", index=False)
    for name, rows, col in [("PdM_errors.csv", errors, "errorID"), ("PdM_maint.csv", maint, "comp"), ("PdM_failures.csv", failures, "failure")]:
        d = pd.DataFrame(rows, columns=["datetime", "machineID", col]).sort_values(["machineID", "datetime"])
        d["datetime"] = pd.to_datetime(d.datetime).dt.strftime(fmt)
        d.to_csv(out_dir / name, index=False)
    machines.to_csv(out_dir / "PdM_machines.csv", index=False)
