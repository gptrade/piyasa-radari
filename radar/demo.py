"""İnternet ve API anahtarı olmadan paneli denemek için örnek veri üretir.

Kayıtlar açıkça "ÖRNEK" olarak işaretlenir; ilk gerçek çalıştırmada üzerine yazılır.
"""
from __future__ import annotations

import json
import math
import random
from datetime import timedelta

from .config import DATA, load_watchlist
from .models import Item, iso, now_utc
from .prices import PRICE_DIR, reaction

SAMPLES = [
    ("VAKBN", "KAP", "disclosure", "VAKBN: Özel Durum Açıklaması (Genel)",
     "Banka, yurt dışı piyasalarda sendikasyon kredisi yenilemesini tamamladığını bildirdi.",
     ("bullish", 74, "medium", "days", "fonlama"),
     "Sendikasyon yenilemesi fonlama tarafında belirsizliği azaltıyor."),
    ("TTKOM", "Bloomberg HT", "news", "Türk Telekom yeni fiber yatırım planını açıkladı",
     "Şirket altyapı yatırımlarını hızlandıracağını duyurdu; capex rehberliği yükseltildi.",
     ("neutral", 55, "medium", "weeks", "yatırım planı"),
     "Uzun vadede olumlu, kısa vadede serbest nakit akışına baskı yaratabilir."),
    ("GLRMK", "KAP", "disclosure", "GLRMK: Yeni İş İlişkisi",
     "Şirket yurt dışında raylı sistem projesi için sözleşme imzaladı.",
     ("bullish", 81, "high", "days", "ihale"),
     "Yeni sözleşme iş birikimini artırıyor; tutar piyasa değerine oranla anlamlı."),
    ("NVDA", "SEC EDGAR", "disclosure", "8-K - Current report",
     "Item 1.01 Entry into a Material Definitive Agreement.",
     ("bullish", 68, "medium", "days", "sözleşme"),
     "Maddi sözleşme bildirimi talep görünürlüğünü destekliyor; ayrıntılar sınırlı."),
    ("TSLA", "Yahoo Finance", "news", "Tesla trims near-term delivery outlook",
     "Management points to planned downtime for factory upgrades.",
     ("bearish", 72, "high", "days", "rehberlik"),
     "Kısa vadeli teslimat beklentisi düşüyor; planlı duruş kısmen açıklayıcı."),
    ("AAPL", "Reddit", "social", "$AAPL buyback thread: is the new authorization priced in?",
     "Discussion about the size of the repurchase program.",
     ("neutral", 40, "low", "days", "söylenti"),
     "Sosyal medya tartışması; yeni bilgi içermiyor."),
]


def _fake_prices(symbol: str, market: str, trend: float) -> dict:
    rnd = random.Random(symbol)
    now = now_utc().replace(second=0, microsecond=0)
    base = rnd.uniform(20, 250)
    intraday, daily = [], []
    p = base
    for i in range(120, 0, -1):
        p *= 1 + rnd.gauss(0, 0.012)
        daily.append([int((now - timedelta(days=i)).timestamp()), round(p, 2)])
    for i in range(78 * 3, 0, -1):
        p *= 1 + rnd.gauss(trend / 2000, 0.0025) + 0.0004 * math.sin(i / 7)
        intraday.append([int((now - timedelta(minutes=5 * i)).timestamp()), round(p, 2)])
    daily.append([int(now.timestamp()), intraday[-1][1]])
    prev = daily[-2][1]
    return {"symbol": symbol, "yahoo": symbol, "market": market,
            "currency": "TRY" if market == "BIST" else "USD", "last": intraday[-1][1],
            "prev_close": prev, "change_pct": round((intraday[-1][1] / prev - 1) * 100, 2),
            "intraday": intraday, "daily": daily, "updated": iso(now), "demo": True}


