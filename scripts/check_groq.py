"""Groq'ta araç çağırmanın (tool calling) çalıştığını test eder.

Modele tek bir sahte araç veriyoruz ve Türkçe bir soru soruyoruz. Üç şeyi kontrol ediyoruz:
  1. Model aracı çağırdı mı?
  2. Doğru argümanla mı çağırdı (machine_id=42)?
  3. Araç sonucunu kullanıp Türkçe, doğru bir cevap verdi mi?

Kullanım:  python scripts/check_groq.py
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import NotFoundError, OpenAI  # noqa: E402

from maintagent import config  # noqa: E402

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_machine_info",
            "description": "Bir makinenin modelini ve yaşını (yıl) döndürür.",
            "parameters": {
                "type": "object",
                "properties": {"machine_id": {"type": "integer", "description": "Makine numarası, 1-100"}},
                "required": ["machine_id"],
            },
        },
    }
]


def get_machine_info(machine_id: int) -> dict:
    # Sahte veri: gerçek araç ileride DuckDB'den okuyacak.
    return {"machine_id": machine_id, "model": "model3", "age": 18}


def main() -> int:
    if not config.GROQ_API_KEY:
        print(".env dosyasında GROQ_API_KEY yok. .env.example'ı .env olarak kopyalayıp anahtarı yaz.")
        return 1

    client = OpenAI(api_key=config.GROQ_API_KEY, base_url=config.GROQ_BASE_URL)
    messages = [
        {"role": "system", "content": "Sen bir fabrika bakım asistanısın. Türkçe ve kısa cevap ver. Bilgiyi araçlardan al, uydurma."},
        {"role": "user", "content": "Makine 42 hangi model ve kaç yaşında?"},
    ]

    t0 = time.perf_counter()
    try:
        first = client.chat.completions.create(model=config.GROQ_MODEL, messages=messages, tools=TOOLS)
    except NotFoundError:
        print(f"'{config.GROQ_MODEL}' modeline hesabının erişimi yok. Kullanabileceğin modeller:")
        for m in sorted(client.models.list(), key=lambda m: m.id):
            print(f"  {m.id}")
        print(".env dosyasındaki GROQ_MODEL satırını bunlardan biriyle değiştir.")
        return 3
    msg = first.choices[0].message
    calls = msg.tool_calls or []
    print(f"Model: {config.GROQ_MODEL}")
    print(f"1) Araç çağrıldı mı: {'EVET' if calls else 'HAYIR'}")
    if not calls:
        print(f"   Model doğrudan cevap verdi: {msg.content}")
        return 2

    args = json.loads(calls[0].function.arguments)
    print(f"2) Çağrı: {calls[0].function.name}({args})  ->  {'DOĞRU' if args.get('machine_id') == 42 else 'YANLIŞ'}")

    messages.append(msg)
    for c in calls:
        result = get_machine_info(**json.loads(c.function.arguments))
        messages.append({"role": "tool", "tool_call_id": c.id, "content": json.dumps(result, ensure_ascii=False)})

    second = client.chat.completions.create(model=config.GROQ_MODEL, messages=messages, tools=TOOLS)
    answer = second.choices[0].message.content or ""
    ok = "model3" in answer and "18" in answer
    print(f"3) Cevap: {answer.strip()}")
    print(f"   Araç sonucunu kullandı mı: {'EVET' if ok else 'KONTROL ET'}")
    print(f"Toplam süre: {time.perf_counter() - t0:.1f} sn")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
