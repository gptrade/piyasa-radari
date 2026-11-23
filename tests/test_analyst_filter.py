"""Analist haberleri süzgeci: başlıkta hem şirket hem analist ifadesi olmalı."""
from radar import pipeline
from radar.config import Stock
from radar.sources.feeds import analyst_relevant

TT = Stock("TTKOM", "Türk Telekom", "BIST", ["Türk Telekom", "Türk Telekomünikasyon"])
MS = Stock("MSFT", "Microsoft", "US", [])


def test_drops_unrelated_turkish_news():
    assert not analyst_relevant("Muş Bulanık'ta Kaymakam Koşansu, öğrencilere kitap okumalarını tavsiye etti - Haberler", TT)
    assert not analyst_relevant("Deprem bölgesinde internet altyapısı sağlanmadı: KDK vatandaşı haklı buldu - Memurlar.Net", TT)
    assert not analyst_relevant("TÜRK TELEKOM yeni tarifelerini açıkladı - AA", TT)          # şirket var, görüş yok


def test_keeps_real_analyst_notes():
    assert analyst_relevant("TÜRK TELEKOM için hedef fiyat 85 TL'ye yükseltildi - AA", TT)
    assert analyst_relevant("Aracı kurumlardan TTKOM için AL önerisi - Paratic", TT)
    assert analyst_relevant("UBS raises Microsoft stock price target to $675 - Investing.com", MS)
    assert not analyst_relevant("Microsoft unveils new Surface laptops - The Verge", MS)


def test_source_suffix_is_ignored():
    # " - Kaynak" kısmındaki kelimeler eşleşme sayılmaz
    assert not analyst_relevant("Okullarda kitap haftası başladı - Türk Telekom Hedef Fiyat Haberleri", TT)


def test_pipeline_drops_stale_items():
    items = [{"title": "Muş'ta kaymakam tavsiye etti - X", "tickers": ["TTKOM"], "extra": {"analyst_query": True}},
             {"title": "Türk Telekom hedef fiyat 90 TL - Y", "tickers": ["TTKOM"], "extra": {"analyst_query": True}},
             {"title": "Muş'ta kaymakam tavsiye etti - X", "tickers": ["TTKOM"], "extra": {}}]
    out = pipeline._drop_stale_analyst(items, [TT])
    assert [i["title"][:6] for i in out] == ["Türk T", "Muş'ta"]


def test_names_stock_requires_title_mention():
    from radar.sources.feeds import names_stock
    from radar.config import Stock
    thy = Stock(symbol="THYAO", name="Türk Hava Yolları", market="BIST", aliases=["THY"])
    assert not names_stock("2 hisse yakın izleme pazarında işleme başlayacak - Rota Borsa", thy)
    assert names_stock("THY yolcu sayısını açıkladı - AA", thy)
    assert names_stock("Türk Hava Yolları'ndan yeni sipariş - Dünya", thy)
    assert names_stock("THYAO hissesinde hareketli saatler - Borsagundem", thy)
    assert not names_stock("Borsada günün özeti - THY Haber", thy)              # kaynak adı eki sayılmaz


def test_pipeline_drops_old_unrelated_google_items():
    from radar import pipeline
    from radar.config import Stock
    thy = Stock(symbol="THYAO", name="Türk Hava Yolları", market="BIST", aliases=["THY"])
    items = [{"source": "Rota Borsa · Google News", "tickers": ["THYAO"], "title": "2 hisse yakın izleme pazarında işleme başlayacak - Rota Borsa"},
             {"source": "Dünya · Google News", "tickers": ["THYAO"], "title": "THY'den rekor yolcu - Dünya"},
             {"source": "KAP", "tickers": ["THYAO"], "title": "Özel Durum Açıklaması (Genel)"}]
    assert [x["title"][:3] for x in pipeline._drop_stale_analyst(items, [thy])] == ["THY", "Öze"]
