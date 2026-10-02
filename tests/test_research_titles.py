from radar import research as rs

KNOWN = {"GLRMK": ["Gülermak"], "THYAO": ["Türk Hava Yolları", "THY"], "AKSEN": ["Aksa Enerji"], "OTKAR": ["Otokar"]}
CASES = [
    ("StoneX, Synopsys hissesi için hedef fiyatını korudu - Investing.com Türkiye", dict(broker="StoneX", name="Synopsys", action="keep")),
    ("Morgan Stanley, McDonald’s hisse hedef fiyatını 297 dolara düşürdü - Investing.com Türkiye", dict(broker="Morgan Stanley", name="McDonald", tp=297, action="down", cur="USD")),
    ("BTIG, Nike’ın hedef fiyatını zayıf görünüm nedeniyle 50 dolara düşürdü - Investing.com Türkiye", dict(broker="BTIG", name="Nike", tp=50, action="down")),
    ("Stifel, ON Semiconductor hissesi için Tut tavsiyesini korudu - Investing.com Türkiye", dict(broker="Stifel", name="ON Semiconductor", rating="TUT", action="keep")),
    ("Cantor Fitzgerald, Netstreit hissesi için Overweight tavsiyesini korudu", dict(broker="Cantor Fitzgerald", rating="AL")),
    ("Yapı Kredi Yatırım’dan Otokar için 780 TL hedef fiyat - borsamatik.com.tr", dict(broker="Yapı Kredi Yatırım", t="OTKAR", tp=780, cur="TRY")),
    ("Deniz Yatırım PETKM için 21 TL'lik Hedef Fiyat Açıkladı - paraajansi.com.tr", dict(broker="Deniz Yatırım", t="PETKM", tp=21)),
    ("İş Yatırım Aksa Enerji'yi model portföyüne ekledi - borsamatik.com.tr", dict(broker="İş Yatırım", t="AKSEN", action="add", rating="AL")),
    ("Freedom Capital, CoreWeave için 151 dolar hedefle Al tavsiyesini yineledi", dict(broker="Freedom Capital", name="CoreWeave", tp=151, rating="AL")),
    ("Yapı Kredi Yatırım Otokar İçin Hedef Fiyatını Açıkladı - Paranın Yönü", dict(broker="Yapı Kredi Yatırım", t="OTKAR")),
    ("Gedik Yatırım, Tofaş Hedef Fiyatını %55 Yükseltti!!! - Para Ajansı", dict(broker="Gedik Yatırım", name="Tofaş", action="up")),
    ("Ziraat Yatırım, Galata Wind İçin 'AL' Tavsiyesi Verdi! - Para Ajansı", dict(name="Galata Wind", rating="AL")),
    ("Ak Yatırım Model Portföyünü Güncelledi: Aselsan İçin Hedef 520 TL - Paranın Yönü", dict(broker="Ak Yatırım", name="Aselsan", tp=520)),
    ("AKSEN İş Yatırım’ın Model Portföyüne Girdi: Hedef Fiyat Kaç TL? - Para Ajansı", dict(broker="İş Yatırım", t="AKSEN", action="add")),
    ("HİSSE DEĞERLENDİRMESİ-Yapı Kredi Yatırım, OTKAR-Otokar için hedef fiyatını 780 TL, tavsiyesini \"al\" olarak korudu", dict(t="OTKAR", tp=780, rating="AL", action="keep")),
]
NONE = ["Gülermak için hedef fiyat revizyonu: Tavsiye “endeks üstü getiri” - Paratic Haber",
        "ASELS, TUPRS, FROTO ve DOAS dahil 6 hisse için hedef fiyat açıklandı - Rota Borsa",
        "Borsa günü yükselişle tamamladı", "Portföyler için önerilen 30 hisse - Para Dergi"]


def test_titles():
    for title, exp in CASES:
        n = rs.parse_note(title, "", KNOWN)
        assert n, title
        for k, v in exp.items():
            assert (n[k] or "").startswith(v) if k == "name" else n[k] == v, (title, k, n)


def test_non_notes():
    for t in NONE:
        assert rs.parse_note(t, "", KNOWN) is None, (t, rs.parse_note(t, "", KNOWN))
