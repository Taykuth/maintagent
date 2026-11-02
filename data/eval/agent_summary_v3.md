# Ajan değerlendirmesi (v3)

LLM: `openai/gpt-oss-120b` (akıl yürütme: `low`), kılavuz araması: `bm25`

| Ölçüt | Sonuç |
|---|---|
| Senaryo | 12 (12 arıza, 0 hatalı-arızasız, 0 sakin) |
| Bileşen doğru (ajan) | 12/12 (%100) |
| Bileşen doğru (sadece risk modeli) | 12/12 (%100) |
| Ajan, modelin bileşenini doğru aktardı | 12/12 (%100) |
| Arızada iş emri taslağı açıldı | 12/12 (%100) |
| Taslakta süre kılavuzla aynı | 12/12 (%100) |
| Taslaktaki parçalar kılavuzda var | 12/12 (%100) |
| Yanlış alarm: hatalı-arızasız | - |
| Yanlış alarm: sakin | - |
| Doğrulama ilk cevabı düzelttirdi | 0/12 (%0) |
| Dayanaksız sayı içeren cevap (son hâli) | 0/12 (%0) |
| Uydurma birim içeren cevap (son hâli) | 0/12 (%0) |
| Biçime uyan cevap (son hâli) | 12/12 (%100) |
| Adım kontrolü devreye girdi | 6/12 (%50) |
| Araç çağrısı şemaya uymadı (en az bir kez) | 0/12 (%0) |
| Adım sınırında durdu | 0/12 (%0) |
| Ortalama araç çağrısı | 3.0 |
| Token (medyan / en çok) | 9,552 / 10,533 |
| Süre, bekleme hariç (medyan sn) | 4.8 |
