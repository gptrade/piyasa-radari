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
