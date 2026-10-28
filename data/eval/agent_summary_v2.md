# Ajan değerlendirmesi (v2)

LLM: `openai/gpt-oss-120b` (akıl yürütme: `low`), kılavuz araması: `bm25`

| Ölçüt | Sonuç |
|---|---|
| Senaryo | 4 (4 arıza, 0 hatalı-arızasız, 0 sakin) |
| Bileşen doğru (ajan) | 4/4 (%100) |
| Bileşen doğru (sadece risk modeli) | 4/4 (%100) |
| Ajan, modelin bileşenini doğru aktardı | 4/4 (%100) |
| Arızada iş emri taslağı açıldı | 4/4 (%100) |
| Yanlış alarm: hatalı-arızasız | - |
| Yanlış alarm: sakin | - |
| Doğrulama ilk cevabı düzelttirdi | 0/4 (%0) |
| Dayanaksız sayı içeren cevap (son hâli) | 0/4 (%0) |
| Uydurma birim içeren cevap (son hâli) | 0/4 (%0) |
| Biçime uyan cevap (son hâli) | 4/4 (%100) |
| Adım kontrolü devreye girdi | 2/4 (%50) |
| Araç çağrısı şemaya uymadı (en az bir kez) | 0/4 (%0) |
| Adım sınırında durdu | 0/4 (%0) |
| Ortalama araç çağrısı | 3.0 |
| Token (medyan / en çok) | 10,129 / 10,166 |
| Süre, bekleme hariç (medyan sn) | 5.9 |
