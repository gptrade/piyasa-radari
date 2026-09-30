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
- **Panel:** üç sekme, kenar çubuğundan: **Makro Veri** (`#makro`), **Sinyal Takip** (`#sinyal`), **Şirket Geri Alım** (`#geri-alim`). Adressiz açılışta son ziyaret edilen sekme gelir (ilk kez: Sinyal Takip).
  - **Üst çubuk (her sekmede aynı):** son güncelleme saati (45 dakikadan eski tarama amber görünür), Yenile, Dışa aktar (CSV; Sinyal Takip'te JSON da), koyu/açık tema.
  - **Kenar çubuğu:** sekmeler (rozetler: son ziyaretten beri gelen güçlü sinyal / son 24 saatteki geri alım işlemi), piyasa filtresi (Tümü · BIST · ABD — Sinyal Takip ve Şirket Geri Alım'daki tüm panellere uygulanır), açılır "Dış kaynaklar", kaynak sağlığı hapı ("13/14 kaynak aktif"; tıklayınca her kaynağın durumu ve son başarılı çekim zamanı). 1024 pikselin altında kenar çubuğu çekmeceye dönüşür.
  - **Sinyal Takip:** Akış / Güçlü sinyaller / Kaydedilenler; tek satırda kaynak türü çipleri (çoklu seçim), "Solukları gizle" ve "Temizle"; tablo 10 kayıtla açılır, "10 kayıt daha göster" ile genişler; tablo sütunları Yön (▲ ▼ ● · N/A) · Hisse (+N) · Olay · Önem (3 seviye) · Tepki (≠ = haber yönü ile fiyat ters) · Kaynak (tür ×N) · Zaman. Sıralama sütun başlıklarından, filtre başlıktaki huni simgesinden. Soluk satırlar nedenini yazar (tekrar, düşük güven, önemsiz, zayıf kaynak, eski, AI yok). Satıra tıkla ya da Enter: ayrıntı çekmecesi (tam metin, kaynaklar, fiyat grafiği, teknik görünüm, kaydet). "?" düğmesi simge açıklamalarını tablonun üzerinde açılan bir pencerede gösterir (içerik kaymaz). En üstte izleme listesi şeridi (renk = bugünkü fiyat, sağ üst = son 24 saatin haber yönü ve sayısı, ≠ = ters; tıkla = süz). Sağda kısa AI özeti (fikirlerin gerekçesi üzerine gelince) ve **Sinyal Haritası**: yatay net haber yönü, dikey bugünkü fiyat; taralı bölgeler haber ile fiyatın ters gittiği hisseler.
  - **Şirket Geri Alım:** ayrı repodaki [kap-geri-alim-takibi](https://github.com/gptrade/kap-geri-alim-takibi) verisi. Özet kutuları, ilk 5 şirket + Diğer yığılmış günlük grafik (bugün taralı, "gün içi"), şirket tablosu (birimler başlıkta; **Güncel / Ort.** = güncel fiyat ÷ ortalama geri alım fiyatı — fiyatlar `data/bb_quotes.json`, pipeline saatte bir Yahoo'dan toplu çeker), hisse satırında son program bildiriminin **azami pay (bin)**, **azami fon (mn ₺)** ve **süre** bilgisi (dönemde yeni program açıklayan şirketler "yeni" etiketiyle, henüz alım yapmamış olsalar da tabloda), satıra tıklayınca program bildirimi bağlantısı ve işlemler. Fiyatı şirketin diğer işlemlerinden 10 kattan fazla sapan işlemler şüpheli sayılır, toplamlara girmez; "⚠ N işlemde fiyat şüpheli" düğmesi tabloyu bunlara süzer.
  - **Makro Veri:** ayrı Vercel uygulaması [alco-dashboard](https://alco-dashboard.vercel.app/) iframe içinde. ALCO'nun kendi başlığı üstten `--alco-crop` (style.css, 84px) kadar kırpılır; koyu temada renkler çevrilir. İframe'e `?embed=1&theme=dark|light` eklenir: uygulama bunları desteklerse kırpma ve renk çevirme kaldırılabilir.
  - **Dışa aktarma:** CSV noktalı virgülle ayrılır, Excel'de Türkçe karakterlerle doğru açılır (pandas: `pd.read_csv(f, sep=';')`); ekrandaki satır sınırı olmadan filtrelenmiş görünümün tamamını içerir.
  - **Tasarım sistemi:** tüm renk, boşluk (4px ölçeği), yarıçap, yazı ve gölge değerleri `site/tokens.css`'te; açık ve koyu tema buradan gelir. Bileşenler (kart, KPI, tablo, çip, segment, sekme, durumlar) `site/style.css`'te.

## Maliyet

Varsayılan model Claude Haiku 4.5; kayıt başına birkaç yüz token çıktı. `max_items_per_run`
(varsayılan 40) üst sınırdır. İzleme listesi büyüdükçe maliyet artar; Anthropic Console'da
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
| Barchart | Google News `site:barchart.com` araması | Barchart'ın açık RSS'i doğrulanamadı |
| Kazanç takvimi | Yahoo takvimi | Bilançoya 7 gün kala akışa düşer; Earnings Hub'ın açık API'si yok |
| TradingView | Resmi "Teknik Analiz" gömme bileşeni + grafik bağlantısı | Veri API'si yok; EMA 14/34/55/200 5 yıllık kapanıştan aynı yöntemle hesaplanır |
| Godel Terminal, MarketVisuals | Sadece bağlantı | Üyelik/giriş gerektiriyor, API yok |
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
