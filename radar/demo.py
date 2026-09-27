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
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "feed.json").write_text(json.dumps({
        "generated": iso(now_utc()), "demo": True,
        "sources": [{"name": n, "ok": True, "count": 0} for n in
                    ("KAP", "SEC EDGAR", "Google News", "Yahoo Finance", "TR haber RSS",
                     "Reddit", "StockTwits", "X", "Rapor kutusu")],
        "watchlist": [{"symbol": s.symbol, "name": s.name, "market": s.market} for s in stocks.values()],
        "ai": {"model": "demo", "enabled": False, "used": 0},
        "items": items,
    }, ensure_ascii=False), encoding="utf-8")
    print(f"Örnek veri yazıldı: {len(items)} kayıt → {DATA}")
