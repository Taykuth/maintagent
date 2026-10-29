"""Herkese açık demo için verileri JSON olarak arayüze yazar (frontend/public/demo).

Önce kayıtlı örnekleri al (python scripts/record_examples.py); statik demoda ajan tarafını
onlar gösterir. LLM çağırmaz, token harcamaz.

Kullanım:
    python scripts/export_static.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from maintagent import config  # noqa: E402
from maintagent.api import AppState  # noqa: E402
from maintagent.static_export import export_static  # noqa: E402

OUT_DIR = config.ROOT_DIR / "frontend" / "public" / "demo"


def main() -> int:
    state = AppState.from_config()
    summary = export_static(state, OUT_DIR)
    print(f"{summary['machines']} makine, {summary['examples']} kayıtlı örnek, "
          f"toplam {summary['bytes'] / 1e6:.1f} MB -> {OUT_DIR}")
    if summary["examples"] == 0:
        print("Uyarı: kayıtlı örnek yok. Demoda ajan tarafı boş kalır; önce python scripts/record_examples.py")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
