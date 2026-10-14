"""Türkiye resmi veri takvimi: TÜİK "Ulusal Veri Yayımlama Takvimi" (Resmi İstatistik Programı).

Kaynak: www.tuik.gov.tr/Kurumsal/Veri_Takvimi sayfasının kullandığı açık JSON
(/Kurumsal/GetYillikHaberBulteniListesi?yil=YYYY). TÜİK, TCMB, BDDK, Hazine ve Maliye Bakanlığı, SPK ve diğer
kurumların bütün yıl için planlanan yayın tarih ve saatleri. www.tuik.gov.tr robots.txt yok; veri portalı robots.txt
tüm botlara açık. Günde iki kez çekilir.

Yalnız piyasa açısından anlamlı yayınlar (RULES) takvime girer; her biri için kısa ad, grup, önem, etkilediği varlıklar
ve kısa açıklama eklenir. Aynı anda yayımlanan alt tablolar (ör. BDDK bülteninin 6 tablosu) tek olayda birleşir.
Her iş günü yayımlanan seriler (gösterge kurlar, PÖS/EFT, analitik bilanço…) ızgarayı doldurmasın diye ayrı listelenir.
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import http
from .config import DATA
from .models import iso, now_utc

log = logging.getLogger("radar.trcal")

URL = "https://www.tuik.gov.tr/Kurumsal/GetYillikHaberBulteniListesi?yil={y}"
PAGE = "https://www.tuik.gov.tr/Kurumsal/Veri_Takvimi"
RAW_FILE = DATA / "tr_calendar_raw.json"
REFRESH_H = 12
IST = ZoneInfo("Europe/Istanbul")

BANKS = "bankalar (AKBNK, GARAN, ISCTR, YKBNK)"
# (desen, kurum, anahtar, kısa ad, grup, önem, etkilediği varlıklar, açıklama)
# önem: 3 yüksek · 2 orta · 1 düşük · 0 = her iş günü (ızgaraya girmez, "günlük veriler" listesinde)
RULES: list[tuple[str, str | None, str, str, str, int, list[str], str]] = [
    # Enflasyon
    (r"^Tüketici Fiyat Endeksi", "TÜİK", "tufe", "TÜFE", "Enflasyon", 3,
     ["TCMB faiz beklentisi", "TL tahvil ve mevduat faizleri", BANKS, "BIST 100"],
     "Aylık ve yıllık tüketici enflasyonu; PPK kararının ana girdisi, TÜFE'ye endeksli tahvillerin kuponu"),
    (r"^Yurt İçi Üretici Fiyat Endeksi", "TÜİK", "ufe", "Yİ-ÜFE", "Enflasyon", 2,
     ["Sanayi şirketlerinin maliyetleri", "TÜFE'ye geçiş beklentisi"], "Üretici fiyatları; maliyet baskısının öncü göstergesi"),
    (r"^Yurt Dışı Üretici Fiyat Endeksi", "TÜİK", "yd_ufe", "Yurt Dışı ÜFE", "Enflasyon", 1,
     ["İhracatçı şirketler"], "İhraç edilen ürünlerin üretici fiyatları"),
    (r"^Hizmet Üretici Fiyat Endeksi", "TÜİK", "h_ufe", "Hizmet ÜFE", "Enflasyon", 1,
     ["Hizmet enflasyonu"], "Hizmet sektöründe üretici fiyatları"),
    (r"^Tarım Ürünleri Üretici Fiyat Endeksi", "TÜİK", "tarim_ufe", "Tarım ÜFE", "Enflasyon", 1,
     ["Gıda enflasyonu", "gıda şirketleri"], "Tarım ürünlerinde üretici fiyatları; gıda enflasyonunun öncüsü"),
    (r"^Tarımsal Girdi Fiyat Endeksi", "TÜİK", "tarim_girdi", "Tarımsal Girdi Fiyatları", "Enflasyon", 1,
     ["Gübre üreticileri (GUBRF, BAGFS)", "gıda enflasyonu"], "Gübre, yem, enerji gibi tarımsal girdilerin fiyatları"),
    (r"^İnşaat Maliyet Endeksi", "TÜİK", "insaat_maliyet", "İnşaat Maliyet Endeksi", "Konut ve inşaat", 1,
     ["Konut geliştiriciler ve GYO'lar", "çimento"], "Malzeme ve işçilik maliyetleri"),
    (r"^Finansal Yatırım Araçlarının Reel Getiri", "TÜİK", "reel_getiri", "Yatırım Araçları Reel Getiri", "Enflasyon", 1,
     ["BIST, altın, döviz, mevduat karşılaştırması"], "Aylık getiriler enflasyondan arındırılmış olarak"),
    # Büyüme, üretim, talep
    (r"^Dönemsel Gayrisafi Yurt İçi Hasıla", "TÜİK", "gsyh", "GSYH (büyüme)", "Büyüme ve üretim", 3,
     ["BIST 100", "TL varlıklar", "döngüsel sektörler"], "Çeyreklik ekonomik büyüme"),
    (r"^Yıllık Gayrisafi Yurt İçi Hasıla", "TÜİK", "gsyh_y", "Yıllık GSYH", "Büyüme ve üretim", 2,
     ["BIST 100", "TL varlıklar"], "Yıllık milli gelir"),
    (r"^Sanayi Üretim Endeksi", "TÜİK", "sanayi", "Sanayi Üretimi", "Büyüme ve üretim", 2,
     ["Sanayi hisseleri (XUSIN)", "büyüme beklentisi"], "İmalat, madencilik ve enerjide üretim hacmi"),
    (r"^Hizmet Üretim Endeksi", "TÜİK", "hizmet", "Hizmet Üretimi", "Büyüme ve üretim", 1,
     ["Hizmet şirketleri"], "Hizmet sektöründe üretim hacmi"),
    (r"^İnşaat Üretim Endeksi", "TÜİK", "insaat", "İnşaat Üretimi", "Konut ve inşaat", 1,
     ["Çimento (AKCNS, CIMSA, OYAKC)", "inşaat ve GYO"], "İnşaat sektörü üretim hacmi"),
    (r"^Ticaret Satış Hacim Endeksi", "TÜİK", "perakende", "Ticaret Satış Hacmi", "Büyüme ve üretim", 2,
     ["Perakende (BIMAS, MGROS, SOKM)", "iç talep"], "Perakende ve toptan satış hacmi; iç talebin göstergesi"),
    (r"^Ciro Endeksleri", "TÜİK", "ciro", "Ciro Endeksleri", "Büyüme ve üretim", 1,
     ["Sanayi, ticaret ve hizmet şirketleri"], "Sektörlerin nominal satış hasılatı"),
    (r"^Motorlu Kara Taşıtları", "TÜİK", "tasit", "Motorlu Taşıt Kayıtları", "Sektör verisi", 1,
     ["Otomotiv (FROTO, TOASO, DOAS)", "taşıt kredileri"], "Trafiğe kaydı yapılan taşıtlar"),
    (r"^Yapı İzin İstatistikleri", "TÜİK", "yapi_izin", "Yapı İzinleri", "Konut ve inşaat", 1,
     ["Çimento, inşaat ve GYO"], "Verilen yapı ruhsatları; inşaat faaliyetinin öncüsü"),
    # Güven ve anketler
    (r"^İmalat Sanayi Kapasite Kullanım", "TCMB", "kko", "Kapasite Kullanım Oranı", "Güven ve anket", 2,
     ["Sanayi hisseleri (XUSIN)"], "İmalat sanayinde kapasite kullanımı"),
    (r"^İktisadi Yönelim .*Reel Kesim Güven", "TCMB", "rkge", "Reel Kesim Güven Endeksi", "Güven ve anket", 2,
     ["Sanayi hisseleri (XUSIN)", "büyüme beklentisi"], "İmalat sanayi yöneticilerinin beklentileri"),
    (r"^Tüketici Güven Endeksi", "TÜİK", "tge", "Tüketici Güven Endeksi", "Güven ve anket", 2,
     ["Perakende ve tüketici şirketleri"], "Hanehalkının ekonomik durum ve harcama beklentisi"),
    (r"^Ekonomik Güven Endeksi", "TÜİK", "ege", "Ekonomik Güven Endeksi", "Güven ve anket", 1,
     ["BIST 100"], "Tüketici ve sektör güven endekslerinin bileşimi"),
    (r"^Hizmet, Perakende Ticaret ve İnşaat Güven", "TÜİK", "sektor_guven", "Sektörel Güven Endeksleri", "Güven ve anket", 1,
     ["Hizmet, perakende ve inşaat şirketleri"], "Hizmet, perakende ve inşaat sektörlerinde güven"),
    (r"^Finansal Hizmetler İstatistikleri", "TCMB", "fin_guven", "Finansal Hizmetler Güven Endeksi", "Güven ve anket", 1,
     [BANKS], "Finans sektörü yöneticilerinin beklentileri"),
    (r"^Yatırım Eğilimi", "TCMB", "yatirim_egilim", "Yatırım Eğilimi Anketi", "Güven ve anket", 1,
     ["Sanayi hisseleri"], "Şirketlerin yatırım planları"),
    (r"^Dış Ticaret Beklenti Anketi", None, "dt_beklenti", "Dış Ticaret Beklenti Anketi", "Güven ve anket", 1,
     ["İhracatçı şirketler"], "Ticaret Bakanlığının ihracatçı beklenti anketi"),
    # İstihdam
    (r"^İşgücü İstatistikleri", "TÜİK", "isgucu", "İşgücü (işsizlik)", "İstihdam", 2,
     ["TCMB faiz beklentisi", "iç talep"], "İşsizlik oranı, istihdam ve işgücüne katılım"),
    (r"^Dönemsel İşgücü İstatistikleri", "TÜİK", "isgucu_d", "Dönemsel İşgücü", "İstihdam", 1,
     ["İç talep"], "Çeyreklik işgücü göstergeleri"),
    (r"^Ücretli Çalışan İstatistikleri", "TÜİK", "ucretli", "Ücretli Çalışanlar", "İstihdam", 1,
     ["İç talep"], "Kayıtlı ücretli çalışan sayısı (idari kayıt)"),
    (r"^İşgücü Girdi Endeksleri", "TÜİK", "isgucu_girdi", "İşgücü Girdi Endeksleri", "İstihdam", 1,
     ["Ücret enflasyonu", "şirket maliyetleri"], "Saatlik işgücü maliyeti ve kazanç"),
    (r"^Sanayide Birim Ücret", None, "birim_ucret", "Sanayide Birim Ücret", "İstihdam", 1,
     ["Sanayi şirketlerinin maliyetleri"], "Sanayide birim ücret endeksi"),
    # Dış denge
    (r"^Ödemeler Dengesi", "TCMB", "odemeler", "Ödemeler Dengesi (cari denge)", "Dış denge", 3,
     ["Döviz kuru (USD/TRY)", "ülke risk primi (CDS)", "TL varlıklar"], "Cari işlemler dengesi ve finansmanı"),
    (r"^Dış Ticaret İstatistikleri", "TÜİK", "dis_ticaret", "Dış Ticaret", "Dış denge", 2,
     ["İhracatçı şirketler", "döviz kuru", "cari denge beklentisi"], "İhracat, ithalat ve dış ticaret açığı (kesin veri)"),
    (r"^Dış Ticaret Endeksleri", "TÜİK", "dt_endeks", "Dış Ticaret Endeksleri", "Dış denge", 1,
     ["İhracatçı şirketler"], "Dış ticarette birim değer ve miktar endeksleri"),
    (r"^Uluslararası Rezervler", "TCMB", "rezerv", "Uluslararası Rezervler", "Dış denge", 2,
     ["Döviz kuru (USD/TRY)", "ülke risk primi (CDS)"], "TCMB rezervleri ve kısa vadeli döviz likiditesi"),
    (r"^Kısa Vadeli Dış Borç", "TCMB", "ky_dis_borc", "Kısa Vadeli Dış Borç", "Dış denge", 1,
     ["Döviz kuru", BANKS], "Kalan vadesi bir yıla kadar dış borç stoku"),
    (r"^Türkiye Dış Borç", "TCMB", "dis_borc", "Dış Borç Stoku", "Dış denge", 1,
     ["Döviz kuru", "ülke risk primi"], "Brüt dış borç stoku (çeyreklik)"),
    (r"^Uluslararası Yatırım Pozisyonu", "TCMB", "uyp", "Uluslararası Yatırım Pozisyonu", "Dış denge", 1,
     ["Döviz kuru"], "Yurt dışı varlık ve yükümlülükler"),
    (r"^Yurt Dışı Portföy Yatırım", "TCMB", "portfoy", "Yurt Dışı Portföy Yatırımları", "Dış denge", 1,
     ["BIST 100"], "Yerleşiklerin yurt dışı portföy yatırımları"),
    (r"^Reel Efektif Döviz Kuru", "TCMB", "reer", "Reel Efektif Kur", "Dış denge", 1,
     ["Döviz kuru", "ihracatçı şirketler"], "TL'nin enflasyondan arındırılmış değeri"),
    (r"^Özel Sektörün Yurtdışından Sağladığı Kredi", "TCMB", "ozel_dis_kredi", "Özel Sektör Dış Kredi Borcu", "Dış denge", 1,
     ["Döviz kuru", "borçlu şirketler"], "Özel sektörün yurt dışı kredi borcu"),
    # Para ve banka
    (r"^Menkul Kıymet İstatistikleri", "TCMB", "menkul", "Menkul Kıymet İstatistikleri (yabancı akımı)", "Para ve banka", 2,
     ["BIST 100", "TL tahviller", "döviz kuru"], "Yurt dışı yerleşiklerin hisse ve DİBS alım-satımları (haftalık)"),
    (r"^Haftalık Para ve Banka", "TCMB", "para_banka_h", "Para ve Banka İstatistikleri", "Para ve banka", 1,
     [BANKS], "Mevduat, kredi ve para arzı (haftalık)"),
    (r"^Aylık Para ve Banka", "TCMB", "para_banka_a", "Aylık Para ve Banka İstatistikleri", "Para ve banka", 1,
     [BANKS], "Parasal büyüklükler (aylık)"),
    (r"^Mevduat Faiz Oranları", "TCMB", "mevduat_faiz", "Mevduat Faiz Oranları", "Para ve banka", 1,
     [BANKS, "net faiz marjı"], "Bankaların açtığı mevduatların ağırlıklı ortalama faizi"),
    (r"^Kredi Faiz Oranları", "TCMB", "kredi_faiz", "Kredi Faiz Oranları", "Para ve banka", 1,
     [BANKS, "net faiz marjı"], "Bankaların kullandırdığı kredilerin ağırlıklı ortalama faizi"),
    (r"^Zorunlu Karşılığa Tabi", "TCMB", "zk", "Zorunlu Karşılığa Tabi Mevduat", "Para ve banka", 1,
     [BANKS], "Zorunlu karşılığa tabi mevduat ve katılım fonları"),
    (r"^Konut Fiyat Endeksi", "TCMB", "kfe", "Konut Fiyat Endeksi", "Konut ve inşaat", 2,
     ["GYO'lar (EKGYO)", "konut geliştiriciler"], "Konut fiyatlarının aylık ve yıllık değişimi"),
    (r"^Finansal Hesaplar", "TCMB", "fin_hesap", "Finansal Hesaplar", "Para ve banka", 1,
     [BANKS], "Sektörlerin finansal varlık ve yükümlülükleri (çeyreklik)"),
    (r"^Bankacılık Sektörü (Bilanço Bilgileri|Kar-Zarar|Sermaye Yeterliliği|Likidite|KOBİ|Kredi Dağılımı|Sektörel|Menkul Değerler Cüzdanı)",
     "BDDK", "bddk_aylik", "BDDK Aylık Bankacılık Verileri", "Para ve banka", 2,
     [BANKS, "sektör kârlılığı ve sermaye yeterliliği"], "Sektörün aylık kâr-zarar, bilanço, likidite ve sermaye yeterliliği tabloları"),
    (r"^Bankacılık Sektörü .*\(Fonksiyon ve Sahiplik", "BDDK", "bddk", "BDDK Haftalık Bülten", "Para ve banka", 1,
     [BANKS], "Sektörün kredi, mevduat, takipteki alacak ve kâr tabloları"),
    (r"^(Kredi Kartı Harcamalarına|Tüketici Kredilerine)", "BDDK", "bddk_tuketici", "BDDK Tüketici Kredisi ve Kart Verileri", "Para ve banka", 1,
     [BANKS, "perakende"], "Tüketici kredileri ve kredi kartı harcamaları"),
    (r"^(Faktoring|Finansal Kiralama|Finansman) Şirketlerine Ait", "BDDK", "bddk_bdfk", "Faktoring, Leasing ve Finansman Şirketleri", "Para ve banka", 1,
     ["Leasing ve faktoring şirketleri"], "Banka dışı finans kuruluşlarının bilanço ve kâr tabloları"),
    (r"^(Prim Üretimi|Sigorta, Reasürans ve Emeklilik Şirketlerinin Mali)", None, "sigorta", "Sigorta Sektörü Verileri", "Sektör verisi", 1,
     ["Sigorta şirketleri (AKGRT, ANSGR, TURSG, ANHYT, AGESA)"], "Prim üretimi ve sigorta şirketlerinin mali tabloları"),
    (r"^Halka Açık Şirket İstatistikleri \(Birinci el", "SPK", "spk_aylik", "SPK Sermaye Piyasası İstatistikleri", "Para ve banka", 1,
     ["Aracı kurumlar"], "Halka arzlar, ihraçlar ve ikincil piyasa işlemleri (aylık)"),
    # Kamu maliyesi
    (r"^Merkezi Yönetim Bütçe Denge", "HMB", "butce", "Merkezi Yönetim Bütçesi", "Kamu maliyesi", 2,
     ["TL tahvil faizleri", "ülke risk primi"], "Bütçe gelir, gider ve dengesi"),
    (r"^Hazine Nakit Gerçekleşmeleri", "HMB", "hazine_nakit", "Hazine Nakit Dengesi", "Kamu maliyesi", 1,
     ["TL tahvil faizleri"], "Hazinenin nakit bazlı gelir ve giderleri"),
    (r"^Merkezi Yönetim (İç|Dış) Borç İstatistikleri|^Merkezi Yönetim Borç Stoku", "HMB", "borc", "Hazine Borç İstatistikleri", "Kamu maliyesi", 1,
     ["TL tahvil faizleri"], "Borç stoku, iç borç çevirme oranı, borçlanma vadesi ve maliyeti"),
    (r"^Kamu Net Borç Stoku", "HMB", "net_borc", "Kamu Net Borç Stoku", "Kamu maliyesi", 1,
     ["Ülke risk primi"], "Kamunun net borç stoku (çeyreklik)"),
    (r"^Avrupa Birliği Tanımlı Genel Yönetim Borç", "HMB", "ab_borc", "AB Tanımlı Borç Stoku", "Kamu maliyesi", 1,
     ["Ülke risk primi"], "Genel yönetim borç stoku / GSYH"),
    # Sektör verileri
    (r"^Konut (ve İş Yeri )?Satış İstatistikleri", "TÜİK", "konut", "Konut Satışları", "Konut ve inşaat", 2,
     ["GYO'lar (EKGYO)", "konut kredisi veren bankalar"], "Toplam, ilk el ve ipotekli konut satışları"),
    (r"^Havalimanı İstatistikleri", "UAB", "havalimani", "Havalimanı Yolcu İstatistikleri", "Sektör verisi", 1,
     ["Havacılık (THYAO, PGSUS, TAVHL)"], "DHMİ yolcu, uçak ve yük trafiği"),
    (r"^Giriş-Çıkış Yapan Yabancı", "KTB", "turist", "Turist Girişleri", "Sektör verisi", 1,
     ["Turizm ve havacılık (THYAO, PGSUS, TAVHL)"], "Yabancı ziyaretçi sayısı"),
    (r"^Turizm İstatistikleri", "TÜİK", "turizm", "Turizm Gelirleri", "Sektör verisi", 1,
     ["Turizm ve havacılık", "cari denge"], "Çeyreklik turizm geliri ve ziyaretçi sayısı"),
    (r"^Elektrik Enerjisi Üretim-İletim", "ETKB", "elektrik", "Elektrik Üretim ve Tüketimi", "Sektör verisi", 1,
     ["Elektrik üreticileri (ENJSA, AKSEN, ZOREN)"], "Kaynaklara göre elektrik üretimi"),
    (r"^(Elektrik|Doğal Gaz|Petrol) Piyasası Aylık Sektör Raporu", "EPDK", "epdk", "EPDK Enerji Piyasası Raporları", "Sektör verisi", 1,
     ["Enerji şirketleri (TUPRS, AYGAZ, ENJSA)"], "Elektrik, doğal gaz ve akaryakıt satışları"),
    (r"^Kurulan ve Kapanan Şirketler", "TOBB", "sirket_kurulus", "Kurulan ve Kapanan Şirketler", "Büyüme ve üretim", 1,
     ["İş döngüsü"], "Aylık şirket kuruluş ve kapanışları"),
    # Her iş günü (ızgaraya girmez)
    (r"^Gösterge Niteliğindeki Merkez Bankası Kurları", "TCMB", "kur", "TCMB gösterge kurları", "Günlük", 0, [], ""),
    (r"^TCMB Analitik Bilanço", "TCMB", "analitik", "TCMB analitik bilanço", "Günlük", 0, [], ""),
    (r"^Merkez Bankası Bünyesindeki Bankalararası Para", "TCMB", "bpp", "Bankalararası para piyasası", "Günlük", 0, [], ""),
    (r"^(Perakende Ödeme Sistemi|Elektronik Fon Transfer)", "TCMB", "odeme_sis", "Ödeme sistemleri (PÖS, EFT)", "Günlük", 0, [], ""),
    (r"^Menkul Kıymet Yatırım Fonlarına/Emeklilik Yatırım Fonlarına/Yatırım Ortaklıklarına İlişkin Günlük", "SPK", "spk_fon", "SPK fon istatistikleri", "Günlük", 0, [], ""),
]
_RX = [(re.compile(p, re.I), kurum, key, short, grp, imp, assets, desc) for p, kurum, key, short, grp, imp, assets, desc in RULES]
FREQ = {"H": "haftalık", "A": "aylık", "Ç": "çeyreklik", "Y": "yıllık"}


def classify(name: str, kurum: str) -> dict | None:
    n = re.sub(r"\s+", " ", (name or "")).strip()
    for rx, k, key, short, grp, imp, assets, desc in _RX:
        if (k is None or (kurum or "").startswith(k)) and rx.search(n):
            return {"key": key, "short": short, "group": grp, "importance": imp, "assets": assets, "desc": desc}
    return None


def compact(payload: dict) -> list[dict]:
    """API yanıtı (yayında olan + olmayan listeleri) → sade satırlar, id'ye göre tekil."""
    out, seen = [], set()
    for lst in ("yayindaOlanlarList", "yayindaOlmayanlarList"):
        for r in payload.get(lst) or []:
            # henüz yayımlanmamış TÜİK bültenlerinin id'si 0 gelir → içerikle tekilleştir
            rid = r.get("id") or (r.get("sorumluKisaAd"), r.get("adi"), r.get("gTarih"), r.get("donemi"))
            if rid in seen or not r.get("gTarih") or not r.get("adi"):
                continue
            seen.add(rid)
            out.append({"id": r.get("id") or 0, "k": (r.get("sorumluKisaAd") or "").strip(), "kurum": (r.get("sorumluKurum") or "").strip(),
                        "adi": re.sub(r"\s+", " ", r["adi"]).strip(), "t": r["gTarih"][:16], "d": (r.get("donemi") or "").strip(),
                        "link": (r.get("link") or "").strip()})
    return out


