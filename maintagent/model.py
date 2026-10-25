"""Arıza riski modeli: eğitim, değerlendirme, kaydetme ve açıklama.

Model çok sınıflı: 'none' (24 saat içinde arıza yok) ya da arızalanacak bileşen
(comp1-comp4). Risk = 1 - P(none). En olası bileşen = en yüksek olasılıklı comp.
"""

import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, precision_recall_curve

from maintagent.features import COMPS, FEATURES, SENSORS

CLASSES = ["none"] + COMPS


def train(df: pd.DataFrame, seed: int = 0) -> lgb.LGBMClassifier:
    y = df["label"].map({c: i for i, c in enumerate(CLASSES)})
    model = lgb.LGBMClassifier(
        objective="multiclass", n_estimators=300, learning_rate=0.05, num_leaves=31,
        min_child_samples=20, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
        random_state=seed, verbose=-1,
    )
    model.fit(df[FEATURES], y)
    return model


def _booster(model) -> lgb.Booster:
    """Eğitimden gelen LGBMClassifier ya da dosyadan yüklenen Booster: ikisiyle de çalış."""
    return model.booster_ if hasattr(model, "booster_") else model


def predict(model, df: pd.DataFrame) -> pd.DataFrame:
    """Her satır için risk ve en olası bileşeni döndürür."""
    proba = _booster(model).predict(df[FEATURES])
    comp_idx = proba[:, 1:].argmax(axis=1)
    return pd.DataFrame({
        "machine_id": df["machine_id"].values,
        "ts": df["ts"].values,
        "risk": 1.0 - proba[:, 0],
        "likely_comp": [COMPS[i] for i in comp_idx],
    })


def top_factors(model, row: pd.DataFrame, comp: str, k: int = 3) -> list[dict]:
    """Bir satırın 'comp' tahminine en çok katkı yapan k özelliği döndürür (SHAP değerleri)."""
    contrib = _booster(model).predict(row[FEATURES], pred_contrib=True)[0]
    width = len(FEATURES) + 1  # her sınıf için özellikler + sabit terim
    cls = CLASSES.index(comp)
    values = contrib[cls * width: cls * width + len(FEATURES)]
    order = np.argsort(-values)[:k]
    return [{"feature": FEATURES[i], "value": float(row[FEATURES[i]].iloc[0]), "contribution": round(float(values[i]), 3)}
            for i in order]


def rule_baseline_score(train_df: pd.DataFrame, df: pd.DataFrame) -> np.ndarray:
    """Model olmadan basit kural: 24 saatlik ortalaması normalden en çok sapan sensörün z-skoru."""
    z = []
    for s in SENSORS:
        col = f"{s}_mean_24h"
        mu, sd = train_df[col].mean(), train_df[col].std()
        z.append(((df[col] - mu) / sd).abs().values)
    return np.max(np.vstack(z), axis=0)


def _recall_at_precision(y: np.ndarray, score: np.ndarray, min_precision: float) -> float:
    p, r, _ = precision_recall_curve(y, score)
    ok = r[p >= min_precision]
    return float(ok.max()) if len(ok) else 0.0


def evaluate(model, train_df: pd.DataFrame, test_df: pd.DataFrame) -> dict:
    pred = predict(model, test_df)
    y = (test_df["label"] != "none").astype(int).values
    baseline = rule_baseline_score(train_df, test_df)

    positives = test_df["label"] != "none"
    comp_acc = float((pred.loc[positives.values, "likely_comp"].values == test_df.loc[positives, "label"].values).mean()) \
        if positives.any() else float("nan")

    return {
        "test_samples": int(len(test_df)),
        "test_positive_rate": round(float(y.mean()), 4),
        "pr_auc_model": round(float(average_precision_score(y, pred["risk"])), 3),
        "pr_auc_rule_baseline": round(float(average_precision_score(y, baseline)), 3),
        "recall_at_80pct_precision_model": round(_recall_at_precision(y, pred["risk"].values, 0.8), 3),
        "recall_at_80pct_precision_rule": round(_recall_at_precision(y, baseline, 0.8), 3),
        "component_accuracy_on_failures": round(comp_acc, 3),
    }


def save(model: lgb.LGBMClassifier, meta: dict, out_dir: Path) -> None:
    # Dosyayı LightGBM yerine Python yazıyor: LightGBM'in C++ tarafı Windows'ta
    # yolunda Türkçe karakter (ör. "Masaüstü") olan klasörlere yazamıyor.
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "risk_model.txt").write_text(model.booster_.model_to_string(), encoding="utf-8")
    (out_dir / "metrics.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def load(model_dir: Path) -> lgb.Booster:
    return lgb.Booster(model_str=(model_dir / "risk_model.txt").read_text(encoding="utf-8"))
