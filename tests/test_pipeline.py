"""Uçtan uca: ağ ve Claude taklit edilir, tekilleştirme ve kayıt doğrulanır."""
import json
from datetime import timedelta

import pytest

from radar import pipeline, prices
from radar.models import Item, iso, now_utc


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "DATA", tmp_path)
    monkeypatch.setattr(pipeline, "FEED", tmp_path / "feed.json")
    monkeypatch.setattr(pipeline, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(prices, "update_all", lambda stocks: {})
    monkeypatch.setattr(pipeline.tcmb, "update_macro", lambda settings: None)
    monkeypatch.setattr(pipeline.bb_quotes, "update", lambda settings: None)
    monkeypatch.setattr(pipeline.digest, "DIGEST_FILE", tmp_path / "digest.json")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    return tmp_path


def _items():
    ts = iso(now_utc() - timedelta(minutes=10))
    return [
        Item(source="A · Google News", source_type="news", market="BIST",
             title="VakıfBank kârını artırdı - A", url="https://a/1", published=ts, tickers=["VAKBN"]),
        Item(source="B · Google News", source_type="news", market="BIST",
             title="VakıfBank kârını artırdı - B", url="https://b/1", published=ts, tickers=["VAKBN"]),
        Item(source="KAP", source_type="disclosure", market="BIST", title="VAKBN: Finansal Rapor",
             url="https://kap/1", published=ts, tickers=["VAKBN"]),
    ]


def test_pipeline_dedup_and_persist(sandbox, monkeypatch):
    def broken(ctx):
        raise RuntimeError("kaynak çöktü")
    monkeypatch.setattr(pipeline, "COLLECTORS", [("fake", lambda ctx: _items()), ("broken", broken)])
    s = pipeline.run()
    assert s["new"] == 2                                 # aynı başlıklı iki haber → bir
    feed = json.loads((sandbox / "feed.json").read_text())
    assert len(feed["items"]) == 2
    st = {x["name"]: x["ok"] for x in feed["sources"]}
    assert st["fake"] is True and st["broken"] is False
    s2 = pipeline.run()                                  # ikinci tur: hepsi görülmüş
    assert s2["new"] == 0
    assert len(json.loads((sandbox / "feed.json").read_text())["items"]) == 2


def test_pipeline_uses_analyzer(sandbox, monkeypatch):
    monkeypatch.setattr(pipeline, "COLLECTORS", [("fake", lambda ctx: _items()[2:])])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    calls = []

    def fake_assess(self, item, context=""):
        calls.append(item.id)
        self.used += 1
        return {"sentiment": "bullish", "confidence": 80, "materiality": "high"}
    monkeypatch.setattr(pipeline.Analyzer, "assess", fake_assess)
    pipeline.run()
    feed = json.loads((sandbox / "feed.json").read_text())
    assert feed["items"][0]["analysis"]["sentiment"] == "bullish" and len(calls) == 1


def test_market_wide_macro_is_analyzed_but_speech_is_not(sandbox, monkeypatch):
    ts = iso(now_utc() - timedelta(minutes=5))
    items = [
        Item(source="TCMB · PPK Kararları", source_type="macro", market="BIST", title="PPK kararı",
             url="https://tcmb/ppk", published=ts, tickers=[], extra={"tcmb": "PPK Kararları"}),
        Item(source="TCMB · Başkanın Konuşmaları", source_type="macro", market="BIST", title="Konuşma",
             url="https://tcmb/k", published=ts, tickers=[], extra={"tcmb": "Başkanın Konuşmaları"}),
        Item(source="SPK Bülteni", source_type="regulator", market="BIST", title="SPK 2026/1",
             url="https://spk/1", published=ts, tickers=[]),
    ]
    monkeypatch.setattr(pipeline, "COLLECTORS", [("fake", lambda ctx: items)])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    seen = []

    def fake_assess(self, item, context=""):
        seen.append((item.title, context))
        self.used += 1
        return {"sentiment": "neutral", "confidence": 50, "materiality": "high", "affected_tickers": ["VAKBN"]}
    monkeypatch.setattr(pipeline.Analyzer, "assess", fake_assess)
    pipeline.run()
    assert [t for t, _ in seen] == ["PPK kararı"]
    assert "İzleme listesi" in seen[0][1] and "VAKBN" in seen[0][1]


def test_old_data_version_is_reset(sandbox, monkeypatch):
    (sandbox / "state.json").write_text(json.dumps({"seen": ["x"], "last_run": "2026-09-30T00:00:00Z"}))
    (sandbox / "feed.json").write_text(json.dumps({"items": [{"id": "old", "published": "2026-09-30T00:00:00Z",
                                                              "tickers": [], "extra": {}}]}))
    monkeypatch.setattr(pipeline, "COLLECTORS", [("fake", lambda ctx: [])])
    pipeline.run()
    assert json.loads((sandbox / "feed.json").read_text())["items"] == []
    assert json.loads((sandbox / "state.json").read_text())["version"] == pipeline.DATA_VERSION


def test_telegram_hello_sent_once(sandbox, monkeypatch):
    from radar import http as rhttp
    calls = []
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    monkeypatch.setattr(rhttp, "post", lambda url, **kw: calls.append(kw["json"]["text"]) or object())
    monkeypatch.setattr(pipeline, "COLLECTORS", [("fake", lambda ctx: [])])
    pipeline.run()
    pipeline.run()
    assert len(calls) == 1 and "bağlandı" in calls[0]
    feed = json.loads((sandbox / "feed.json").read_text())
    assert feed["sources"][-1]["name"] == "Telegram" and feed["sources"][-1]["ok"] is True


def test_earnings_items_window():
    from datetime import timedelta as td
    from radar.config import Stock
    today = now_utc().date()
    st = [Stock("NVDA", "NVIDIA", "US", []), Stock("AAPL", "Apple", "US", []), Stock("THYAO", "THY", "BIST", [])]
    px = {"NVDA": {"next_earnings": {"date": (today + td(days=3)).isoformat(), "eps_est": 1.2}},
          "AAPL": {"next_earnings": {"date": (today + td(days=30)).isoformat()}}, "THYAO": {}}
    items = pipeline.earnings_items(st, px, 7)
    assert [i.tickers for i in items] == [["NVDA"]] and items[0].extra["no_ai"] and "EPS beklentisi 1.2" in items[0].title
    assert items[0].id == pipeline.earnings_items(st, px, 7)[0].id      # aynı tarih → aynı kayıt, tekrar eklenmez


def test_source_health_tracks_last_ok_and_data(monkeypatch):
    from radar.pipeline import source_health
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)
    prev = {"KAP": {"last_ok": "2026-09-30T10:00:00Z", "last_data": "2026-09-30T09:00:00Z"}}
    st = [{"name": "KAP", "ok": True, "count": 0},
          {"name": "Basın", "ok": True, "count": 0, "warnings": ["x: timeout"]},
          {"name": "Yahoo", "ok": False, "count": 0, "error": "boom"},
          {"name": "X", "ok": True, "count": 0}]
    h = source_health(st, prev, now="2026-09-30T12:00:00Z")
    assert st[0]["last_ok"] == "2026-09-30T12:00:00Z" and st[0]["last_data"] == "2026-09-30T09:00:00Z"
    assert "last_ok" not in st[1]                          # uyarılı ve verisiz: başarılı sayılmaz
    assert "last_ok" not in st[2]
    assert st[3]["disabled"] == "X_BEARER_TOKEN tanımlı değil"
    assert h["KAP"]["last_ok"] == "2026-09-30T12:00:00Z"


def test_fair_order_round_robin_within_priority():
    from radar.models import Item
    from radar.pipeline import fair_order
    mk = lambda i, t, st="news": Item(source="s", source_type=st, market="US", title=f"{t}{i}", url=f"u{t}{i}",
                                      published=f"2026-09-30T1{i}:00:00Z", tickers=[t])
    q = [mk(1, "KAP", "disclosure"), mk(9, "NVDA"), mk(8, "NVDA"), mk(7, "NVDA"), mk(6, "THYAO"), mk(5, "AMD")]
    out = [i.title for i in fair_order(q, {"NVDA", "THYAO", "AMD", "KAP"})]
    assert out[0] == "KAP1"                                   # öncelik sınıfı korunur
    assert out[1:4] == ["NVDA9", "THYAO6", "AMD5"]            # her hisse birer tane
    assert out[4:] == ["NVDA8", "NVDA7"]
