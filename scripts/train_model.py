"""Arıza riski modelini eğitir, test eder ve models/ klasörüne kaydeder.

Veri ZAMANA GÖRE bölünür: eğitim Ağustos 2015 öncesi, test Ağustos 2015 sonrası.
Aradaki 1 günlük boşluk, eğitimin son örneklerinin etiketinin (sonraki 24 saat)
test dönemine taşmasını engeller.

Kullanım:
    python scripts/train_model.py              # data/maintagent.duckdb ile
    python scripts/train_model.py --synthetic  # Kaggle verisi olmadan, sentetik veriyle dene
"""

import argparse
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb  # noqa: E402

from maintagent import config  # noqa: E402
from maintagent.db import load_all  # noqa: E402
from maintagent.features import FEATURES, build_features  # noqa: E402
from maintagent.model import evaluate, save, train  # noqa: E402
from maintagent.synthetic import write_synthetic_csvs  # noqa: E402

DATA_START = datetime(2015, 1, 2)    # ilk 24 saat pencereleri doldurmak için atlanır
TRAIN_END = datetime(2015, 8, 1)
TEST_START = datetime(2015, 8, 2)
DATA_END = datetime(2015, 12, 31)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true", help="Sentetik veriyle çalış")
    args = ap.parse_args()

    if args.synthetic:
        tmp = Path(tempfile.mkdtemp())
        write_synthetic_csvs(tmp / "raw", n_machines=20)
        con = load_all(tmp / "raw", tmp / "synthetic.duckdb")
        out_dir = config.ROOT_DIR / "models" / "synthetic"
    else:
        if not config.DB_PATH.exists():
            print("Önce veriyi yükle: python scripts/load_data.py")
            return 1
        con = duckdb.connect(str(config.DB_PATH), read_only=True)
        out_dir = config.ROOT_DIR / "models"

    print("Özellikler hesaplanıyor...")
    train_df = build_features(con, DATA_START, TRAIN_END)
    test_df = build_features(con, TEST_START, DATA_END)
    print(f"Eğitim: {len(train_df):,} örnek, test: {len(test_df):,} örnek, {len(FEATURES)} özellik")

    print("Model eğitiliyor...")
    model = train(train_df)
    metrics = evaluate(model, train_df, test_df)

    print("\nTest sonuçları (Ağustos-Aralık 2015, model bu dönemi hiç görmedi):")
    for k, v in metrics.items():
        print(f"  {k:<36} {v}")

    meta = {"features": FEATURES, "train": [DATA_START, TRAIN_END], "test": [TEST_START, DATA_END],
            "synthetic": args.synthetic, "metrics": metrics}
    save(model, meta, out_dir)
    print(f"\nModel ve metrikler kaydedildi: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
