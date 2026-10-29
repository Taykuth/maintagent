#!/usr/bin/env bash
# Yayındaki sunucunun açılışı: veri yoksa Kaggle'dan indir, veritabanını kur, API'yi başlat.
# Veri seti imaja ya da Space'e konmaz (lisansı belirsiz); her açılışta kaynağından indirilir.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f data/maintagent.duckdb ]; then
  # Kaggle'ın yeni anahtarı (KAGGLE_API_TOKEN) ya da eski usul kullanıcı adı + anahtar
  if [ -z "${KAGGLE_API_TOKEN:-}" ] && { [ -z "${KAGGLE_USERNAME:-}" ] || [ -z "${KAGGLE_KEY:-}" ]; }; then
    echo "Kaggle anahtarı yok: KAGGLE_API_TOKEN (ya da KAGGLE_USERNAME + KAGGLE_KEY) gizli değişkenini tanımla." >&2
    exit 1
  fi
  echo "Veri Kaggle'dan indiriliyor..."
  kaggle datasets download -d arnabbiswas1/microsoft-azure-predictive-maintenance -p data/raw --unzip
  python scripts/load_data.py
fi

exec uvicorn maintagent.api:create_app --factory --host 0.0.0.0 --port "${PORT:-7860}"
