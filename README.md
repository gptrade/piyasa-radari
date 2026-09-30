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
- **Panel:** piyasa (BIST/ABD), tür, yön ve güven filtresi; hisseye dokununca sadece o hisse;
  kartlarda 1G/1H/1A grafik, haber anı işareti ve 15 dk / 1 sa / 1 gün tepkisi. Kaydedilenler tarayıcıda tutulur.

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
