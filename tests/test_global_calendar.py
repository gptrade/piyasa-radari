"""Küresel takvim: Alpha Vantage ABD bilançoları, ECB toplantıları, Eurostat, bölge etiketleri."""
import json
from datetime import datetime, timezone
from pathlib import Path

from radar import calendar_events, global_calendar as gc

FIX = Path(__file__).parent / "fixtures" / "cal2"
AV = """symbol,name,reportDate,fiscalDateEnding,estimate,currency,timeOfTheDay
AAPL,APPLE INCORPORATED,2026-11-02,2026-09-30,1.98,USD,post-market
MMM,3M,2026-10-20,2026-09-30,1.95,USD,pre-market
ZZZZ,TINY CORP,2026-10-20,2026-09-30,,USD,
BRK-B,BERKSHIRE HATHAWAY,2026-11-01,2026-09-30,,USD,
"""


def test_parse_av_keeps_sp500_and_watchlist():
    keep = set(gc.load_sp500()) | {"ZZZZ"}
    rows = {r["s"]: r for r in gc.parse_av(AV, keep)}
    assert set(rows) == {"AAPL", "MMM", "ZZZZ", "BRK.B"}
    assert rows["AAPL"]["t"] == "amc" and rows["MMM"]["t"] == "bmo" and rows["AAPL"]["e"] == 1.98
    assert rows["ZZZZ"]["e"] is None
    assert "ZZZZ" not in {r["s"] for r in gc.parse_av(AV, set(gc.load_sp500()))}


def test_parse_ecb_decision_days():
    days = gc.parse_ecb((FIX / "ecb_meetings.html").read_text(encoding="utf-8"))
    assert "2026-10-29" in days and "2026-12-17" in days
    assert "2026-10-28" not in days and "2026-11-25" not in days       # 1. gün ve para politikası dışı toplantı


def test_parse_eurostat_rules():
    rows = gc.parse_eurostat(json.loads((FIX / "eurostat_ev.json").read_text(encoding="utf-8")))
    by = {(r["short"], r["d"]) for r in rows}
    assert ("Euro Bölgesi enflasyon (öncü)", "2026-11-04") in by
    assert all(r["short"] != "Interest rates (3 months)" for r in rows)  # eşlenmeyenler düşer
    flash = next(r for r in rows if r["short"].startswith("Euro Bölgesi enflasyon (öncü)"))
    assert flash["imp"] == 3 and flash["hm"] == "11:00"


def test_events_regions_and_importance():
    cache = {"us": {"rows": gc.parse_av(AV, set(gc.load_sp500()))},
             "eu": {"rows": [{"s": "SAP.DE", "n": "SAP", "c": "DE", "big": True, "d": "2026-10-21", "e": 2.1},
                             {"s": "BMW.DE", "n": "BMW", "c": "DE", "big": False, "d": "2026-11-05", "e": None}]},
             "ecb": {"rows": ["2026-10-29"]},
             "eurostat": {"rows": gc.parse_eurostat(json.loads((FIX / "eurostat_ev.json").read_text(encoding="utf-8")))}}
    evs = gc.events(cache, "2026-10-14", "2026-12-31", watch_us=set())
    by = {(e["kind"], e.get("ticker") or e["title"]): e for e in evs}
    aapl, mmm = by[("earnings", "AAPL")], by[("earnings", "MMM")]
    assert aapl["importance"] == 3 and aapl["region"] == "US" and "kapanışı sonrası" in aapl["detail"]
    assert mmm["importance"] == 1 and mmm["group"] == "S&P 500"
    assert by[("earnings", "SAP.DE")]["importance"] == 3 and by[("earnings", "BMW.DE")]["importance"] == 2
    ecb = by[("cb", "ECB faiz kararı")]
    assert ecb["region"] == "EU" and ecb["when"] == "2026-10-29T16:15+03:00"     # 14:15 CET = 16:15 İstanbul
    infl = next(e for e in evs if e.get("src") == "eurostat" and e["title"].startswith("Euro Bölgesi enflasyon (öncü)"))
    assert infl["when"] == "2026-11-04T13:00+03:00" and infl["kind"] == "macro"
    assert all(e["region"] == "EU" for e in evs if e.get("src") in ("ecb", "eurostat", "yahoo"))


