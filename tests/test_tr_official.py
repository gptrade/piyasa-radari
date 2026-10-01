from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from radar.config import Stock, TickerMatcher
from radar.enrich import classify_event, source_tier
from radar.sources import Context, tr_official as t, vendors

F = Path(__file__).parent / "fixtures" / "tr"
IST = ZoneInfo("Europe/Istanbul")
STOCKS = [Stock("A1CAP", "A1 Capital", "BIST", ["A1 Capital"]), Stock("VAKBN", "VakıfBank", "BIST", ["VakıfBank"])]


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(t, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(t, "now_utc", lambda: datetime(2026, 10, 1, 20, tzinfo=IST))
    return Context(settings={"sources": {}}, stocks=STOCKS, matcher=TickerMatcher(STOCKS),
                   since=datetime(2026, 9, 29, tzinfo=IST))


class Resp:
    def __init__(self, text=None, content=None, status=200):
        self.text = text or ""
        self.content = content if content is not None else self.text.encode("utf-8")
        self.status_code = status


def test_tuik_keeps_market_bulletins_only(ctx, monkeypatch):
    monkeypatch.setattr(t.http, "get", lambda url, **k: Resp((F / "tuik.html").read_text(encoding="utf-8")))
    items = t.collect_tuik(ctx)
    titles = [i.title for i in items]
    assert any("işsizlik oranı %7,8" in x for x in titles)
    assert any("ihracat %8,1" in x for x in titles)
    assert not any("eğitim süresi" in x for x in titles)                 # piyasa dışı bülten
    i = items[0]
    assert i.source_type == "macro" and i.source == "TÜİK" and i.extra["issuer"] == "TÜİK"
    assert t.collect_tuik(ctx) == []                                    # 15 dk dolmadan tekrar çekilmez
    d = i.to_dict()
    assert classify_event(d) == "macro" and source_tier(d) == 1


def test_bddk_parse_and_window(ctx, monkeypatch):
    html = (F / "bddk_39.html").read_text(encoding="utf-8")
    rows = t.parse_bddk(html)
    assert rows[0]["url"] == "https://www.bddk.org.tr/Duyuru/Detay/4306" and rows[0]["date"].date().isoformat() == "2026-09-30"
    monkeypatch.setattr(t, "_bddk_verify", lambda: True)
    monkeypatch.setattr(t.http._session, "get", lambda url, **k: Resp(html))
    items = t.collect_bddk(ctx)
    assert items and all(i.published >= "2026-09-24" for i in items)
    assert all(i.source.startswith("BDDK · ") for i in items)


def test_resmi_gazete_filters_relevant_and_runs_once_a_day(ctx, monkeypatch):
    raw = (F / "rg.htm").read_bytes()
    calls = []
    monkeypatch.setattr(t.http, "get", lambda url, **k: calls.append(url) or Resp(content=raw))
    items = t.collect_resmi_gazete(ctx)
    titles = [i.title for i in items]
    assert calls[0].endswith("/eskiler/2026/10/20261001.htm")
    assert any("Özel Tüketim Vergisi" in x for x in titles)
    assert not any("Malvarlığının Dondurulması" in x for x in titles)    # "tasarrufunda" tek başına eşleşmez
    assert not any("Üniversitesi" in x for x in titles)
    assert items[0].source.startswith("Resmi Gazete · ")
    assert t.collect_resmi_gazete(ctx) == [] and len(calls) == 1          # gün içinde bir kez


def test_bist_announcements_skip_ceremonies(ctx, monkeypatch):
    monkeypatch.setattr(t.http, "get", lambda url, **k: Resp((F / "bist_ann.html").read_text(encoding="utf-8")))
    items = t.collect_bist_announcements(ctx)
    titles = [i.title for i in items]
    assert "BIST Participation Indices Periodic Review" in titles
    assert not any("opening bell" in x.lower() for x in titles)
    assert all(i.lang == "en" and i.market == "BIST" for i in items)


def test_spk_press_matches_ticker(ctx, monkeypatch):
    monkeypatch.setattr(t.http, "get", lambda url, **k: Resp((F / "spk_basin.html").read_text(encoding="utf-8")))
    items = t.collect_spk_press(ctx)
    a1 = [i for i in items if "A1 Capital" in i.title]
    assert a1 and a1[0].tickers == ["A1CAP"] and a1[0].source_type == "regulator"
    assert any(i.source_type == "macro" for i in items)


def test_vendor_adapters_off_without_creds_and_explicit_when_configured(ctx, monkeypatch):
    for k in ("MATRIKS_API_KEY", "MATRIKS_API_SECRET", "FOREKS_USERNAME", "FOREKS_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    assert vendors.collect_matriks(ctx) == [] and vendors.collect_foreks(ctx) == []
    monkeypatch.setenv("MATRIKS_API_KEY", "x")
    monkeypatch.setenv("MATRIKS_API_SECRET", "y")
    with pytest.raises(RuntimeError, match="bağlantı henüz yazılmadı"):
        vendors.collect_matriks(ctx)
