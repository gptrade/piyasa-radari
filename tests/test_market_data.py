import math
from datetime import datetime, timezone

from radar import prices
from radar.enrich import classify_event, enrich, source_tier
from radar.models import iso

DAY = 86400
T0 = int(datetime(2026, 3, 2, 15, 0, tzinfo=timezone.utc).timestamp())


def bars(closes, vols=None):
    return [[T0 + i * DAY, c, (vols[i] if vols else 1000)] for i, c in enumerate(closes)]


def test_rsi_extremes_and_trend():
    up = [100 * (1.01 ** i) for i in range(80)]
    ta = prices.technicals(bars(up))
    assert ta["trend"] == "yukarı" and ta["rsi"] == 100.0 and ta["pos52"] == 100
    assert any("aşırı alım" in s for s in ta["signals"]) and any("zirve" in s for s in ta["signals"])
    down = [100 * (0.99 ** i) for i in range(80)]
    ta = prices.technicals(bars(down))
    assert ta["trend"] == "aşağı" and ta["rsi"] < 5 and ta["score"] <= 0
    assert any("aşırı satım" in x for x in ta["signals"])


def test_rsi_matches_reference_value():
    # Wilder'ın klasik örneği (14 dönem) ≈ 70.5 civarı
    closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03,
              45.61, 46.28, 46.28]
    assert math.isclose(prices._rsi(closes), 70.46, abs_tol=0.1)


def test_volume_ratio_and_short_history():
    closes = [100 + math.sin(i / 3) for i in range(60)]
    vols = [1000] * 59 + [3500]
    ta = prices.technicals(bars(closes, vols))
    assert ta["vol_ratio"] == 3.5 and any("Hacim" in s for s in ta["signals"])
    assert prices.technicals(bars(closes[:10])) is None
    assert prices.technicals(bars(closes, vols), live=True)["vol_ratio"] == 1.0   # yarım gün hacmi kullanılmaz


def test_reaction_volume_and_index():
    daily = bars([100] * 25 + [104, 106], [1000] * 25 + [3000, 1000])
    idx = {"daily": bars([50] * 25 + [50.5, 51])}
    news = iso(datetime.fromtimestamp(T0 + 24 * DAY + 3600 * 3, tz=timezone.utc))   # 25. günden önce, akşam
    r = prices.reaction(news, {"intraday": [], "daily": daily}, idx)
    assert r["since"] == 6.0 and r["vol_x"] == 3.0
    assert r["index_since"] == 2.0 and r["excess"] == 4.0


def test_source_tier_and_event():
    assert source_tier({"source": "KAP", "source_type": "disclosure"}) == 1
    assert source_tier({"source": "Reuters · Google News", "source_type": "news"}) == 2
    assert source_tier({"source": "Rota Borsa · Google News", "source_type": "news"}) == 3
    assert source_tier({"source": "Reddit", "source_type": "social"}) == 3
    assert classify_event({"title": "TTKOM: Payların Geri Alınmasına İlişkin Bildirim", "source_type": "disclosure"}) == "buyback"
    assert classify_event({"title": "GLRMK: Brüt takas", "extra": {"bist_measure": "Brüt takas"}}) == "measure"
    assert classify_event({"title": "Morgan Stanley raises AMD price target", "source_type": "news"}) == "analyst"
    assert classify_event({"title": "4 - Statement of changes", "extra": {"form": "4"}, "source_type": "disclosure"}) == "insider"
    assert classify_event({"title": "PPK kararı", "source_type": "macro"}) == "macro"
    d = enrich({"title": "Tesla Q3 earnings beat", "source": "Yahoo Finance", "source_type": "news"})
    assert d["event"] == "earnings" and d["tier"] == 2


def test_ema_tv_matches_tradingview_definition():
    xs = [float(i) for i in range(1, 21)]
    e = prices.ema_tv(xs, 5)
    assert e[:4] == [None] * 4 and e[4] == 3.0          # SMA ile başlar
    assert all(abs(v - (i + 1 - 2)) < 1e-9 for i, v in enumerate(e) if v is not None)   # doğrusal seride (n-1)/2 gecikme
    assert prices.ema_tv([1.0, 2.0], 5) == [None, None]


def test_ema_alignment_crosses_and_weekly():
    up = [50 * (1.004 ** i) for i in range(320)]
    ta = prices.technicals(bars(up))
    assert ta["ema_align"] == "boğa" and ta["trend"] == "yukarı" and ta["weekly_trend"] == "yukarı"
    assert all(ta["ema"][k]["above"] for k in ("14", "34", "55", "200"))
    assert ta["view"] in ("al", "güçlü al")
    # uzun düşüşten sonra sert dönüş: EMA14 EMA34'ü yukarı keser
    v = [100 * (0.995 ** i) for i in range(300)] + [100 * (0.995 ** 300) * (1.03 ** i) for i in range(12)]
    ta = prices.technicals(bars(v))
    assert prices._cross([1, 2, 3, 5], [4, 4, 4, 4]) == "up" and prices._cross([5, 4, 3], [3.5] * 3) == "down"
    assert ta["atr_pct"] is not None and ta["bb_pct"] is not None


def test_bb_quotes_recent_tickers_and_cache(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from radar import bb_quotes
    rows = [{"tickers": "DAPGM", "quantity": 5, "transaction_date": "2026-09-30"},
            {"tickers": "ESKI", "quantity": 5, "transaction_date": "2025-01-01"},
            {"tickers": "PROG", "quantity": None, "transaction_date": "2026-09-30"},
            {"tickers": "KOZAL, KOZAA", "quantity": 1, "publish_date": "29.09.2026 10:00:00"}]
    assert bb_quotes.recent_tickers(rows, today=datetime(2026, 9, 30, tzinfo=timezone.utc)) == ["DAPGM", "KOZAL"]

    monkeypatch.setattr(bb_quotes, "FILE", tmp_path / "bb.json")
    class R:
        def json(self): return rows
    monkeypatch.setattr(bb_quotes.http, "get", lambda *a, **k: R())
    calls = []
    def fake(syms):
        calls.append(syms); return {s: {"last": 1.0, "date": "2026-09-30", "change_pct": None} for s in syms}
    doc = bb_quotes.update({}, fetcher=fake)
    assert set(doc["quotes"]) >= {"DAPGM"} and len(calls) == 1
    bb_quotes.update({}, fetcher=fake)                       # saat dolmadan yeniden çekmez
    assert len(calls) == 1
