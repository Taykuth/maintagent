"""Cevaptaki sayıların ve birimlerin araç çıktılarına dayanıp dayanmadığını kontrol eder.

Hem değerlendirmede (uydurma oranını ölçmek için) hem de ajan döngüsünde (cevabı
kullanıcıya göstermeden önce düzelttirmek için) aynı kurallar kullanılır.

İlk değerlendirmede cevapların %62'sinde araç çıktısında olmayan sayı vardı. Çoğu,
kılavuzda olmayan adım başına süreler ("≈15 dk") ve veride olmayan birimlerdi ("bar").
"""

import re

# Cevapta geçmesi doğal olan ama araç çıktısında sayı olarak bulunmayan değerler:
# pencere uzunlukları (24 saat, 7 gün, 30 gün), eşikler (%50, %80) ve kılavuz aralıkları.
CONTEXT_NUMBERS = {3.0, 5.0, 7.0, 24.0, 30.0, 48.0, 50.0, 72.0, 80.0}

# Veride birim yok; bunlardan biri cevapta geçiyorsa model uydurmuş demektir.
UNIT_PATTERN = re.compile(r"\b(rpm|psi|bar|kpa|hz|volt|mm/s)\b|(?<=\d)\s?(V)\b", re.IGNORECASE)

# Harf, alt çizgi, nokta ya da tireye yapışık rakamları almaz: comp2, E3, RL-02, model3 sayı değildir.
NUMBER_PATTERN = re.compile(r"(?<![\w.\-])\d+(?:[.,]\d+)?")

REQUIRED_SECTIONS = ("Durum", "Kanıt", "Öneri")


def numbers_in_text(text: str) -> list[float]:
    """Metindeki sayılar. Türkçe ondalık virgülü de okunur: '15,2' -> 15.2."""
    return [float(n.replace(",", ".")) for n in NUMBER_PATTERN.findall(text)]


def tool_numbers(obj) -> set[float]:
    """Araç çıktılarında geçen bütün sayılar (metin alanlarının içindekiler dahil).

    İşaretsiz hâlleri de eklenir: araç -0,6 dediğinde cevap "%0,6 altında" yazar.
    """
    found: set[float] = set()
    if isinstance(obj, bool):
        return found
    if isinstance(obj, (int, float)):
        found |= {float(obj), abs(float(obj))}
    elif isinstance(obj, str):
        found.update(numbers_in_text(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            found |= tool_numbers(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            found |= tool_numbers(v)
    return found


def is_grounded(x: float, pool: set[float]) -> bool:
    """x, havuzdaki bir sayının kendisi ya da yuvarlanmış hâli mi?

    377,68 -> 377,7 (bir ondalık) ve 445,6 -> 446 (tam sayı) kabul. 15,2 -> 16 kabul değil.
    """
    for y in pool:
        if abs(x - y) <= 0.051 + 1e-9:
            return True
        if x == int(x) and abs(x - y) <= 0.5 + 1e-9:
            return True
    return False


def ungrounded_numbers(answer: str, results: list[dict], extra: set[float]) -> list[float]:
    """Cevapta olup araç çıktılarında, soruda ya da bağlamda olmayan sayılar."""
    pool = set(extra) | CONTEXT_NUMBERS
    for r in results:
        pool |= tool_numbers(r)
    return [x for x in numbers_in_text(answer) if not is_grounded(x, pool)]


def invented_units(answer: str) -> list[str]:
    return sorted({(a or b).lower() for a, b in UNIT_PATTERN.findall(answer)})


def missing_sections(answer: str) -> list[str]:
    return [s for s in REQUIRED_SECTIONS if s not in answer]
