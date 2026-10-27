# MaintAgent Bakım Kılavuzu

## Kılavuz hakkında

Bu kılavuz kurgusaldır. Microsoft Azure Predictive Maintenance veri setindeki dört bileşen (comp1-comp4) için yazılmıştır. Veri seti bileşenlerin ne olduğunu söylemez; bileşen isimleri, prosedürler, süreler ve parça kodları temsilidir. Belirtiler bölümlerindeki sayılar ise uydurma değildir: veri setindeki 761 arıza kaydından hesaplanmıştır.

## Güvenlik

### Kilitleme ve etiketleme

Her müdahaleden önce makineyi durdur, enerjiyi kes, şalteri kilitle ve üzerine adını ve tarihi yazan bir etiket as. Hidrolik devrede basınç varsa boşalt. Dönen parçaların tamamen durduğunu gözle kontrol et. Kilidi yalnızca takan kişi açar. Bu adım atlanarak yapılan hiçbir bakım işine izin verilmez.

### Arıza beklenen makinede çalışma

Arıza riski yüksek bir makineyi müdahale planlanana kadar gözetimsiz bırakma. Mümkünse yükü azalt ya da makineyi vardiya sonunda durdur. Beklenmedik ses, koku, duman ya da yağ kaçağı görülürse makineyi hemen durdur ve bakım şefine haber ver.

## Sensörler ve normal değerler

### Ölçülen büyüklükler

Her makine dört sensörün saatlik ortalamasını kaydeder: voltaj, dönüş hızı, basınç ve titreşim. Filo genelinde tipik değerler şöyledir (parantez içinde standart sapma): voltaj yaklaşık 171 (15), dönüş hızı yaklaşık 447 (53), basınç yaklaşık 101 (11), titreşim yaklaşık 40 (5). Veri setinde birim verilmez. Her makinenin kendi normali biraz farklıdır; bir değeri filo ortalamasıyla değil, makinenin önceki 30 gününün ortalamasıyla karşılaştır.

### Sensör arızası mı, bileşen arızası mı?

Bir sensördeki sapma çoğu zaman sensörün değil, o sensörün izlediği bileşenin sorunudur. Sensör arızasından ancak şu durumlarda şüphelen: değer saatlerce hiç değişmeden aynı kalıyorsa (donmuş sinyal), bir saat içinde fiziksel olarak mümkün olmayan sıçramalar varsa ya da sapmaya hiçbir hata kodu eşlik etmiyorsa. Sapma ilgili hata koduyla birlikte geliyorsa (örneğin dönüş hızı düşüşü ile birlikte E2 ve E3) önce bileşeni kontrol et. Bu durumda sensörü kalibre etmek sorunu çözmez, yalnızca müdahaleyi geciktirir.

## Hata kodları

### Hata kodu tablosu

- E1 (error1): Besleme gerilimi regülasyon uyarısı. İlgili bileşen: güç ünitesi (comp1).
- E2 (error2): Mil hızı hedefin altında. İlgili bileşen: ana mil rulmanı (comp2).
- E3 (error3): Motor aşırı yük uyarısı. İlgili bileşen: ana mil rulmanı (comp2).
- E4 (error4): Hidrolik basınç üst sınır uyarısı. İlgili bileşen: hidrolik valf bloğu (comp3).
- E5 (error5): Titreşim eşik aşımı. İlgili bileşen: motor-mil kaplini (comp4).

Geçmiş kayıtlarda her bileşenin arızasından önceki 48 saatte en sık görülen kod, yukarıda o bileşenle eşleştirilen koddur. Tek bir hata kodu tek başına arıza demek değildir; sensör sapmasıyla birlikte değerlendir.

## comp1 — Güç ünitesi

### Görevi

Güç ünitesi motor sürücüsünü ve kontrol kartlarını besler, şebeke gerilimini makinenin ihtiyaç duyduğu seviyede sabit tutar.

### Arıza belirtileri

