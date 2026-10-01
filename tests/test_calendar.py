from datetime import date, datetime
from zoneinfo import ZoneInfo

from radar import calendar_events as ce
from radar.config import Stock


def test_expiry_rules():
    evs = ce.expiry_events(date(2026, 10, 1), date(2026, 12, 31))
    viop = [e["date"] for e in evs if e["market"] == "BIST"]
    assert viop == ["2026-10-30", "2026-12-31"]                 # 29 Ekim tatil; çift aylar
    us = {e["date"]: e["title"] for e in evs if e["market"] == "US"}
    assert us == {"2026-10-16": "ABD aylık opsiyon vadesi", "2026-11-20": "ABD aylık opsiyon vadesi",
                  "2026-12-18": "ABD dörtlü vade (quad witching)"}


def test_macro_times_converted_to_istanbul():
    conf = {"events": [{"name": "Fed", "market": "US", "kind": "cb", "time": "14:00", "tz": "America/New_York",
                        "dates": ["2026-10-28", "2026-12-09*"]}]}
    evs = ce.macro_events(conf)
    assert evs[0]["when"].startswith("2026-10-28T21:00")          # yaz saati (EDT)
    assert evs[1]["when"].startswith("2026-12-09T22:00")          # kış saati (EST)
    assert "projeksiyon" in evs[1]["detail"]


def test_build_merges_company_events_and_window(monkeypatch):
    monkeypatch.setattr(ce, "now_utc", lambda: datetime(2026, 10, 1, 9, tzinfo=ZoneInfo("UTC")))
    px = {"NVDA": {"next_earnings": {"date": "2026-11-17", "eps_est": 2.4736, "rev_est": 109.01e9},
                   "next_dividend": {"ex": "2026-12-04", "pay": "2026-12-26"}},
          "AAPL": {"next_earnings": {"date": "2027-03-01"}}}
    cal = ce.build([Stock("NVDA", "Nvidia", "US", []), Stock("AAPL", "Apple", "US", [])], px, days_ahead=90,
                   conf={"events": [{"name": "TÜFE", "market": "BIST", "time": "10:00", "dates": ["2026-10-05", "2026-09-03"]}]})
    titles = [e["title"] for e in cal["events"]]
    assert "NVDA bilanço" in titles and "NVDA temettü hak kullanım" in titles and "AAPL bilanço" not in titles
    assert "TÜFE" in titles and len([t for t in titles if t == "TÜFE"]) == 1     # 3 Eylül pencere dışında
    nv = next(e for e in cal["events"] if e["title"] == "NVDA bilanço")
    assert nv["detail"] == "EPS beklentisi 2,47 · gelir beklentisi 109,01 mr"
    assert cal["events"] == sorted(cal["events"], key=lambda e: (e["when"], -e["importance"], e["title"]))


def test_config_file_parses():
    import yaml
    conf = yaml.safe_load(ce.CONF.read_text(encoding="utf-8"))
    evs = ce.macro_events(conf)
    assert any(e["title"].startswith("TCMB faiz") and e["date"] == "2026-10-22" for e in evs)
    assert any(e["title"].startswith("Fed") and e["date"] == "2026-10-28" for e in evs)