def fetch_year(y: int) -> list[dict] | None:
    r = http.get(URL.format(y=y), headers={"Accept": "application/json", "Referer": PAGE}, timeout=120)
    if r is None:
        return None
    try:
        return compact(r.json())
    except ValueError:
        log.warning("TÜİK veri takvimi %s JSON dönmedi", y)
        return None


def _years(today: date) -> list[int]:
    ys = [today.year]
    if today.month >= 10:
        ys.append(today.year + 1)                 # yeni yıl takvimi Ekim–Aralık'ta açıklanır
    if today.month == 1:
        ys.insert(0, today.year - 1)
    return ys


def load_rows(force: bool = False) -> tuple[list[dict], dict]:
    """Önbellekli satırlar. REFRESH_H saatten eskiyse yeniden çeker; çekemezse önbelleği kullanır."""
    cache = {}
    if RAW_FILE.exists():
        try:
            cache = json.loads(RAW_FILE.read_text(encoding="utf-8"))
        except ValueError:
            cache = {}
    now = now_utc()
    fetched = cache.get("fetched")
    stale = force or not fetched or (now - datetime.fromisoformat(fetched.replace("Z", "+00:00"))) > timedelta(hours=REFRESH_H)
    years = cache.get("years") or {}
    status = {"ok": True, "fetched": fetched, "cached": True}
    if stale:
        got = 0
        for y in _years(now.astimezone(IST).date()):
            rows = fetch_year(y)
            if rows is not None and (rows or str(y) not in years):
                years[str(y)] = rows
                got += 1
        if got:
            cache = {"fetched": iso(now), "years": years}
            RAW_FILE.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            status = {"ok": True, "fetched": cache["fetched"], "cached": False}
        else:
            status = {"ok": bool(years), "fetched": fetched, "cached": True, "error": "TÜİK veri takvimi çekilemedi"}
    rows = [r for y in sorted(years) for r in years[y]]
    status["rows"] = len(rows)
    return rows, status