Ana belirti voltajın yükselmesidir. Geçmiş 192 güç ünitesi arızasında, arızadan önceki 24 saatte voltaj ortalaması makinenin önceki 30 gününe göre ortalama %11 yükseldi. Dönüş hızı, basınç ve titreşimde belirgin bir değişim olmaz (%1'in altında). En sık eşlik eden hata kodu E1'dir.

### Olası nedenler

Regülatör kartındaki kondansatörlerin yaşlanması, gevşek ya da oksitlenmiş bağlantı klemensleri, soğutma fanının durması sonucu ünitenin aşırı ısınması.

### Kontrol adımları

1. Kilitleme ve etiketleme uygula.
2. Ünite kapağını aç; kondansatörlerde şişme, akıntı ya da yanık izi ara.
3. Bağlantı klemenslerinin sıkılığını ve oksitlenme olup olmadığını kontrol et.
4. Soğutma fanının serbestçe döndüğünü kontrol et.
5. Enerji verip çıkış gerilimini ölçü aletiyle ölç. Değer makinenin normalinin %5'inden fazla üstündeyse ünite değiştirilmelidir.

### Değişim prosedürü

1. Enerjiyi kes, kilitle ve etiketle.
2. Giriş ve çıkış kablolarını etiketleyerek sök.
3. Üniteyi montaj rayından çıkar.
4. Yeni üniteyi tak, kabloları etiketlere göre bağla.
5. Enerji ver, çıkış gerilimini ölç ve makineyi 30 dakika yüksüz çalıştırarak voltajı izle.

### Süre, parça ve öncelik

Tahmini süre 2 saat, 1 elektrik teknisyeni. Gerekli parça: güç ünitesi (stok kodu GU-01). Ertelenirse yüksek gerilim motor sürücüsüne ve kontrol kartlarına zarar verebilir; bu durumda onarım çok daha uzun sürer.

## comp2 — Ana mil rulmanı

### Görevi

Ana mil rulmanı mili taşır ve motorun dönüşünü işleme kafasına düşük sürtünmeyle iletir.

### Arıza belirtileri

Ana belirti dönüş hızının düşmesidir. Geçmiş 259 rulman arızasında, arızadan önceki 24 saatte dönüş hızı ortalaması makinenin önceki 30 gününe göre ortalama %17 düştü. Voltaj, basınç ve titreşim %1 içinde kalır. Eşlik eden hata kodları E2 (mil hızı düşük) ve E3 (motor aşırı yük) olup genellikle birlikte görülür. Rulmanda sürtünme arttıkça motor aynı hızı tutamaz ve zorlanır.

### Olası nedenler

Yetersiz yağlama, yağın toz ya da metal parçacıklarla kirlenmesi, normal aşınma, hatalı montaj.

### Kontrol adımları

1. Kilitleme ve etiketleme uygula.
2. Mili elle çevir; takılma, sertlik ya da hırıltı olup olmadığına bak.
3. Gres noktalarını kontrol et. Siyahlaşmış ve metal tozlu yağ aşınma işaretidir.
4. Makine durduktan hemen sonra rulman yuvasının sıcaklığını ölç. Yuva elle tutulamayacak kadar sıcaksa rulman değiştirilmelidir.
5. Dönüş hızı düşüşü E2 ve E3 ile birlikte geliyorsa sensörü kalibre etmeye çalışma, rulmanı değiştir.

### Değişim prosedürü

1. Kilitle ve etiketle.
2. Kaplini ayırarak motoru milden ayır.
3. Rulman yatağı kapağını sök ve eski rulmanı çektirme aparatıyla çıkar.
4. Yuvayı temizle. Yeni rulmanı ısıtarak ya da presle tak; asla çekiçle vurma.
5. Gresle, kapağı kapat ve mili elle çevirerek serbest döndüğünü kontrol et.
6. Makineyi 1 saat düşük hızda alıştırma çalışmasına al ve dönüş hızını izle.

### Süre, parça ve öncelik

Tahmini süre 4 saat, 2 mekanik teknisyen. Gerekli parçalar: ana mil rulman seti (stok kodu RL-02) ve rulman gresi. Ertelenirse mil ve yatak yuvası hasar görür; onarım saatlerden günlere uzar.

## comp3 — Hidrolik valf bloğu

### Görevi

Hidrolik valf bloğu devredeki basıncı ayarlar ve fazla basıncı tahliye valfi üzerinden tanka geri boşaltır.

### Arıza belirtileri

Ana belirti basıncın yükselmesidir. Geçmiş 131 valf bloğu arızasında, arızadan önceki 24 saatte basınç ortalaması makinenin önceki 30 gününe göre ortalama %23 yükseldi. Voltaj, dönüş hızı ve titreşim %1 içinde kalır. Eşlik eden hata kodu E4'tür. Tahliye valfi takıldığında fazla basınç boşaltılamaz ve devrede birikir.

### Olası nedenler

Tahliye valfinin kir ya da çapak nedeniyle takılması, tıkanmış hidrolik filtre, valf yayının yorulması.

### Kontrol adımları

1. Kilitleme ve etiketleme uygula, hidrolik basıncı tamamen boşalt.
2. Filtre göstergesine bak; kırmızı bölgedeyse filtreyi değiştir.
3. Tahliye valfini sök; sürgüde ve yayda çizik, kir ya da kırık ara.
4. Hidrolik yağdan numune al. Bulanık ya da parçacıklı yağ kirlenme olduğunu gösterir; bu durumda yağ da değiştirilmelidir.

### Değişim prosedürü

1. Kilitle, basıncı boşalt ve sızacak yağ için altına kap yerleştir.
2. Valf bloğunun hortum bağlantılarını etiketleyerek sök.
3. Yeni valf bloğunu yeni contalarla tak.
4. Hidrolik filtreyi de değiştir.
5. Sistemi doldur, havasını al ve basıncı kademeli artırarak sızıntı kontrolü yap.

### Süre, parça ve öncelik

Tahmini süre 3 saat, 1 hidrolik teknisyeni. Gerekli parçalar: valf bloğu (stok kodu HV-03), conta seti, hidrolik filtre. Ertelenirse hortum patlaması ve basınçlı yağ kaçağı riski doğar; bu iş güvenliği açısından önceliklidir.

## comp4 — Motor-mil kaplini

### Görevi

Kaplin motorun milini ana mile bağlar ve iki mil arasındaki küçük eksen kaçıklıklarını esneyerek tolere eder.

### Arıza belirtileri

Ana belirti titreşimin artmasıdır. Geçmiş 179 kaplin arızasında, arızadan önceki 24 saatte titreşim ortalaması makinenin önceki 30 gününe göre ortalama %24 arttı. Voltaj, dönüş hızı ve basınç yaklaşık %1 içinde kalır. Eşlik eden hata kodu E5'tir.

### Olası nedenler

Elastik elemanın yıpranması ya da ufalanması, motor ile mil arasındaki eksen kaçıklığı, gevşemiş kaplin cıvataları.

### Kontrol adımları

1. Kilitleme ve etiketleme uygula.
2. Kaplin muhafazasını aç; elastik elemanda çatlak, ufalanma ya da lastik tozu ara.
3. Kaplin cıvatalarının sıkılığını kontrol et.
4. Komparatör saat ya da lazer hizalama cihazıyla iki mil arasındaki eksen kaçıklığını ölç.

### Değişim prosedürü

1. Kilitle ve etiketle.
2. Kaplin cıvatalarını sök ve motoru geri çek.
3. Eski kaplini çıkar, yenisini tak.
4. Motoru hizala ve eksen kaçıklığını üretici toleransına getir.
5. Cıvataları belirtilen torkta sık, muhafazayı kapat ve titreşimi 30 dakika izle.

### Süre, parça ve öncelik

Tahmini süre 2 saat, 1 mekanik teknisyen. Gerekli parça: kaplin seti (stok kodu KP-04). Ertelenirse artan titreşim rulmanlara yayılır ve ana mil rulmanının (comp2) ömrünü kısaltır.

## Planlı bakım

### Planlı bakım aralıkları

Geçmiş kayıtlarda aynı bileşenin iki planlı değişimi arasında geçen sürenin medyanı güç ünitesi, ana mil rulmanı ve hidrolik valf bloğu için 45 gün, motor-mil kaplini için 30 gündür. Bir bileşen bu sürenin çok üstünde değişmeden kaldıysa ve arıza riski yükseliyorsa planlı bakımı öne çek.

## İş emri kuralları

### Öncelik seviyeleri

- Acil: 24 saatlik arıza riski %80 ve üstündeyse ve en az bir sensör sapması ya da hata kodu bunu destekliyorsa. Müdahale 24 saat içinde yapılır.
- Yüksek: risk %50 ile %80 arasındaysa. Müdahale 72 saat içinde planlanır.
- Normal: risk %50'nin altında ama belirgin bir sensör sapması varsa. Bir sonraki planlı bakıma eklenir.

Model riski tek başına iş emri gerekçesi değildir; destekleyen kanıt iş emrine yazılmalıdır.

### İş emri içeriği

Her iş emrinde şunlar bulunur: makine numarası, bileşen, öncelik, sayılarla gerekçe (sensör sapması, hata kodları, bakım geçmişi), bu kılavuzdaki prosedüre atıfla yapılacak adımlar, tahmini süre ve gerekli parçalar. İş emri bakım şefi onaylamadan uygulanmaz.
