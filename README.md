# Piyasa Radarı

BIST ve ABD hisseleri için haber, bildirim, sosyal medya ve rapor akışı. Her kayıt Claude ile
değerlendirilir (yön, güven, önem, ufuk, gerekçe, riskler), haber anından sonraki fiyat tepkisi
ölçülür ve güçlü sinyaller Telegram'a düşer. Sunucu yok: GitHub Actions toplar, GitHub Pages yayınlar.

```
 KAP + Borsa İstanbul tedbirleri ─┐  SPK bülteni ─┐  TCMB (PPK, duyuru, EVDS) ─┐
 SEC EDGAR ─┐  PR Newswire / GlobeNewswire ─┐  Google News ─┐  Yahoo RSS ─┐  AA / Bloomberg HT / Dünya ─┐
 Reddit ─┐  StockTwits ─┐  X API ─┐  inbox/ (PDF raporlar) ─┐
                                   ▼
         radar/ (15 dakikada bir, GitHub Actions)
   topla → tekilleştir → fiyat (yfinance) → Claude değerlendirmesi → fiyat tepkisi
                                   │
             ┌─────────────────────┼──────────────────────┐
             ▼                     ▼                      ▼
   site/data/feed.json      data dalı (durum)       Telegram bildirimi
             │
             ▼
   GitHub Pages paneli (site/)
```

## Kurulum (bir kez, tamamen tarayıcıdan)

0. **Dosyaları repoya yükle:** Zip'i aç. GitHub'daki boş `piyasa-radari` reposunda
   *uploading an existing file* bağlantısına tıkla ve açtığın klasörün **içindekileri** sürükle-bırak
   (`.github` klasörü dahil; Mac'te gizli klasörleri görmek için Finder'da Cmd+Shift+. ).
   Alternatif olarak terminalden:
   `cd piyasa-radari && git remote add origin https://github.com/gptrade/piyasa-radari.git && git push -u origin main`

1. **Pages'i aç:** Settings → Pages → *Build and deployment* → Source: **GitHub Actions**.
2. **Secrets ekle:** Settings → Secrets and variables → Actions → *New repository secret*

   | Secret | Gerekli mi | Açıklama |
   |---|---|---|
   | `ANTHROPIC_API_KEY` | AI yorumu için evet | console.anthropic.com → API Keys |
   | `GEMINI_API_KEY` (ya da `PIYASA_RADARI`) | yedek AI | aistudio.google.com → Get API key. Claude'un anahtarı yoksa, kredisi bittiyse ya da erişilemiyorsa değerlendirme Gemini ile yapılır |
   | `SEC_USER_AGENT` | ABD için önerilir | SEC kuralı: `Ad Soyad eposta@adres` biçiminde |
   | `TELEGRAM_BOT_TOKEN` | bildirim için | Diğer tracker'daki bot kullanılabilir |
   | `TELEGRAM_CHAT_ID` | bildirim için | Aynı sohbet ya da yeni bir kanal |
   | `X_BEARER_TOKEN` | isteğe bağlı | X API (ücretli katman). Yoksa X atlanır |
   | `EVDS_API_KEY` | makro paneli için | evds3.tcmb.gov.tr → üye ol → Profil → API Anahtarı (ücretsiz) |

3. **İlk çalıştırma:** Actions → *radar* → **Run workflow**. Birkaç dakika sonra panel
   `https://<kullanıcı>.github.io/piyasa-radari/` adresinde. Sonrasında 15 dakikada bir kendiliğinden çalışır.

## Günlük kullanım

- **Hisse eklemek/çıkarmak:** `config/watchlist.yml` dosyasını GitHub'da düzenle. `aliases`,
  haber metninde şirketi tanımak için kullanılır.
- **Ayarlar:** `config/settings.yml` — model, çalıştırma başına AI limiti, bildirim eşikleri, kaynaklar.
  Daha derin yorum için `model: claude-sonnet-5` yapılabilir (daha pahalı).
