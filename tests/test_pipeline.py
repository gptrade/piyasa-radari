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
    assert {x["name"]: x["ok"] for x in feed["sources"]} == {"fake": True, "broken": False}
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
