"""Proje genelindeki ayarlar. Değerler .env dosyasından okunur."""

import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = Path(os.getenv("RAW_DIR", ROOT_DIR / "data" / "raw"))
DB_PATH = Path(os.getenv("DB_PATH", ROOT_DIR / "data" / "maintagent.duckdb"))

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
# gpt-oss modellerinde akıl yürütme düzeyi (low, medium, high). Düşük: daha az token, dakikalık sınıra daha geç takılır.
GROQ_REASONING_EFFORT = os.getenv("GROQ_REASONING_EFFORT", "low")

# Uygulamanın "şu an" kabul ettiği an. Veri 2015 yılına ait olduğu için
# gerçek saati kullanamayız. Tüm araçlar bu tarihten SONRAKİ veriyi görmemeli,
# yoksa model ve ajan geleceği görür (veri sızıntısı).
AS_OF = datetime.fromisoformat(os.getenv("AS_OF", "2015-10-01 00:00:00"))

# Bakım kılavuzu ve arama yöntemi (bm25, embedding, hybrid).
# Varsayılan hybrid: ölçümde en iyi sonuç (bkz. maintagent/manual.py). sentence-transformers
# kurulu değilse uygulama BM25'e düşer.
MANUAL_PATH = ROOT_DIR / "data" / "manual" / "kilavuz.md"
MANUAL_SEARCH = os.getenv("MANUAL_SEARCH", "hybrid")

# İş emri taslakları ve onaylar (SQLite; git'e girmez)
WORK_ORDERS_DB = Path(os.getenv("WORK_ORDERS_DB", ROOT_DIR / "data" / "work_orders.sqlite"))

# Herkese açık demoda canlı soru sınırı (0 = sınırsız; yerelde varsayılan). Yayında ör. 5 ve 15.
LIVE_PER_IP_PER_HOUR = int(os.getenv("LIVE_PER_IP_PER_HOUR", "0"))
LIVE_PER_DAY = int(os.getenv("LIVE_PER_DAY", "0"))

# Kayıtlı örnek çalıştırmalar (scripts/record_examples.py üretir)
EXAMPLES_PATH = ROOT_DIR / "data" / "examples" / "examples.json"

# API'yi çağırabilecek arayüz adresleri, virgülle ayrılmış
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
