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
      ]))],
    ["temel", "Temel Analiz", () => window.radarFundamentals?.methodHTML?.() || ""],
    ["banka-faiz", "Banka Faiz Duyarlılığı", () => card("Yöntem ve sınırlar", `<ul>
        <li><b>Veri.</b> KAP'taki banka mali tabloları (solo/konsolide, bankanın yayımladığı): faiz gelirleri ve giderleri çeyreklere ayrılır, ortalama toplam aktife bölünüp yıllıklandırılır. Politika faizi: TCMB ağırlıklı ortalama fonlama maliyeti (EVDS, günlük → çeyrek ortalaması). Beklenti: TCMB Piyasa Katılımcıları Anketi, 12 ay sonrası politika faizi.</li>
        <li><b>Model.</b> Aktif getirisi ve fonlama maliyeti ayrı ayrı faizin bu ve önceki çeyrek ortalamasına regrese edilir. Banka katsayıları bankalar arası havuz tahminine doğru gözlem gürültüsüyle orantılı büzülür (az çeyreği olan banka sektöre daha çok benzer). 1 yıllık etki = bu çeyrek katsayısı + önceki çeyreğin ¾'ü (12 ayda geçişin dört çeyreğe yayıldığı varsayımı).</li>
        <li><b>Örneklem.</b> Ana model 2024 T1'den başlar: 2023'teki KKM, menkul kıymet tesis ve kredi büyüme sınırları faiz geçişkenliğini bozdu. "2023 dahil" düğmesi sağlamlık için aynı hesabı uzun örneklemle verir; ikisi çok ayrışıyorsa sonuç düzenleme rejimine duyarlıdır.</li>
        <li><b>Sınırlar.</b> TL/döviz karışımı ayrıştırılmaz (döviz fonlama faiz giderini TL faizinden bağımsız etkiler). Swap fonlaması faiz giderinde değil ticari kâr/zararda görünür: swap kullanımı yüksek bankada gerçek fonlama maliyeti ve duyarlılık eksik ölçülür. TÜFE'ye endeksli menkul kıymet geliri enflasyona bağlıdır, faize değil; enflasyon düşüşü bu geliri ayrıca azaltır. Bilanço büyümesi, kredi/mevduat karması değişimi, karşılık giderleri ve vergi oranı sabit kabul edilir. Katılım bankaları kapsam dışıdır.</li>
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
