/* Lyra Radar — Metodoloji: her sekmenin veri kaynakları, hesap yöntemi ve sınırları tek yerde.
   Sekmeler kendi içinde yalnız kısa bir "Kaynaklar ve yöntem" bağlantısı gösterir (#metodoloji/<sekme>).
   Temel Analiz bölümü fundamentals.js'teki metni kullanır (window.radarFundamentals.methodHTML). */
(() => {
  "use strict";
  const sh = window.shell;
  const { $, $$, esc } = sh;
  const ul = items => `<ul>${items.map(([b, t]) => `<li>${b ? `<b>${b}.</b> ` : ""}${t}</li>`).join("")}</ul>`;
  const card = (title, body) => `<section class="card fa-method"><h2 class="card-title">${title}</h2>${body}</section>`;

  const SECTIONS = [
    ["sinyal", "Sinyal Takip", () => card("Kaynaklar", ul([
        ["Resmi", "KAP ve Borsa İstanbul bildirimleri, SPK bülteni ve duyuruları, TCMB, TÜİK, BDDK, Hazine, Resmi Gazete; ABD için SEC EDGAR (8-K, 10-Q, 10-K, Form 4, 13D/G)."],
        ["Haber", "Google News, Yahoo Finance, Finnhub, Marketaux ve Türkçe haber RSS akışları; dünya basını için GDELT tema taraması."],
        ["Sosyal", "Reddit ve StockTwits (gürültüsü yüksek; ayrı tür olarak işaretlenir)."],
        ["Aracı kurum", "Kurum notlarının kamuya duyurulan başlıkları ve senin ilettiğin rapor e-postaları (raporun kendisi yayımlanmaz)."],
        ["Kapsam", "Yön ve özet yalnız izleme listesi hisseleri için üretilir; diğer KAP bildirimleri olay veritabanına girer."],
      ])) + card("AI sınıflandırma", ul([
        ["Model", "Gemini (ücretsiz kota); her kayıt için yön (olumlu/olumsuz/nötr), güven (0–100), önem (düşük/orta/yüksek), olay türü ve Türkçe özet."],
        ["Güçlü sinyal", "güven ≥ %70 ve önem düşük değil."],
        ["Sınır", "Model yalnız başlık ve özeti görür; ek dokümanı yalnız resmi bildirimlerde okur. Yanılabilir: karar vermeden önce kaynağa bak."],
      ])) + card("Karne", ul([
        ["Sinyal anından", "Yönlü sinyaller yayın anındaki fiyatla arşivlenir; aynı hisse, olay ve yön 12 saat içinde bir kez sayılır. Getiri, yayından sonraki 1., 5. ve 20. tam seans kapanışına kadar; fazla getiri aynı aralıkta endeks (BIST 100 / S&P 500) getirisi düşülerek hesaplanır. Son 180 gün tutulur."],
        ["Önceki kapanıştan", "Aynı sinyaller olay veritabanından ölçülür: getiri haber ya da bildirimden önceki son kapanıştan başlar, böylece sinyal yayımlanmadan önce fiyata yansıyan tepki de sayılır. Kıyas BIST'te eşit ağırlıklı BIST Tüm, ABD'de S&P 500. İki ölçüm arasındaki fark büyükse fiyat sinyal panele düşmeden önce hareket etmiştir."],
        ["İsabet", "sinyal yönü ile fazla getirinin işaretinin aynı olma oranı; %50 yazı-turadır. Geçmiş isabet gelecek getirinin garantisi değildir."],
      ]))],
    ["olay-karnesi", "Olay Karnesi", () => card("Yöntem ve sınırlar", `<ul>
      <li><b>Olaylar.</b> KAP bildirimlerinin tamamı (idari ve rutin bildirimler hariç), panelin haber ve sinyal akışı, aracı kurum notlarının kamuya açık özetleri, gerçekleşen geri alımlar ve kâr payı kararları tek tabloda. Aynı gün aynı hisse için başlığı neredeyse aynı olaylar (aynı haberin birkaç kaynağı, konsolide + solo rapor) tek olay sayılır.</li>
      <li><b>Getiri.</b> Olaydan önceki son kapanıştan 1, 5 ve 20 seans sonraki kapanışa; seans dışı olaylar sonraki seanstan başlar. BIST'te kıyas eşit ağırlıklı BIST Tüm: dönemde küçük ve orta hisseler XU100'den belirgin zayıf kaldığı için XU100'e göre fark her olayı olumsuz gösterirdi. Yahoo'da düzeltilmemiş bölünme/bedelsiz izi taşıyan pencereler dışarıda.</li>
      <li><b>Bilanço sürprizi.</b> Analist konsensüsü ücretsiz ve lisanslı olmadığından beklenti = geçen yılın aynı çeyreğinin reel (TÜFE ile düzeltilmiş) net kârı. Sürpriz, farkın son dört çeyreğin ortalama kâr büyüklüğüne oranı; +0,2 üstü olumlu, −0,2 altı olumsuz. Aynı gün yayımlanan faaliyet raporu ve konsolide/solo rapor aynı yönü alır.</li>
      <li><b>Belirsizlik.</b> %95 aralık olay gününe göre kümelenmiş standart hatayla. Geri alım gibi ardışık günlerde tekrarlanan bildirimlerde pencereler çakışır; aralık yine de biraz dar kalabilir.</li>
      <li><b>Okuma.</b> Bu geçmişin ortalaması, bir alım-satım kuralı değil. İşlem maliyeti, likidite ve açılış boşluğu yok sayılır. ABD tarafında yalnız izlenen hisseler var (seçim yanlılığı: izlenen hisseler son dönemin güçlü hisseleri olabilir). "Öncesi (5)" sütunu büyükse olay, fiyat hareketinin sonucu olabilir (ör. devre kesici).</li>
      <li><b>Kaynak.</b> Fiyat: Yahoo Finance (kişisel kullanım). Veri saatlik güncellenir; KAP geçmişi 90 gün geriye dolduruldu ve birikerek uzar.</li></ul>`)],
    ["piyasa-gucu", "Piyasa Gücü", () => card("Genişlik ve rejim", ul([
        ["Evren", "BIST Tüm (KAP endeks listesi) ve endeks dışı bankalar; Yahoo günlük kapanış ve hacmi, 2010'dan bugüne. Yahoo bazı bedelsiz ve bölünmeleri düzeltmediği için ±%25'i aşan tek gün hareketi sıfır getiri sayılarak temiz seri kurulur (BIST fiyat sınırı ±%10). Tatil artığı satırlar atılır."],
        ["Ortalama üstü oran", "Kapanışı 20, 50 ve 200 günlük basit ortalamasının üstünde olan hisselerin, o ortalaması hesaplanabilen hisselere oranı."],
        ["Yeni zirve / dip", "Kapanışı önceki 252 seansın en yükseğini aşan / en düşüğünün altına inen hisse sayısı; en az 230 seans geçmişi olanlar."],
        ["Yükselen–düşen", "Günlük yükselen ve düşen hisse sayısı, farkının birikimli toplamı (çizgi). McClellan osilatörü oran ayarlıdır: (yükselen − düşen) / (yükselen + düşen) × 1000'in 19 ve 39 günlük EMA farkı; evren büyüklüğünden bağımsız."],
        ["Hacim", "Yükselen hisselerin TL hacminin (kapanış × adet) yükselen + düşen hisselerin toplamına oranı. ≥ %90 ve hisselerin de ≥ %85'i yükseliyorsa alım, tersi satış günü (Lowry %90 günleri)."],
        ["Genişlik sıçraması", "Yükselen hisse oranının 10 günlük EMA'sı 10 seans içinde %40'ın altından %61,5'in üstüne çıkar (Zweig)."],
        ["Diverjans", "XU100 63 günlük kapanış dibindeyken yeni 52 hafta dibindeki hisse sayısı son 63 günün en yüksek değerinin yarısından azsa pozitif; XU100 63 günlük zirvedeyken yeni zirve sayısı aynı ölçüde azsa negatif (pencerenin zirvesi en az 20 hisse)."],
        ["Rejim", "Kurallı ve açık: <b>Toparlanma</b> son 30 günde genişlik sıçraması ya da 200 günlüğün altında %90 satış ve %90 alım günlerinin birlikte görülmesi; <b>Boğa</b> XU100 200 günlüğün üstünde, 50 günlük > 200 günlük, hisselerin en az yarısı 200 günlüğün üstünde ve net yeni zirve − dip (50 gün ort.) artı; <b>Ayı</b> XU100 200 günlüğün altında, hisselerin %40'ından azı 200 günlüğün üstünde ve net yeni zirve − dip eksi; bunlara ek olarak aşırı satım (20 ya da 50 günlükte %15 altı), %90 satış günü ya da pozitif diverjans varsa <b>Dip arayışı</b>; diğer durumlar <b>Düzeltme / kararsız</b>."],
      ])) + card("Korku–açgözlülük endeksi", ul([
        ["Fikir", "CNN Fear & Greed mantığı, yalnız BIST'te gözlenen veriyle: 0 aşırı korku, 100 aşırı açgözlülük. Bölgeler: 0–25 aşırı korku, 25–45 korku, 45–55 nötr, 55–75 açgözlülük, 75–100 aşırı açgözlülük."],
        ["Bileşenler", "<b>Momentum</b>: XU100'ün 125 günlük ortalamasından uzaklığı. <b>Fiyat gücü</b>: 52 haftalık (yeni zirve − yeni dip) / izlenen hisse, 10 gün ortalaması. <b>Hacim genişliği</b>: yükselen hisselerin TL hacim payı, 10 gün. <b>Oynaklık</b>: XU100 20 günlük gerçekleşen oynaklığının 1 yıllık ortalamaya oranı (ters). <b>Güvenli liman</b>: XU100 ile TL gram altının 20 günlük getiri farkı. <b>Banka risk iştahı</b>: XBANK'ın XU100'e göre 20 günlük göreli getirisi. <b>Kur baskısı</b>: USD/TRY 20 günlük değişimi (ters). <b>Kaldıraç</b>: aracı kurumların kredili işlem (hisse teminatlı kredi) bakiyesinin son 3 aydaki büyümesi eksi XU100'ün aynı dönemdeki getirisi; seviye değil değişim, çünkü bakiye yatırımcı tabanıyla yıllar içinde yapısal olarak büyüyor."],
        ["Kredili işlem verisi", "Türkiye Sermaye Piyasaları Birliği (TSPB) veriler sayfası: 2002–2024 çeyreklik, 2025'ten aylık. Ay sonu verisi ayın ilk haftasında yayımlanır; geriye dönük hesapta her değer yayım tarihinden (aylıkta ay sonu + 7 gün, çeyreklikte + 45 gün) itibaren kullanılır, böylece geçmişe bakarken bilinmeyen veri kullanılmaz. Kaynak gösterilerek kullanılır."],
        ["Puanlama", "Her gösterge, son 756 işlem gününün (≈3 yıl) dağılımı içindeki yüzdelik sırasıyla 0–100'e çevrilir; endeks eşit ağırlıklı ortalamadır (en az bileşenlerin %60'ı gerekir). Yüzdelik sıra, yüksek enflasyonun nominal TL serilerine kattığı yukarı eğilimi büyük ölçüde nötrler; seviyeler değil, son 3 yıla göre konum ölçülür."],
        ["Geriye dönük", "Aynı kurallarla 2011'den bugüne hesaplanır. Bölge başına sonraki 1 ve 3 aylık XU100 getirisi USD bazında (TL'nin değer kaybı ayıklanır) medyan olarak verilir. Pencereler örtüştüğü için gözlemler bağımsız değildir; tablo yönü gösterir, anlamlılık iddiası taşımaz."],
        ["Sınırlar", "BIST için ücretsiz bir oynaklık endeksi (VIX benzeri) ve opsiyon put/call oranı olmadığından bu bileşenler yok; oynaklık gerçekleşen oynaklıkla ölçülür. Kredili işlem verisi aylık olduğu için bu bileşen ay içinde değişmez. Endeks bir alım-satım sinyali değildir."],
      ])) + card("Sektör rotasyonu", ul([
        ["Sektör endeksi", "KAP alt sektörü (en az 3 işlem gören hisse); eşit ağırlıklı, temiz günlük getirilerden zincirlenir. Nakit temettü dahil değil."],
        ["Rotasyon grafiği", "Haftalık (cuma kapanışı). Göreli güç = sektör endeksi / XU100; oran = 100 × göreli güç / 10 haftalık EMA'sı; ivme = 100 + (oran − 4 hafta önceki oran). Bölgeler: Lider (oran ≥ 100, ivme ≥ 100), Zayıflayan, Geride, İyileşen. RRG (Relative Rotation Graph) yaklaşımına benzer, kendi formülümüzdür."],
        ["Sektör skoru", "0–100: 3 aylık medyan hisse getirisi %25, oran %25, ivme %20, 50 günlük ortalama üstü hisse oranı %15, sektörün BIST TL hacmindeki payının son 20 / son 60 gün oranı %15; her birinin sektörler arası yüzdelik sırasının ağırlıklı ortalaması."],
      ])) + card("Güçlü hisseler", ul([
        ["Göreli güç", "1–99: 0,4 × 3 aylık + 0,2 × 6, 9 ve 12 aylık getiri (kısa geçmişte eksik dönem bir öncekiyle doldurulur); BIST Tüm içinde yüzdelik sıra (IBD yöntemi)."],
        ["Trend şablonu", "Minervini'nin 7 fiyat maddesi: fiyat 150 ve 200 günlüğün üstünde; 150 > 200; 200 günlük 1 aydır yükseliyor; 50 > 150 ve 200; fiyat 50 günlüğün üstünde; 52 hafta dibinin en az %30 üstünde; zirvesine %25'ten yakın. En az 260 seans geçmiş."],
        ["Hacim teyidi", "Son 50 seansta yükselen günlerin TL hacmi / düşen günlerin TL hacmi; 1 üstü birikim."],
        ["Sınırlar", "Borsadan çıkmış hisseler Yahoo'da yok: eski yıllarda evren daha küçük ve hayatta kalanlardan oluşur, bu yüzden sayılar yerine oranlar esas alınır. Rejim, sinyaller ve liste geriye dönük olarak henüz test edilmedi; isabetleri ayrıca ölçülecek. Hafta içi kapanıştan sonra güncellenir."],
      ]))],
    ["yontem-karnesi", "Yöntem Karnesi", () => card("Test kurgusu", ul([
        ["Soru", "Bir tarama ölçütü (ör. düşük F/K, yüksek F-skoru) geçmişte BIST'te sonraki ayın getirisini öngörüyor muydu?"],
        ["Nokta-zamanlı", "Her ay sonunda yalnız o güne kadar KAP'ta yayımlanmış son mali tablo kullanılır. Yayın anı bilinmeyen eski raporlarda SPK'nın yasal son günü alınır (1. ve 3. çeyrek +41, 2. çeyrek +61, yıl sonu +71 gün). Dönem sonundan 9 aydan eski tablo kullanılmaz."],
        ["Fiyat ve pay", "Ay sonu gerçek kapanış × dönemin ödenmiş sermayesi; dönem sonu ile ay sonu arasındaki bölünme ve bedelsizler pay sayısına işlenir (bedelsiz sonrası hisse yanlışlıkla ucuz görünmez). Mali tablo tutarları TÜFE ile ay sonunun TL'sine taşınır."],
        ["Getiri", "Ertesi ayın temettü ve bölünme düzeltilmiş getirisi. Kıyas aynı ay uygun hisselerin eşit ağırlıklı ortalaması; yani her sonuç piyasaya göre fazla getiridir. Aylık %300 üstü ya da −%90 altı hareketler veri hatası sayılıp dışarıda."],
        ["Evren", "BIST Tüm ve endeks dışı bankalar. Son 3 ayın medyan işlem hacmine göre o ayın alt %20'si ve aylarca aynı fiyatta kalan hisseler dışarıda. Temel yöntemlerde mali kuruluşlar (banka, sigorta ve finansal şablonla raporlayan şirketler) hariç; fiyat yöntemleri tüm hisselerde."],
      ])) + card("Ölçütler", ul([
        ["Dilimler", "Her ay hisseler sinyale göre beş eşit dilime ayrılır (eşit ağırlık). En iyi − en kötü dilim farkının aylık ortalaması ve Newey-West (3 gecikme) t istatistiği."],
        ["Rank IC", "Sinyal sırası ile ertesi ay getiri sırası arasındaki Spearman korelasyonunun aylık ortalaması."],
        ["En iyi dilim", "Yalnız en iyi dilimi alan uzun portföyün piyasaya göre fazla getirisi; ayda değişen hisse payı kadar %0,2/işlem maliyeti düşülür. Reel TL (TÜFE) ve ABD doları cinsinden yıllık getiri de verilir."],
        ["Alt dönemler", "2017–2019, 2020–2022 ve 2023 sonrası (enflasyon muhasebesi) ayrı ayrı."],
        ["Karar", "Çok sayıda yöntem test edildiği için güçlü kanıt eşiği t ≥ 3 (Harvey, Liu ve Zhu 2016) ve alt dönemlerin çoğunda aynı yön; en az iki alt dönem ve 60 ay yoksa \"güçlü · kısa dönem\" (farklı piyasa koşullarında sınanmadı); 2 ≤ t < 3 zayıf işaret; |t| < 2 kanıt yok; eksi yönde aynı eşikler \"ters çalışıyor\". 24 aydan az test edilebilir dönem: veri yetersiz."],
      ])) + card("Sınırlar", ul([
        ["Hayatta kalma", "Borsadan çıkmış şirketlerin fiyatları Yahoo'da yok; evren bugünkü şirketlerden oluşur. Bu, özellikle ucuz ve sıkıntılı hisselerin sonuçlarını iyimser gösterir."],
        ["Örneklem", "KAP tabloları 2016 yıl sonundan önce okunamıyor; en fazla ~115 ay. Geçmiş tablolar KAP indirme sınırı nedeniyle kademeli iniyor, temel yöntemlerin test dönemi doldukça uzar."],
        ["Enflasyon muhasebesi", "2023 sonu öncesi raporlar nominal, sonrası TMS 29'lu; kârlılık ve büyüme ölçütleri iki dönemde farklı davranabilir (alt dönem tablosuna bak)."],
        ["Uygulama", "Aylık yeniden dengeleme, açılış boşluğu ve piyasa etkisi yok sayılır; sığ hisselerde gerçek maliyet daha yüksektir."],
        ["Kaynak", "KAP mali tabloları, TCMB EVDS TÜFE, Yahoo Finance fiyat ve USD/TRY (kişisel kullanım; ham fiyat yayımlanmaz). Haftada bir (pazar) yeniden hesaplanır."],
      ]))],
    ["takvim", "Takvim", () => card("Kaynaklar", ul([
        ["Saat", "tüm saatler İstanbul saatiyle."],
        ["Süzgeçler", "üst çubuktaki piyasa seçimi (BIST/ABD) yalnız şirket olaylarına uygulanır: bilanço, temettü, genel kurul, vade sonu. Makro veriler ve merkez bankası kararları bu seçimden bağımsızdır; onları takvimin Bölge süzgeci daraltır (Türkiye, ABD, Avrupa, İngiltere, Japonya)."],
        ["Türkiye verileri", "TÜİK Ulusal Veri Yayımlama Takvimi'nden (TÜİK, TCMB, BDDK, Hazine ve Maliye Bakanlığı, SPK ve diğer kurumlar; otomatik, yaklaşık 2 ay ileri). Son açıklanan değerler TCMB EVDS'ten."],
        ["Merkez bankaları", "TCMB PPK, Fed ve ABD TÜFE resmi takvimlerden; ECB toplantıları ecb.europa.eu'dan, BoE toplantıları bankofengland.co.uk'ten, BoJ toplantıları boj.or.jp'den. Euro Bölgesi verileri Eurostat'tan."],
        ["Bilançolar", "ABD (S&P 500) Alpha Vantage kazanç takviminden; Avrupa ve izleme listesi bilançoları Yahoo Finance'ten (şirketler tarihi değiştirebilir)."],
        ["Şirket olayları", "temettüler KAP'tan, genel kurullar Borsa İstanbul listesinden."],
        ["Vadeler", "VİOP vade sonu çift ayların son iş günü, ABD opsiyon vadesi ayın 3. cuması olarak hesaplanır."],
      ]))],
    ["arastirma", "Araştırma", () => card("Kaynaklar ve hesaplar", ul([
        ["Notlar", "Aracı kurum notlarının haber başlıklarından çıkarılan kurum, tavsiye ve hedef fiyatı; rapor e-postalarındaki notlar. Raporların kendisi yayımlanmaz, yalnız kamuya duyurulan özetleri kullanılır."],
        ["Potansiyel", "hedef fiyat / güncel fiyat − 1. <b>Reel potansiyel</b> 12 ay sonrası TÜFE beklentisine (TCMB Piyasa Katılımcıları Anketi) göre; anket yoksa fonlama faizine göre faiz üstü getiri."],
        ["Revizyon", "aynı kurumun aynı hisse için bir önceki hedefine göre değişim."],
        ["AI sentezi", "kurum görünümlerini ve notları özetler; yatırım tavsiyesi değildir."],
      ]))],
    ["geri-alim", "Şirket Geri Alım", () => card("Kaynaklar", ul([
        ["Veri", "KAP'taki pay geri alım bildirimleri; ayrı repodaki <a href=\"https://github.com/gptrade/kap-geri-alim-takibi\" target=\"_blank\" rel=\"noopener\">kap-geri-alim-takibi</a> uygulaması toplar (işlem tarihi, fiyat, adet, sermayeye oranı)."],
        ["Fiyat", "güncel kapanışlar saatte bir Yahoo Finance'ten toplu alınır; izleme listesindeki hisselerde panel fiyatı kullanılır."],
        ["Olay etkisi", "gerçekleşen geri alımların sonraki seanslardaki ortalama getirisi için Olay Karnesi'ne bak."],
      ])) + card("Program kullanımı", ul([
        ["Kullanım", "aktif programın başından beri alınan pay ÷ son program bildirimindeki azami pay. Çizgi: programın süresinin geçen kısmı; kullanım süreden hızlıysa çubuk turuncu."],
        ["Kaynak", "azami pay ve süre son program bildiriminden okunur; süre metni okunamayan programlarda zaman çizgisi yoktur."],
        ["%110 üstü", "azami payı aşıyor görünen programlarda büyük ihtimalle yeni program bildirimi eksik ya da azami pay okunamamıştır; uyarıyla listenin sonuna alınır."],
      ])) + card("Geri alım sonrası performans", ul([
        ["Dalga", "aynı hissede 30 günden uzun ara vermeden gelen geri alım bildirimleri tek dalga sayılır; olay dalganın ilk bildirimidir. Böylece her gün alım yapan şirketler sonucu domine etmez."],
        ["Giriş", "yayın anına göre, ileriye bakmadan: bildirim 09:55'ten önce yayımlandıysa o günün kapanışı, sonra yayımlandıysa bir sonraki işlem gününün kapanışı."],
        ["Getiri", "hissenin getirisi − BIST 100 getirisi (aynı pencere, temettü ve bölünmeye göre düzeltilmiş fiyat). Ufuklar 5, 20 ve 60 işlem günü (yaklaşık 1 hafta, 1 ay, 3 ay). \"Alımdan önceki 20 gün\" girişten önceki 20 işlem günüdür."],
        ["Anlamlılık", "dalgalar takvimde kümelendiği (aynı haftalarda çok şirket alıyor) için standart hata giriş ayına göre kümelenir; |t| ≥ 2 \"anlamlı\" sayılır. Kutunun üzerine gelince ortalama, medyan, pozitif oran ve t görünür."],
        ["Grafik", "her gün için o güne verisi olan dalgaların ortalaması; gölge basit %95 aralıktır (kümelenme hesaba katılmaz, gerçek belirsizlik daha geniştir)."],
        ["Sınırlar", "örnek takipçinin başladığı Ağustos 2025'ten beri, kısa. İşlem maliyeti ve likidite yok sayılır. Geri alım şirketin kendi fiyatını desteklemesidir; sonuç geçmişin ortalamasıdır, tek hisse için öngörü değildir. Fiyat: Yahoo (yalnız yüzde getiriler yayımlanır)."],
      ]))],
    ["temel", "Temel Analiz", () => window.radarFundamentals?.methodHTML?.() || ""],
    ["banka-faiz", "Banka Faiz Duyarlılığı", () => card("Yöntem ve sınırlar", `<ul>
        <li><b>Veri.</b> KAP'taki banka mali tabloları (solo/konsolide, bankanın yayımladığı): faiz gelirleri ve giderleri çeyreklere ayrılır, ortalama toplam aktife bölünüp yıllıklandırılır. Politika faizi: TCMB ağırlıklı ortalama fonlama maliyeti (EVDS, günlük → çeyrek ortalaması). Beklenti: TCMB Piyasa Katılımcıları Anketi, 12 ay sonrası politika faizi.</li>
        <li><b>Model.</b> Aktif getirisi ve fonlama maliyeti ayrı ayrı faizin bu ve önceki çeyrek ortalamasına regrese edilir. Banka katsayıları bankalar arası havuz tahminine doğru gözlem gürültüsüyle orantılı büzülür (az çeyreği olan banka sektöre daha çok benzer). 1 yıllık etki = bu çeyrek katsayısı + önceki çeyreğin ¾'ü (12 ayda geçişin dört çeyreğe yayıldığı varsayımı).</li>
        <li><b>Örneklem.</b> Ana model 2024 T1'den başlar: 2023'teki KKM, menkul kıymet tesis ve kredi büyüme sınırları faiz geçişkenliğini bozdu. "2023 dahil" düğmesi sağlamlık için aynı hesabı uzun örneklemle verir; ikisi çok ayrışıyorsa sonuç düzenleme rejimine duyarlıdır.</li>
        <li><b>Sınırlar.</b> TL/döviz karışımı ayrıştırılmaz (döviz fonlama faiz giderini TL faizinden bağımsız etkiler). Swap fonlaması faiz giderinde değil ticari kâr/zararda görünür: swap kullanımı yüksek bankada gerçek fonlama maliyeti ve duyarlılık eksik ölçülür. TÜFE'ye endeksli menkul kıymet geliri enflasyona bağlıdır, faize değil; enflasyon düşüşü bu geliri ayrıca azaltır. Bilanço büyümesi, kredi/mevduat karması değişimi, karşılık giderleri ve vergi oranı sabit kabul edilir. Katılım bankasında (Albaraka) faiz yerine kâr payı kalemleri kullanılır: kredilerden alınan kâr payı aktif getirisi, katılma hesaplarına verilen kâr payı fonlama maliyeti sayılır.</li>
        <li><b>Okuma.</b> Bu bir duyarlılık tahminidir, hedef fiyat değildir. "Piyasa değerine" sütunu, etkinin fiyatta olup olmadığını söylemez; piyasa faiz indirimi beklentisini zaten fiyatlıyor olabilir.</li>
      </ul>`)],
    ["enerji", "Enerji", () => card("Kaynaklar", ul([
        ["Santraller", "Santraller, konumlar ve sahiplik <b>Global Energy Monitor</b> Integrated Power ve Ownership izleyicilerinden gelir (yılda yaklaşık iki kez güncellenir). Lisanslı santral listesi ve kurulu güç toplamları EPİAŞ Şeffaflık Platformu'ndan."],
        ["Pay oranı", "grup kapasitesi pay oranına göredir: ortak girişimlerde her ortağa payı kadar MW yazılır."],
        ["Yurt dışı", "yalnız sahibi ya da ana ortağı Türkiye'de kayıtlı bir şirketse alınır ve Türkiye toplamlarına katılmaz."],
        ["Kapsam dışı", "1 MW altı güneş ve izleyici eşiğinin altındaki küçük santraller."],
        ["Harita", "Natural Earth ülke ve il sınırları (kamu malı), sitenin kendi sunucusundan; harici harita servisi ya da anahtar kullanılmaz. İli belli olmayan santraller koordinattan il sınırına göre atanır."],
        ["Değerleme", "FD/MW = firma değeri / pay oranlı kurulu güç; firma değeri temel analiz verisinden, USD'ye TCMB kuru ile çevrilir."],
      ]))],
    ["regulasyon", "Regülasyon Takip", () => card("Kaynaklar ve süzme", ul([
        ["Kaynak", "kurumların kendi duyuru, sirküler ve yayın sayfaları her gün okunur (BCBS/BIS, Türkiye, Azerbaycan, Körfez ve Orta Doğu bankacılık düzenleyicileri)."],
        ["Süzme", "başlıklar ücretsiz bir AI modeliyle risk yönetimi ve model validasyonu açısından süzülür; faiz kararları, enflasyon raporları ve rutin makro duyurular hariç. Konu etiketleri ve Türkçe özetler de AI ile üretilir."],
        ["Tarih", "yayın tarihi gelecekteyse yürürlük tarihi olarak gösterilir, yayın tarihi ilk görüldüğü gün sayılır; ayrı yürürlük bilgisi varsa Yürürlük sütununda."],
        ["Erişilemeyen siteler", "bot korumalı ya da yurt dışı sunuculara kapalı kurumların korumaları aşılmaz. Bunun yerine: İsrail, Lübnan, Azerbaycan, Umman, Bahreyn ve BAE ana sitesi için Google News'in herkese açık RSS'inde kurumun alan adı aranır (site:); bu kayıtlar \u201cGoogle News\u201d etiketiyle gösterilir, tarih Google'ın dizine aldığı gündür ve genelge PDF'leri çoğu zaman bu listede yer almaz. Bahreyn'in bağlayıcı kural kitabı (CBB Rulebook) Thomson Reuters'ın barındırdığı ayrı sitesinden, BAE'ninki kendi Rulebook sitesinden okunur. Sertifika zincirini eksik gönderen sitelerde eksik ara sertifika kurumun kendi AIA adresinden tamamlanır, doğrulama kapatılmaz."],
        ["Sınır", "bağlayıcılık ve yürürlük için orijinal dokümana bak."],
      ]))],
    ["portfoy", "Portföy", () => card("Veri ve hesaplar", ul([
        ["Saklama", "pozisyonlar yalnız bu tarayıcıda saklanır, sunucuya gönderilmez; tarayıcı verisi silinirse kaybolur. Dışa aktar → Portföy yedeği (JSON) ile yedekle."],
        ["Fiyat", "son taramadan (15 dk); izleme listesi dışındaki BIST hisseleri için geri alım fiyat listesi, o da yoksa elle girilen fiyat. ABD pozisyonları TCMB USD/TRY kuruyla TL'ye çevrilir."],
        ["Risk", "1 günlük risk tarihsel yöntemle: bugünkü ağırlıklarla son 120 günün TL bazında günlük getirileri; %95 düzeyi. Betalar son 60 günde kendi endeksine (BIST 100 / S&P 500) göre."],
        ["Look-through", "her pozisyon, portföydeki TL değeri kadar şirketin karına, özkaynağına ve borcuna sahipmiş gibi toplanır."],
      ]))],
  ];
  const KEYS = SECTIONS.map(s => s[0]);
  let cur = "sinyal";

  function render() {
    const want = (sh.param || "").toLowerCase();
    if (KEYS.includes(want)) cur = want;
    const [key, title, body] = SECTIONS.find(s => s[0] === cur);
    $("#view-metodoloji").innerHTML = `<nav class="m-tabs" aria-label="Metodoloji bölümleri">${SECTIONS.map(([k, t]) =>
        `<a href="#metodoloji/${k}" class="m-tab" ${k === key ? 'aria-current="page"' : ""}>${esc(t)}</a>`).join("")}</nav>
      <div class="m-head"><h2 class="card-title">${esc(title)}</h2>${key !== "temel" ? `<a class="link-btn" href="#${key}">Sekmeye git →</a>` : `<a class="link-btn" href="#temel">Sekmeye git →</a>`}</div>
      <div class="m-body ${key === "temel" ? "" : "m-grid"}">${body()}</div>
      <p class="card-foot">Bu panel bilgi amaçlıdır, yatırım tavsiyesi değildir.</p>`;
  }
  // sekmelerden çağrılan kısa bağlantı
  window.radarMethod = { link: (key, label = "Kaynaklar ve yöntem") => `<a class="m-link" href="#metodoloji/${key}">${label} →</a>` };
  sh.register("metodoloji", { onShow: render, exports: () => [], exportNote: "Metodoloji metni" });
  addEventListener("hashchange", () => { if (sh.route === "metodoloji") render(); });
})();