- **Rapor analizi:** aracı kurum / değerleme raporlarını `inbox/` klasörüne yükle. Ayrıntı: `inbox/README.md`.
- **Panel:** beş sekme, kenar çubuğundan: **Makro Veri** (`#makro`), **Takvim** (`#takvim`), **Sinyal Takip** (`#sinyal`), **Portföy** (`#portfoy`), **Şirket Geri Alım** (`#geri-alim`). Adressiz açılışta son ziyaret edilen sekme gelir (ilk kez: Sinyal Takip).
  - **Üst çubuk (her sekmede aynı):** son güncelleme saati (45 dakikadan eski tarama amber görünür), Yenile, Dışa aktar (CSV; Sinyal Takip'te JSON da), koyu/açık tema.
  - **Kenar çubuğu:** sekmeler (rozetler: son ziyaretten beri gelen güçlü sinyal / son 24 saatteki geri alım işlemi), piyasa filtresi (Tümü · BIST · ABD — Sinyal Takip ve Şirket Geri Alım'daki tüm panellere uygulanır), açılır "Dış kaynaklar", kaynak sağlığı hapı ("13/14 kaynak aktif"; tıklayınca her kaynağın durumu ve son başarılı çekim zamanı). 1024 pikselin altında kenar çubuğu çekmeceye dönüşür.
  - **Sinyal Takip:** Akış / Güçlü sinyaller / Kaydedilenler / **Hisseler** (izleme listesindeki her hisse, haberi olmasa da: bugünkü fiyat, teknik görünüm, RSI, 52 hafta konumu, haber yönü ve sayısı, en önemli olay). **Hisse paneli:** şerit kutusu, Sinyal Haritası balonu, Hisseler satırı ya da tablodaki hisse adına tıklayınca açılır — grafik + EMA 14/34/55/200, teknik görünüm, sonraki bilanço, en önemli haberler, BIST için geri alımlar; "Akışı bu hisseye süz" düğmesi panelde; aynı hisse için 12 saat içinde gelen aynı olay ana kaydın altında "+N benzer" olarak gruplanır; geniş ekranda (≥1400 px) satır detayı sağda yan panelde açılır (↑ ↓ ile gezinilir, Esc kapatır); mobilde tablo kart düzenine geçer ve "Sırala" seçicisi çıkar; tek satırda kaynak türü çipleri (çoklu seçim), "Solukları gizle" (varsayılan açık) ve "Temizle"; otomatik yenilemede tablo oynamaz, "N yeni kayıt" hapı çıkar; zamana göre sıralıyken "Son 1 saat · Bugün · Dün" ayraçları görünür. İzleme listesi iki satırı aşarsa şerit öne çıkanları (ters sinyal, en çok hareket eden, haberi olan) gösterir, kalanlar "+N hisse" kutusunda; Sinyal Haritası 12 balondan sonra yalnız önemli hisseleri etiketler; tablo 10 kayıtla açılır, "10 kayıt daha göster" ile genişler; tablo sütunları Yön (▲ ▼ ● · N/A) · Hisse (+N) · Olay · Önem (3 seviye) · Tepki (≠ = haber yönü ile fiyat ters) · Kaynak (tür ×N) · Zaman. Sıralama sütun başlıklarından, filtre başlıktaki huni simgesinden. Soluk satırlar nedenini yazar (tekrar, düşük güven, önemsiz, zayıf kaynak, eski, AI yok). Satıra tıkla ya da Enter: ayrıntı çekmecesi (tam metin, kaynaklar, fiyat grafiği, teknik görünüm, kaydet). "?" düğmesi simge açıklamalarını tablonun üzerinde açılan bir pencerede gösterir (içerik kaymaz). En üstte izleme listesi şeridi (renk = bugünkü fiyat, sağ üst = son 24 saatin haber yönü ve sayısı, ≠ = ters; tıkla = süz). Sağda kısa AI özeti (fikirlerin gerekçesi üzerine gelince) ve **Sinyal Haritası**: yatay net haber yönü, dikey bugünkü fiyat; taralı bölgeler haber ile fiyatın ters gittiği hisseler.
  - **Karne (Sinyal Takip > Karne):** sinyallerin geriye dönük isabeti. Her taramada yönlü sinyaller (olumlu/olumsuz, izleme listesindeki hisse) yayın anındaki hisse ve endeks fiyatıyla `data/signals.json` arşivine yazılır (aynı hisse + olay + yön 12 saat içinde bir kez; 180 gün tutulur). Yayından sonraki 1. ve 5. tam seans kapanışında notlanır: fazla getiri = hisse getirisi − aynı aralıkta BIST 100 / S&P 500 getirisi; isabet = sinyal yönü ile fazla getirinin işareti aynı. `data/scorecard.json` piyasa × dönem (30/90 gün, tümü) × ufuk kırılımında isabet oranı (%95 güven aralığıyla), yön ayarlı ortalama fazla ve ham getiriyi verir; kırılımlar: kaynak türü, olay türü, AI güveni, önem, yön, hisse, kaynak, değerlendiren (AI/kural). 10'dan az örnekli gruplar "az örnek" olarak soluk gösterilir. Baz fiyat ileriye bakmaz: gün içi veri yoksa yayın gününden önceki kapanış alınır.
  - **Habersiz hareket (⚡):** hissenin bugünkü getirisi endeksten arındırılır (son 60 günde OLS ile beta); kalan hareket son 60 günün artık oynaklığının 2,5 katını ve %2'yi aşarsa, son 24 saatte o hisseye ait KAP/SEC bildirimi ya da orta/yüksek önemli haber yoksa akışa "Habersiz hareket" kaydı düşer (gün başına hisse ve yön için bir kez, AI kotası harcamaz, Telegram'a gider: `notify.anomaly`). Şeritte ⚡ ve turuncu çerçeve, hisse panelinin en üstünde uyarı kutusu; karnede "Habersiz hareket" türü olarak notlanır (hareketin sürüp sürmediği ölçülür). Eşikler: `sources.anomaly`.
  - **Akış dengesi:** akış hisse başına dengelenir (`feed.max_per_ticker`, `min_per_ticker`); haber yönü, olumlu haberden hissenin olağan iyimserlik payı düşülerek hesaplanır (hisse panelinde ham ve normal değer görünür).
  - **Takvim (`#takvim`):** önümüzdeki 2 hafta / 1 ay / 2 aylık katalizörler, İstanbul saatiyle: TCMB faiz kararı ve raporları, TÜİK TÜFE ve GSYH, Fed (FOMC) kararı, ABD TÜFE (`config/calendar.yml`; tarihler resmi takvimlerden, yeni yıl açıklanınca eklenir), VİOP endeks vadeli vade sonu (çift ayların son iş günü) ve ABD opsiyon vadesi (3. cuma; Mart/Haziran/Eylül/Aralık dörtlü vade) hesaplanır, izleme listesindeki şirketlerin bilanço ve temettü hak kullanım tarihleri Yahoo'dan (`data/calendar.json`). Üstte sıradaki 3 önemli olay geri sayımla; tür çipleri, "Yalnız önemli", piyasa filtresi; hisseye tıklayınca hisse paneli. Kenar çubuğu rozeti: bugün ve yarın kaç önemli olay var.
  - **Portföy (`#portfoy`):** pozisyonlar (hisse, adet, ortalama maliyet, isteğe bağlı stop/hedef/not) **yalnız tarayıcıda** (localStorage `radar.portfolio.v1`) saklanır, sunucuya gönderilmez; Dışa aktar → Portföy yedeği (JSON) ile indirilip başka cihazda "İçe aktar" ile yüklenir (ileride `config/portfolio.yml`'e taşınabilir biçim). Fiyat: izleme listesi fiyat dosyaları → BIST geri alım fiyat listesi → elle fiyat; ABD pozisyonları TCMB EVDS USD/TRY ile (ya da elle girilen kur) TL'ye çevrilir. Gösterilenler: portföy değeri (TL ve $), bugünkü ve toplam K/Z, 1 günlük %95 tarihsel riske maruz değer (bugünkü ağırlıklar, son 120 gün, ABD için kur dahil), dağılım (ilk 5 + Diğer, BIST/ABD payı, BIST ve ABD betası), pozisyon tablosu (ağırlık, K/Z, stop/hedefe uzaklık, son 24 saat sinyal özeti, ⚡ habersiz hareket, yaklaşan bilanço/temettü), pozisyonlardaki son 48 saatin önemli gelişmeleri. Stop/hedef geçilince satır ve üst bant uyarır, kenar çubuğunda rozet çıkar (Telegram'a gitmez; tarayıcıda saklandığı için sunucu pozisyonları bilmez).
  - **Şirket Geri Alım:** ayrı repodaki [kap-geri-alim-takibi](https://github.com/gptrade/kap-geri-alim-takibi) verisi. Özet kutuları, ilk 5 şirket + Diğer yığılmış günlük grafik (bugün taralı, "gün içi"), şirket tablosu (birimler başlıkta; **Güncel / Ort.** = güncel fiyat ÷ ortalama geri alım fiyatı — fiyatlar `data/bb_quotes.json`, pipeline saatte bir Yahoo'dan toplu çeker), hisse satırında son program bildiriminin **azami pay (bin)**, **azami fon (mn ₺)** ve **süre** bilgisi (dönemde yeni program açıklayan şirketler "yeni" etiketiyle, henüz alım yapmamış olsalar da tabloda), satıra tıklayınca program bildirimi bağlantısı ve işlemler. Fiyatı şirketin diğer işlemlerinden 10 kattan fazla sapan işlemler şüpheli sayılır, toplamlara girmez; "⚠ N işlemde fiyat şüpheli" düğmesi tabloyu bunlara süzer.
  - **Makro Veri:** ayrı Vercel uygulaması [alco-dashboard](https://alco-dashboard.vercel.app/) iframe içinde. ALCO'nun kendi başlığı üstten `--alco-crop` (style.css, 84px) kadar kırpılır; koyu temada renkler çevrilir. İframe'e `?embed=1&theme=dark|light` eklenir: uygulama bunları desteklerse kırpma ve renk çevirme kaldırılabilir.
  - **Dışa aktarma:** CSV noktalı virgülle ayrılır, Excel'de Türkçe karakterlerle doğru açılır (pandas: `pd.read_csv(f, sep=';')`); ekrandaki satır sınırı olmadan filtrelenmiş görünümün tamamını içerir.
  - **Tasarım sistemi:** tüm renk, boşluk (4px ölçeği), yarıçap, yazı ve gölge değerleri `site/tokens.css`'te; açık ve koyu tema buradan gelir. Bileşenler (kart, KPI, tablo, çip, segment, sekme, durumlar) `site/style.css`'te.

**Önceki sürüme dönmek:** her büyük arayüz değişikliğinden önce yayındaki sürüm `yedek-…` adlı bir dalda saklanır (ör. `yedek-2026-10-01-hisse-paneli-oncesi`). Geri dönmek için o dalı `main`'e birleştirmek ya da ilgili commit'i geri almak yeterli.

## Maliyet

Varsayılan model Claude Haiku 4.5; kayıt başına birkaç yüz token çıktı. `max_items_per_run`
(varsayılan 40) üst sınırdır; bu kota hisseler arasında sırayla dağıtılır (çok haber üreten bir hisse kotayı tek başına tüketmez). İzleme listesi büyüdükçe maliyet artar; Anthropic Console'da
harcama limiti koymak iyi olur. GitHub Actions: public repoda ücretsiz, private repoda aylık
dakika kotasından düşer (15 dk'da bir ≈ 2.900 çalıştırma/ay).

## Kaynaklar ve sınırlar

| Kaynak | Yöntem | Not |
|---|---|---|
| KAP | kap.org.tr bildirim sorgu uç noktası | Resmi, belgelenmiş bir API değil; KAP değiştirirse `radar/sources/kap.py` güncellenmeli |
| Borsa İstanbul tedbirleri | KAP'taki "Borsa İstanbul A.Ş. Duyurusu" kayıtları | Brüt takas, tek fiyat, kredili işlem/açığa satış yasağı, emir paketi, işlem sırası durdurma; kaldırılması da ayrı etiketlenir |
| SPK bülteni | spk.gov.tr yıllık bülten sayfası → PDF | İzleme listesindeki şirketlerin geçtiği bölümler Claude'a gider |
| TCMB | Resmi RSS: PPK kararları, basın duyuruları, başkan konuşmaları | Piyasa geneli; Claude etkilenecek hisseleri işaretler (konuşmalar sadece listelenir) |
| TCMB EVDS | evds3 API | Kur, fonlama maliyeti vb.; seri kodları `settings.yml`'de |
| PR Newswire, GlobeNewswire | Genel RSS | "(NASDAQ: XXX)" etiketi ya da başlıkta şirket adıyla eşleşir |
| SEC EDGAR | Şirket bazlı Atom akışı | 8-K, 10-Q/K, Form 4, 13D/G, 6-K, S-1 |
| Google News | Hisse bazlı RSS araması | TR ve EN ayrı sorgu |
| Yahoo Finance | Hisse bazlı RSS | ABD |
| AA, Bloomberg HT, Dünya | Genel RSS + şirket adı eşleştirme | `settings.yml`'den kaynak eklenebilir |
| Reddit, StockTwits | Herkese açık RSS / JSON | Söylenti riski: Claude güveni düşük tutar |
| X (Twitter) | Resmi API v2 | Ücretli anahtar gerekir |
| Fiyatlar | yfinance (Yahoo) | Gecikmeli; BIST için `.IS` eki |
| Investing.com Türkiye | Resmi RSS: BİST, şirket haberleri, insider, analist dereceleri, kazanç görüşmeleri, hisse analizleri | Hem BIST hem ABD hisseleriyle eşleşir |
| Barchart, MarketWatch, TradingView (ABD) · Fintables, TradingView (BIST) | Google News `site:` araması, hisse başına tek sorgu (`google_news.sites`) | TradingView ve Fintables'ın resmi haber akışı/API'si yok, kullanım koşulları kazımayı yasaklıyor; yalnızca Google'ın indekslediği başlık + bağlantı alınır |
| TÜİK | turkiye.gov.tr TÜİK haber bülteni listesi (15 dk) | Başlık sonucu içerir ("işsizlik oranı %7,8"); yalnız piyasayı ilgilendiren bültenler (TÜFE, ÜFE, GSYH, işsizlik, dış ticaret, güven endeksleri, konut, sanayi…) |
| BDDK | Basın ve mevzuat duyuruları (30 dk) | Sunucu ara sertifikayı göndermiyor; GlobalSign'ın herkese açık ara sertifikası güvenilen köklere eklenir (doğrulama kapatılmaz) |
| Resmi Gazete | Günün sayısı (gece bir kez) | Vergi, kambiyo, bankacılık, sermaye piyasası, enerji piyasası, teşvik vb. anahtar kelimeli düzenlemeler |
| Borsa İstanbul duyuruları | /en/announcement listesi (15 dk) | Endeks dönemsel değişiklikleri, pazar geçişleri, açığa satış kuralları, prosedür değişiklikleri; gong törenleri hariç |
| SPK basın duyuruları | Yıl listesi (30 dk) | Bültenden ayrı; şirket adı geçerse hisseye bağlanır |
| Hazine | Haber araması (30 dk) | HMB sitesi yalnız JavaScript ile çalışıyor; ihale/borçlanma haberleri Google News'ten |
| TCMB | + Yayınlar ve Veriler RSS | Enflasyon Raporu, FİR, Piyasa Katılımcıları Anketi, ödemeler dengesi, rezervler |
| Ekonomim | Resmi RSS (Şirket, Piyasa) | |
| Marketaux | API (`MARKETAUX_API_TOKEN`), saatte bir, piyasa başına 1 istek (ücretsiz plan: günde 100 istek, istek başına 3 haber) | Şirket etiketli haber; Marketaux'nun kendi skoru (−1…+1) kayıt ayrıntısında "ikinci görüş" olarak görünür ve karnede ayrı değerlendirici olarak notlanır (ana toplamlara karışmaz). Skor sözlük tabanlı: finans dilini yanlış okuyabilir. BIST kapsamı zayıf (`.IS` sembolleri) |
| Finnhub | API (`FINNHUB_API_KEY`), her ABD hissesi için 30 dakikada bir istek (ücretsiz plan: dakikada 60 istek) | ABD şirket haberleri. Ücretsiz planda yalnız Kuzey Amerika şirketleri; Finnhub'ın duygu skoru ücretli olduğu için değerlendirmeyi AI yapar. Aynı haberin başka kaynaktaki kopyası tek kayıtta birleşir |
| Alpha Vantage | API (`ALPHAVANTAGE_API_KEY`), turda en fazla 1 istek, ABD hisseleri sırayla; günde en fazla 20 (ücretsiz plan: günde 25) | ABD haberleri + hisse bazında duygu skoru ve ilgililik. Skor "ikinci görüş" olarak gösterilir, karnede ayrı değerlendirici olarak notlanır. Aynı haber başka kaynaktan geldiyse skor o kayda taşınır |
| Belge okuma | KAP bildirim sayfası + ekli PDF'ler, SEC 8-K dosya dizini (EX-99), turda en fazla 4 belge | İzleme listesi şirketlerinin yatırımcı sunumu, finansal rapor, faaliyet raporu, yatırımcı/değerleme raporu ve 8-K basın bülteni/sunum ekleri AI'a tam metin verilir; panelde "Belge" rozeti ve belge özeti (bulgular, rakamlar, riskler). Belge metni yayımlanmaz, yalnız özet |
| Gizli rapor kutusu | Gizli repo `gptrade/piyasa-radari-raporlar` (`RAPOR_REPO_TOKEN`, salt-okunur), `sirket/` `sektor/` `strateji/` klasörleri; PDF, TXT, MD, JPG, PNG; çok sayfalı görsel raporlar alt klasörde (1.jpg, 2.jpg…); turda en fazla 2 rapor | AI raporu okur (görsel/taranmış sayfalar dahil). Sitede yalnız kurum, tavsiye, hedef fiyat, tahmin değişimleri, kısa tez ve öne çıkan hisseler; ayrıntılı özet yalnız Telegram'a. Rapor dosyaları `site/` dışına çekilir, yayımlanmaz; okunanlar içerik özetiyle hatırlanır |
| Temel analiz (KAP mali tabloları) | KAP finansal rapor bildirimlerinin dışa aktarımı (bilanço, kar/zarar, nakit akışı), BIST-100; TÜFE: TCMB EVDS `TP.GENENDEKS.T1`; fiyat: Yahoo (saatlik, yalnız son kapanış); sektör: KAP | Radar iş akışında 180 sn bütçeli ayrı adım, çalıştırma başına en fazla 24 KAP isteği (429'da 30 dk ara). Geçmiş 2023'ten kademeli yüklenir. Bankalar, sigorta ve finansal kiralama kapsam dışı (farklı şablon). Çeyreklik/12A/reel hesaplar, ~37 oran, Piotroski, Altman Z'', Beneish M, kategori puanları, sektör medyanına göre değerleme, kriter setleri (Graham, Buffett, Lynch, Greenblatt) |
| Değerleme | Yahoo Finance (yfinance), günde bir | Hisse panelinde F/K, ileri F/K, PD/DD, FD/FAVÖK, F/S, PEG, temettü verimi, özsermaye kârlılığı, marj, büyüme, borç/özsermaye, beta; izleme listesinde aynı alt sektörden hisse varsa emsal medyanı. Bilanço para birimi fiyatınkinden farklıysa (ör. THYAO: USD bilanço) fiyat tabanlı çarpanlar tutarsız olduğundan gösterilmez |
| Fed · ECB · IMF | Fed para politikası ve konuşma RSS'i, ECB basın RSS'i; IMF ve yaptırım haberleri Google News konu aramasıyla (Hazine/OFAC ve IMF RSS'leri otomatik erişime kapalı) | Faiz kararları, politika metinleri (sayfadan tam metin), ekonomi/para politikası konuşmaları. Makro kayıt olarak akışa girer, AI izleme listesine etkisini yazar |
| GDELT (dünya basını) | api.gdeltproject.org, ücretsiz ve anahtarsız; saatte bir, tema başına 1 istek (hacim artınca +1 ton isteği, 8 sn aralık). GitHub sunucularından sık sık hız sınırına (429) takılıyor: o tur atlanır, kaynak durumunda uyarı görünür | Türkiye (dünya basını), Türk basını ve petrol temalarında son 2 saatin haber payı olağanın 3 katını aşar ya da ton 2 puan saparsa öne çıkan başlıklarla makro alarm. Tema başına 6 saatte en fazla bir alarm |
| Matriks / Foreks | Yalnız arayüz (`radar/sources/vendors.py`) | `MATRIKS_API_KEY`+`MATRIKS_API_SECRET` ya da `FOREKS_USERNAME`+`FOREKS_PASSWORD` tanımlanırsa devreye girer; bağlantı kodu sözleşme sonrası yazılacak |
| Borsa İstanbul günlük bülteni | Resmi ücretsiz gün sonu dosyası `/data/thb/YYYY/AA/thbYYYYAAGG1.zip` (seans sonrası yayımlanır) | İzleme listesi BIST hisseleri için açığa satış hacminin toplam hacimdeki payı, açığa satış izni ve brüt takas tedbiri bayrakları `data/bist_flows.json`'da birikir (~45 seans). Pay 20 seans ortalamasının 2 katını ve %5'i aşarsa akışa "Açığa satış artışı" düşer (`sources.bist_bulletin`). Hisseler görünümünde "Açığa sat." sütunu, hisse panelinde son 30 seans grafiği. Ham dosya yeniden yayımlanmaz |
| Borsa İstanbul genel kurul listesi | `/data/gk/gkYYYY.zip` (günde bir) | İzleme listesi BIST hisselerinin genel kurulları (tarih, saat, gündem, KAP bağlantısı) Takvim'e düşer |
| MarketWatch | Dow Jones resmi RSS (Top Stories) | ABD hisseleri şirket adıyla eşleşir |
| Analist haberleri | Google News: "hedef fiyat / tavsiye / model portföy" (BIST), "price target / upgrade / downgrade" (ABD) (`google_news.analyst_terms`) | Hisse panelinde "Analist haberleri" altında da listelenir |
| Analist notları | Yahoo Finance (yfinance): not değişiklikleri, hedef fiyatlar, tavsiye dağılımı | Son 3 günün not artırımı/indirimi akışa kural tabanlı düşer (AI kotası harcamaz, Telegram kurallarına tabi). Hedef fiyat ve dağılım hisse panelinde; 6 saatte bir yenilenir (`sources.analyst`). BIST'te kapsama sınırlı |
| Kazanç takvimi | Yahoo takvimi | Bilançoya 7 gün kala akışa düşer; Earnings Hub'ın açık API'si yok |
| TradingView | Resmi "Teknik Analiz" gömme bileşeni + grafik bağlantısı | Veri API'si yok; EMA 14/34/55/200 5 yıllık kapanıştan aynı yöntemle hesaplanır |
| Godel Terminal, MarketVisuals | Sadece bağlantı | Üyelik/giriş gerektiriyor, API yok |
| Teknik olaylar | Fiyat verisinden (5 yıllık günlük kapanış) | EMA55/EMA200 kesişimi, fiyatın EMA55/EMA200'ü kesmesi, RSI 70/30 eşikleri, 52 hafta zirve/dip, hacim patlaması (20 gün ortalamasının 3 katı). Haber olmasa da akışa "Teknik" türünde düşer, aynı gün aynı olay bir kez gelir, AI kotası harcamaz. Telegram'a gider (`notify.technical`), kapatmak için `sources.technical.enabled: false` |
| Aracı kurum raporları | `inbox/` | Kapalı portallara giriş yapılmaz; raporu sen yüklersin |

**TradingView:** Haber akışı için resmi bir API yok ve üyelik bilgileriyle otomatik oturum açıp
veri çekmek kullanım şartlarına aykırı, bu yüzden radar TradingView'e bağlanmaz. TradingView'i
grafik ve Pine Script tarafında kullanmaya devam edebilirsin; panel her hissenin grafiğini zaten gösterir.

Bu araç yatırım tavsiyesi değildir; Claude değerlendirmeleri olasılıksal ve hatalı olabilir.

## Yerelde deneme

```bash
pip install -r requirements.txt
python -m pytest -q
python -m radar demo          # ağsız örnek veri
cd site && python -m http.server 8000
```
