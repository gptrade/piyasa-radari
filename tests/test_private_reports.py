import io
import json

from PIL import Image

from radar import private_reports as pr


def png(w=50, h=40):
    b = io.BytesIO(); Image.new("RGB", (w, h), "white").save(b, "PNG"); return b.getvalue()


def make_root(tmp_path):
    r = tmp_path / "_raporlar"
    (r / "sirket").mkdir(parents=True)
    (r / "sektor" / "2026-10-07_bankacilik_GarantiBBVA").mkdir(parents=True)
    (r / "strateji").mkdir()
    (r / "sirket" / "OKU.md").write_text("Şirket raporları")
    (r / "sirket" / "2026-10-07_THYAO_IsYatirim.txt").write_text("THYAO hedef fiyat 450 TL AL " * 40)
    (r / "sirket" / "ekran.jpg").write_bytes(png())
    d = r / "sektor" / "2026-10-07_bankacilik_GarantiBBVA"
    for i in (10, 2, 1):
        (d / f"{i}.png").write_bytes(png())
    (r / "strateji" / "notlar.docx").write_bytes(b"x")          # desteklenmeyen tür: atlanır
    return r


def test_units_and_order(tmp_path):
    u = pr.units(make_root(tmp_path))
    assert [(x["kind"], x["path"].name) for x in u] == [
        ("sirket", "2026-10-07_THYAO_IsYatirim.txt"), ("sirket", "ekran.jpg"), ("sektor", "2026-10-07_bankacilik_GarantiBBVA")]
    assert [f.name for f in u[2]["files"]] == ["1.png", "2.png", "10.png"]
    assert pr.name_hints(u[0]["path"]) == {"date": "2026-10-07", "subject": "THYAO", "broker": "IsYatirim"}


def test_content_text_vs_media(tmp_path):
    u = pr.units(make_root(tmp_path))
    text, media = pr.content(u[0])
    assert "hedef fiyat" in text and media == []
    text, media = pr.content(u[2])
    assert text == "" and len(media) == 3 and media[0][0] == "image/png"
    big = tmp_path / "big.jpg"
    Image.new("RGB", (4000, 3000), "white").save(big, "JPEG")
    mime, data = pr._shrink(big.read_bytes(), "image/jpeg")
    assert max(Image.open(io.BytesIO(data)).size) == 2000


X = {"type": "sirket", "broker": "İş Yatırım", "date": "2026-10-07", "tickers": ["THYAO"], "rating": "Endeks Üstü Getiri",
     "target_price": 450, "prev_target": 400, "currency": "TRY", "thesis": "Kısa tez.", "catalysts": ["Yolcu büyümesi"],
     "risks": ["Yakıt"], "sentiment": "bullish", "confidence": 75, "materiality": "medium",
     "estimate_changes": [{"metric": "Net kâr", "period": "2026T", "new": "120 mlr", "old": "100 mlr", "change": "+20%"}],
     "detailed_summary": ["GİZLİ AYRINTI"], "top_picks": [], "model_portfolio": {}}


def test_public_record_and_notes():
    r = pr.public_record(X, "a" * 40, "sirket", {}, "2026-10-08T10:00:00Z")
    assert r["rating"] == "AL" and r["tp"] == 450 and "detailed_summary" not in r and "GİZLİ" not in json.dumps(r, ensure_ascii=False)
    n = pr.notes_from_record(r)
    assert n[0]["t"] == "THYAO" and n[0]["action"] == "up" and n[0]["src"] == "Rapor" and n[0]["ts"].startswith("2026-10-07")
    it = pr.feed_item(r, X, {"THYAO"})
    assert it.tickers == ["THYAO"] and it.analysis["sentiment"] == "bullish" and it.extra["no_ai"]
    assert "GİZLİ" not in json.dumps(it.to_dict(), ensure_ascii=False)
    assert pr.feed_item(r, X, {"AAPL"}) is None


def test_sector_record_picks():
    x = {**X, "type": "sektor", "tickers": [], "sector": "Bankacılık", "top_picks": [{"ticker": "VAKBN.IS", "rating": "AL", "target_price": 40}],
         "model_portfolio": {"added": ["AKBNK"], "removed": []}}
    r = pr.public_record(x, "b" * 40, "sektor", {}, "2026-10-08T10:00:00Z")
    n = pr.notes_from_record(r)
    assert [(a["t"], a["action"], a["src"]) for a in n] == [("VAKBN", "set", "Sektör raporu"), ("AKBNK", "add", "Strateji raporu")]
    it = pr.feed_item(r, x, {"VAKBN"})
    assert it.tickers == [] and it.analysis["affected_tickers"] == ["VAKBN"]       # sektör raporu: piyasa geneli gibi


class FakeAI:
    enabled = True

    def __init__(self):
        self.calls = []

    def ask_json(self, system, prompt, tool, fmt, max_tokens=1500, media=None):
        self.calls.append((prompt[:40], len(media or [])))
        return {**X, "_provider": "Fake"}


def test_process_limits_and_remembers(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    done = tmp_path / "done.json"
    monkeypatch.setattr(pr, "telegram", lambda r, x: True)
    ai = FakeAI()
    res = pr.process(ai, {"THYAO"}, {"max_per_run": 2}, root=root, done_path=done)
    assert res["status"] == {"count": 2, "waiting": 1} and len(res["records"]) == 2 and len(ai.calls) == 2
    assert ai.calls[1][1] == 1                                                         # görsel rapor: medya ile
    res = pr.process(ai, {"THYAO"}, {"max_per_run": 2}, root=root, done_path=done)
    assert res["status"]["count"] == 1 and ai.calls[2][1] == 3
    assert pr.process(ai, {"THYAO"}, {}, root=root, done_path=done)["status"]["count"] == 0
    assert all(len(s) == 40 for s in json.loads(done.read_text()))                     # yalnız sha1, dosya adı yok


def test_disabled_without_folder(tmp_path):
    assert pr.process(FakeAI(), set(), {}, root=tmp_path / "yok")["status"] == {"disabled": True}
