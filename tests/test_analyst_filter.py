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