def _freq(rows: list[dict]) -> dict[str, str]:
    """Anahtar başına yayın sıklığı: yıl içindeki farklı yayın günü sayısından."""
    days = defaultdict(set)
    for r in rows:
        c = classify(r["adi"], r["k"])
        if c:
            days[(c["key"], r["t"][:4])].add(r["t"][:10])
    out = {}
    for (key, _), ds in days.items():
        n = len(ds)
        f = "H" if n >= 40 else "A" if n >= 9 else "Ç" if n >= 3 else "Y"
        out[key] = max(out.get(key, "Y"), f, key=lambda x: "YÇAH".index(x))
    return out


def events(rows: list[dict], lo: str, hi: str) -> tuple[list[dict], list[dict]]:
    """Takvim olayları (calendar_events biçimi) ve her iş günü yayımlanan seriler."""
    freq = _freq(rows)
    groups: dict[tuple, dict] = {}
    daily: dict[str, dict] = {}
    for r in rows:
        day = r["t"][:10]
        c = classify(r["adi"], r["k"])
        if not c:
            continue
        if c["importance"] == 0:
            d = daily.setdefault(c["key"], {"name": c["short"], "inst": r["k"], "time": r["t"][11:16], "url": r["link"]})
            d["time"] = min(d["time"], r["t"][11:16])
            continue
        if not (lo <= day <= hi):
            continue
        g = groups.setdefault((c["key"], r["t"]), {"c": c, "rows": []})
        g["rows"].append(r)
    out = []
    for (key, t), g in groups.items():
        c, rs = g["c"], g["rows"]
        d = date.fromisoformat(t[:10])
        when = datetime.fromisoformat(t).replace(tzinfo=IST).isoformat(timespec="minutes")
        periods = list(dict.fromkeys(r["d"] for r in rs if r["d"] and not re.fullmatch(r"[\d/.-]+", r["d"])))
        title = c["short"] + (f" · {periods[0]}" if len(periods) == 1 else "")
        parts = [c["desc"]] if c["desc"] else []
        if len(rs) > 1:
            parts.append(f"{len(rs)} tablo")
        f = freq.get(key)
        ev = {"kind": "macro" if c["importance"] >= 2 else "data", "date": d.isoformat(), "when": when, "timed": True,
              "market": "BIST", "title": title, "detail": " · ".join(parts), "importance": c["importance"],
              "url": next((r["link"] for r in rs if r["link"]), PAGE), "src": "uvyt", "key": key,
              "group": c["group"], "inst": rs[0]["k"], "assets": c["assets"], "period": ", ".join(periods),
              "freq": FREQ.get(f, ""), "items": sorted({r["adi"] for r in rs})[:8]}
        ev["id"] = "|".join(str(ev.get(x, "")) for x in ("kind", "date", "ticker", "title"))
        out.append(ev)
    out.sort(key=lambda e: (e["when"], -e["importance"], e["title"]))
    dl = sorted(daily.values(), key=lambda x: (x["time"], x["name"]))
    return out, dl


