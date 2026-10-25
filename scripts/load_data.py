"""Kaggle'dan indirilen CSV'leri DuckDB'ye yükler ve özet basar.

Kullanım:  python scripts/load_data.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from maintagent import config  # noqa: E402
from maintagent.db import load_all, missing_files, summarize  # noqa: E402


def main() -> int:
    missing = missing_files(config.RAW_DIR)
    if missing:
        print(f"Eksik dosyalar: {', '.join(missing)}")
        print(f"Kaggle'dan indirdiğin CSV'leri şu klasöre koy: {config.RAW_DIR}")
        return 1

    con = load_all(config.RAW_DIR, config.DB_PATH)
    print(f"Veritabanı: {config.DB_PATH}\n")
    print(f"{'tablo':<10} {'satır':>9} {'makine':>7}  {'ilk kayıt':<20} {'son kayıt':<20}")
    for r in summarize(con):
        first = str(r["first"] or "-")
        last = str(r["last"] or "-")
        print(f"{r['table']:<10} {r['rows']:>9,} {r['machines']:>7}  {first:<20} {last:<20}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
