# Ajan değerlendirmesi (v2)

LLM: `openai/gpt-oss-120b` (akıl yürütme: `low`), kılavuz araması: `bm25`

| Ölçüt | Sonuç |
|---|---|
| Senaryo | 24 (12 arıza, 6 hatalı-arızasız, 6 sakin) |
| Bileşen doğru (ajan) | 12/12 (%100) |
| Bileşen doğru (sadece risk modeli) | 12/12 (%100) |
| Ajan, modelin bileşenini doğru aktardı | 12/12 (%100) |
| Arızada iş emri taslağı açıldı | 12/12 (%100) |
| Taslakta süre kılavuzla aynı | 7/12 (%58) |
| Taslaktaki parçalar kılavuzda var | 7/12 (%58) |
| Yanlış alarm: hatalı-arızasız | 0/6 (%0) |
| Yanlış alarm: sakin | 0/6 (%0) |
| Doğrulama ilk cevabı düzelttirdi | 0/24 (%0) |
| Dayanaksız sayı içeren cevap (son hâli) | 0/24 (%0) |
| Uydurma birim içeren cevap (son hâli) | 0/24 (%0) |
| Biçime uyan cevap (son hâli) | 24/24 (%100) |
| Adım kontrolü devreye girdi | 7/24 (%29) |
| Araç çağrısı şemaya uymadı (en az bir kez) | 2/24 (%8) |
| Adım sınırında durdu | 0/24 (%0) |
| Ortalama araç çağrısı | 2.0 |
| Token (medyan / en çok) | 7,041 / 10,950 |
| Süre, bekleme hariç (medyan sn) | 3.4 |