# ------------------------------------------------------------------ son açıklanan değer (EVDS)
# anahtar → (seri, etiket, biçim). biçim: "mom_yoy" aylık+yıllık % (endeks), "yoy" yıllık %, "level" düzey,
# "musd" milyon $ → okunur, "kusd" bin $ → milyar $
LAST_SERIES: dict[str, list[tuple[str, str, str]]] = {
    "tufe": [("TP.TUKFIY2025.GENEL", "TÜFE", "mom_yoy")],
    "ufe": [("TP.TUFE1YI.T1", "Yİ-ÜFE", "mom_yoy")],
    "kko": [("TP.KKO.MA", "KKO (mevsimsellikten arındırılmış)", "level")],
    "rkge": [("TP.GY1.N2.MA", "Reel kesim güven (MA)", "level")],
    "tge": [("TP.TG2.Y01", "Tüketici güven", "level")],
    "kfe": [("TP.KFE.TR", "Konut fiyat endeksi", "yoy")],
    "dis_ticaret": [("TP.IHRACATBEC.9999", "İhracat", "kusd"), ("TP.ITHALATBEC.9999", "İthalat", "kusd")],
    "menkul": [("TP.MKNETHAR.M7", "Yabancıların hisse net alımı", "musd")],
    "rezerv": [("TP.AB.TOPLAM", "TCMB brüt rezervi", "musd")],
}
WEEKLY = {"menkul", "rezerv"}
LAST_FILE = DATA / "tr_calendar_last.json"
AY = ["", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


def _tr(x: float, nd: int = 1) -> str:
    return f"{x:,.{nd}f}".replace(",", "§").replace(".", ",").replace("§", ".")


def _period(d: str) -> str:
    """EVDS tarihleri: aylık '2026-9', haftalık/günlük '02-10-2026'."""
    p = d.split("-")
    if len(p) == 2:
        return f"{AY[int(p[1])]} {p[0]}"
    if len(p) == 3:
        return f"{int(p[0])} {AY[int(p[1])]} {p[2]}"
    return d


def describe(fmt_: str, label: str, pts: list[tuple[str, float]]) -> str | None:
    if not pts:
        return None
    d, v = pts[-1]
    per = _period(d)
    if fmt_ in ("mom_yoy", "yoy"):
        txt = []
        if fmt_ == "mom_yoy" and len(pts) >= 2 and pts[-2][1]:
            txt.append(f"aylık %{_tr((v / pts[-2][1] - 1) * 100)}")
        if len(pts) >= 13 and pts[-13][1]:
            txt.append(f"yıllık %{_tr((v / pts[-13][1] - 1) * 100)}")
        return f"{label} ({per}): {', '.join(txt)}" if txt else None
    if fmt_ == "musd":
        return f"{label} ({per}): {_tr(v / 1000, 1)} milyar $" if abs(v) >= 1000 else f"{label} ({per}): {_tr(v, 1)} milyon $"
    if fmt_ == "kusd":
        return f"{label} ({per}): {_tr(v / 1e6, 1)} milyar $"
    return f"{label} ({per}): {_tr(v, 1)}"


def last_values(key: str | None, refresh_h: int = 12) -> dict[str, str]:
    """Olay anahtarı → son açıklanan değer metni. EVDS anahtarı yoksa ya da çekilemezse önbellek."""
    cache = {}
    if LAST_FILE.exists():
        try:
            cache = json.loads(LAST_FILE.read_text(encoding="utf-8"))
        except ValueError:
            cache = {}
    now = now_utc()
    f = cache.get("fetched")
    if not key or (f and now - datetime.fromisoformat(f.replace("Z", "+00:00")) < timedelta(hours=refresh_h)):
        return cache.get("values") or {}
    from .sources.tcmb import evds_url, _num
    items = []
    for weekly in (False, True):                            # aylık ve haftalık seriler ayrı istekte (frekans karışmasın)
        codes = [c for k, specs in LAST_SERIES.items() for c, _, _ in specs if (k in WEEKLY) == weekly]
        r = http.get(evds_url(codes, now - timedelta(days=430), now), headers={"key": key}, timeout=60)
        try:
            items += (r.json().get("items") or []) if r is not None else []
        except ValueError:
            pass
    if not items:
        return cache.get("values") or {}
    out = {}
    for k, specs in LAST_SERIES.items():
        parts = []
        for code, label, fm in specs:
            col = code.replace(".", "_")
            pts = [(i.get("Tarih"), _num(i.get(col))) for i in items]
            pts = [(d, v) for d, v in pts if d and v is not None]
            s = describe(fm, label, pts)
            if s:
                parts.append(s)
        if parts:
            out[k] = " · ".join(parts)
    LAST_FILE.write_text(json.dumps({"fetched": iso(now), "values": out}, ensure_ascii=False), encoding="utf-8")
    return out
