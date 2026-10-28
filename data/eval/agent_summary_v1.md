# Ajan değerlendirmesi

LLM: `openai/gpt-oss-120b`, kılavuz araması: `bm25`

| Ölçüt | Sonuç |
|---|---|
| Senaryo | 24 (12 arıza, 6 hatalı-arızasız, 6 sakin) |
| Bileşen doğru (ajan) | 12/12 (%100) |
| Bileşen doğru (sadece risk modeli) | 12/12 (%100) |
| Ajan, modelin bileşenini doğru aktardı | 12/12 (%100) |
| Arızada iş emri taslağı açıldı | 12/12 (%100) |
| Yanlış alarm: hatalı-arızasız | 0/6 (%0) |
| Yanlış alarm: sakin | 0/6 (%0) |
| Dayanaksız sayı içeren cevap | 15/24 (%62) |
| Uydurma birim içeren cevap | 9/24 (%38) |
| Biçime uyan cevap | 23/24 (%96) |
| Adım kontrolü devreye girdi | 24/24 (%100) |
| Adım sınırında durdu | 0/24 (%0) |
| Ortalama araç çağrısı | 2.5 |
| Token (medyan / en çok) | 9,192 / 10,622 |
| Süre, bekleme hariç (medyan sn) | 5.2 |