def test_build_tags_regions_and_dedupes_watchlist(monkeypatch):
    class St:
        symbol, market, yahoo = "AAPL", "US", "AAPL"
    px = {"AAPL": {"next_earnings": {"date": "2026-11-02", "eps_est": 1.98}}}
    world = gc.events({"us": {"rows": gc.parse_av(AV, set(gc.load_sp500()))}}, "2026-10-01", "2026-12-31", {"AAPL"})
    monkeypatch.setattr(calendar_events, "now_utc", lambda: datetime(2026, 10, 15, 9, tzinfo=timezone.utc))
    conf = {"events": [{"name": "TCMB faiz kararı (PPK)", "market": "BIST", "kind": "cb", "importance": 3,
                        "time": "14:00", "dates": ["2026-10-22"]}]}
    cal = calendar_events.build([St()], px, conf=conf, world=world)
    aapl = [e for e in cal["events"] if e.get("ticker") == "AAPL" and e["kind"] == "earnings"]
    assert len(aapl) == 1 and aapl[0].get("src") != "av"                    # izleme listesindeki Yahoo kaydı kalır
    regions = {e["title"]: e["region"] for e in cal["events"]}
    assert regions["TCMB faiz kararı (PPK)"] == "TR" and regions["MMM bilanço"] == "US"


def test_refresh_uses_cache_on_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "CACHE", tmp_path / "g.json")
    monkeypatch.setattr(gc, "fetch_us", lambda w: [{"s": "AAPL", "n": "A", "d": "2026-11-02", "t": "amc", "e": 1.0}])
    monkeypatch.setattr(gc, "fetch_eu", lambda: None)
    monkeypatch.setattr(gc, "fetch_ecb", lambda: ["2026-10-29"])
    monkeypatch.setattr(gc, "fetch_boe", lambda: None)
    monkeypatch.setattr(gc, "fetch_boj", lambda: None)
    monkeypatch.setattr(gc, "fetch_eurostat", lambda lo, hi: [])
    cache, st = gc.refresh(set(), force=True)
    assert st["us"]["n"] == 1 and st["ecb"]["ok"] and not st["eu"]["ok"]
    monkeypatch.setattr(gc, "fetch_us", lambda w: None)
    cache2, st2 = gc.refresh(set(), force=True)
    assert st2["us"]["ok"] and st2["us"]["cached"] and cache2["us"]["rows"][0]["s"] == "AAPL"


def test_empty_result_is_retried_later(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "CACHE", tmp_path / "g.json")
    for k in ("fetch_us", "fetch_ecb", "fetch_boe", "fetch_boj"):
        monkeypatch.setattr(gc, k, lambda *a: None)
    monkeypatch.setattr(gc, "fetch_eurostat", lambda lo, hi: None)
    calls = []
    monkeypatch.setattr(gc, "fetch_eu", lambda: calls.append(1) or None)
    _, st = gc.refresh(set())
    assert not st["eu"]["ok"] and len(calls) == 1
    _, st = gc.refresh(set())                                   # 2 saat dolmadan yeniden denenmez
    assert len(calls) == 1 and "yeniden" in st["eu"]["error"]
    monkeypatch.setattr(gc, "fetch_eu", lambda: [{"s": "SAP.DE", "n": "SAP", "c": "DE", "big": True, "d": "2026-10-21", "e": 1.8}])
    _, st = gc.refresh(set(), force=True)
    assert st["eu"]["n"] == 1


def test_boe_boj_parse_and_events():
    boe = gc.parse_boe((FIX / "boe_mpc.html").read_text(encoding="utf-8"))
    boj = gc.parse_boj((FIX / "boj_mpm.html").read_text(encoding="utf-8"))
    assert {"d": "2026-11-05", "mpr": True} in boe and {"d": "2026-12-17", "mpr": False} in boe and len(boe) == 16
    assert {"d": "2026-10-30", "outlook": True} in boj and {"d": "2027-03-18", "outlook": False} in boj   # 2. gün
    evs = gc.events({"boe": {"rows": boe}, "boj": {"rows": boj}}, "2026-10-14", "2026-12-31", watch_us=set())
    b = next(e for e in evs if e["src"] == "boe")
    assert b["date"] == "2026-11-05" and b["when"] == "2026-11-05T15:00+03:00" and b["region"] == "UK" and b["market"] == "ALL"
    j = next(e for e in evs if e["src"] == "boj")
    assert j["date"] == "2026-10-30" and j["when"] == "2026-10-30T06:00+03:00" and j["region"] == "JP" and "Görünüm" in j["detail"]