def write_demo() -> None:
    stocks = {s.symbol: s for s in load_watchlist()}
    PRICE_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for n, (tk, src, typ, title, body, (sent, conf, mat, hor, cat), summ) in enumerate(SAMPLES):
        st = stocks.get(tk)
        market = st.market if st else ("BIST" if src in ("KAP", "Bloomberg HT") else "US")
        px = _fake_prices(tk, market, {"bullish": 1, "bearish": -1}.get(sent, 0))
        (PRICE_DIR / f"{tk}.json").write_text(json.dumps(px))
        it = Item(source=src, source_type=typ, market=market, title=title, summary=body,
                  url="", published=iso(now_utc() - timedelta(minutes=35 + 55 * n)),
                  tickers=[tk], lang="tr" if market == "BIST" else "en", extra={"demo": True})
        it.analysis = {"sentiment": sent, "confidence": conf, "materiality": mat, "horizon": hor,
                       "category": cat, "headline_tr": title, "summary": summ,
                       "key_points": ["Örnek değerlendirme — gerçek veri değil"],
                       "risks": ["Bu kayıt panel önizlemesi içindir"],
                       "affected_tickers": [tk], "model": "demo"}
        it.reaction = reaction(it.published, px)
        items.append(it.to_dict())
    # Yeni kaynak türleri: Borsa İstanbul tedbiri, SPK bülteni, TCMB PPK, basın bülteni
    def extra_item(minutes, analysis=None, **kw):
        it = Item(url="", published=iso(now_utc() - timedelta(minutes=minutes)), **kw)
        it.extra["demo"] = True
        if analysis:
            it.analysis = {"key_points": ["Örnek değerlendirme — gerçek veri değil"],
                           "risks": ["Bu kayıt panel önizlemesi içindir"], "model": "demo", **analysis}
        return it
    glr = json.loads((PRICE_DIR / "GLRMK.json").read_text())
    extra = [
        extra_item(12, source="Borsa İstanbul · KAP", source_type="disclosure", market="BIST",
                   title="GLRMK: Brüt takas", summary="Brüt Takas", tickers=["GLRMK"], lang="tr",
                   extra={"bist_measure": "Brüt takas"},
                   analysis={"sentiment": "bearish", "confidence": 78, "materiality": "high",
                             "horizon": "days", "category": "BIST tedbiri", "affected_tickers": ["GLRMK"],
                             "headline_tr": "GLRMK için brüt takas tedbiri",
                             "summary": "Tedbir süresince günlük al-sat yapılamaz; likidite ve kısa vadeli talep düşer."}),
        extra_item(90, source="TCMB · PPK Kararları", source_type="macro", market="BIST",
                   title="Faiz Oranlarına İlişkin Basın Duyurusu", tickers=[], lang="tr",
                   summary="Para Politikası Kurulu politika faizini sabit tuttu.",
                   extra={"tcmb": "PPK Kararları", "high_impact": True},
                   analysis={"sentiment": "neutral", "confidence": 60, "materiality": "high",
                             "horizon": "weeks", "category": "para politikası",
                             "affected_tickers": ["VAKBN", "KLNMA"], "headline_tr": "PPK faizi sabit tuttu",
                             "summary": "Beklentiye paralel karar; bankaların fonlama maliyeti görünümü değişmedi."}),
        extra_item(300, source="SPK Bülteni", source_type="regulator", market="BIST",
                   title="SPK Bülteni 2026/66 — VAKBN", tickers=["VAKBN"], lang="tr",
                   summary="İzleme listesindeki şirketler geçiyor: VAKBN",
                   extra={"bulletin": "2026/66"},
                   analysis={"sentiment": "bullish", "confidence": 66, "materiality": "medium",
                             "horizon": "weeks", "category": "borçlanma aracı ihracı",
                             "affected_tickers": ["VAKBN"], "headline_tr": "VakıfBank ihraç tavanı onaylandı",
                             "summary": "Borçlanma aracı ihraç belgesi onayı fonlama esnekliğini artırıyor."}),
        extra_item(420, source="GlobeNewswire", source_type="news", market="US",
                   title="NVIDIA announces new data center partnership (NASDAQ: NVDA)", tickers=["NVDA"],
                   lang="en", summary="Press release describing a multi-year agreement.",
                   extra={"press_release": True},
                   analysis={"sentiment": "bullish", "confidence": 62, "materiality": "medium",
                             "horizon": "days", "category": "basın bülteni", "affected_tickers": ["NVDA"],
                             "headline_tr": "NVIDIA yeni veri merkezi ortaklığı duyurdu",
                             "summary": "Şirket açıklaması; tutar verilmediği için etki sınırlı olabilir."}),
    ]
    extra[0].reaction = reaction(extra[0].published, glr)
    items = sorted(items + [e.to_dict() for e in extra], key=lambda d: d["published"], reverse=True)

    (DATA / "macro.json").write_text(json.dumps({"updated": iso(now_utc()), "demo": True, "series": [
        {"code": "TP.DK.USD.A.YTL", "name": "USD/TRY", "unit": "", "date": "29-09-2026", "last": 41.3, "prev": 41.18, "change": 0.12},
        {"code": "TP.DK.EUR.A.YTL", "name": "EUR/TRY", "unit": "", "date": "29-09-2026", "last": 48.21, "prev": 48.35, "change": -0.14},
        {"code": "TP.APIFON4", "name": "TCMB ağırlıklı fonlama maliyeti", "unit": "%", "date": "29-09-2026", "last": 40.5, "prev": 40.5, "change": 0.0},
    ]}, ensure_ascii=False))

    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "feed.json").write_text(json.dumps({
        "generated": iso(now_utc()), "demo": True,
        "sources": [{"name": n, "ok": True, "count": 0} for n in
                    ("KAP + Borsa İstanbul", "SPK Bülteni", "TCMB", "SEC EDGAR", "Google News",
                     "Yahoo Finance", "Basın bültenleri", "TR haber RSS", "Reddit", "StockTwits",
                     "X", "Rapor kutusu", "TCMB EVDS")],
        "watchlist": [{"symbol": s.symbol, "name": s.name, "market": s.market} for s in stocks.values()],
        "ai": {"model": "demo", "enabled": False, "used": 0},
        "items": items,
    }, ensure_ascii=False), encoding="utf-8")
    print(f"Örnek veri yazıldı: {len(items)} kayıt → {DATA}")
