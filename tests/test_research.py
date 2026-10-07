import json
from datetime import datetime, timedelta

from radar import research as rs
from radar.config import Stock
from radar.models import UTC, iso

KNOWN = {"THYAO": ["Türk Hava Yolları", "THY"], "TTKOM": ["Türk Telekom"]}


def test_parse_tr_keep():
    n = rs.parse_note('HİSSE DEĞERLENDİRMESİ-Yapı Kredi Yatırım, OTKAR-Otokar için hedef fiyatını 780 TL, tavsiyesini "al" olarak korudu')
    assert n["broker"] == "Yapı Kredi Yatırım" and n["t"] == "OTKAR" and n["tp"] == 780 and n["rating"] == "AL" and n["action"] == "keep"


def test_parse_tr_raise_with_prev_and_name():
    n = rs.parse_note("İş Yatırım, Türk Hava Yolları için hedef fiyatını 350,50 TL'den 420 TL'ye yükseltti - Bloomberg HT", known=KNOWN)
    assert n["t"] == "THYAO" and n["tp"] == 420 and n["prev"] == 350.5 and n["action"] == "up" and n["broker"] == "İş Yatırım"


def test_parse_tr_rating_only_and_noise():
    n = rs.parse_note("Ziraat Yatırım, GWIND-Galata Wind için endeks üzeri getiri tavsiyesiyle kapsama başladı")
    assert n["t"] == "GWIND" and n["rating"] == "AL" and n["action"] == "init"
    assert rs.parse_note("Borsa günü yükselişle tamamladı") is None
    assert rs.parse_note("BIST 100 endeksi için hedef 12.500 puan") is None


def test_parse_en():
    n = rs.parse_note("Morgan Stanley Lowers Apple (AAPL) Price Target to $240 from $260, Maintains Overweight")
    assert n["broker"] == "Morgan Stanley" and n["t"] == "AAPL" and n["tp"] == 240 and n["prev"] == 260
    assert n["action"] == "down" and n["rating"] == "AL" and n["cur"] == "USD"


def test_tr_num():
    assert rs.tr_num("1.250,50") == 1250.5 and rs.tr_num("88,75") == 88.75 and rs.tr_num("1,250.5") == 1250.5 and rs.tr_num("780") == 780


def test_parse_llms():
    txt = "# x\n\n### HİSSE DEĞERLENDİRMESİ-Gedik Yatırım, TTKOM için hedef fiyatını 95 TL'ye yükseltti\n- **Tarih:** 2026-10-02 10:15\n- **Özet:** ...\n- **Detay:** [Analizi oku](https://www.foreks.com/haber/detay/1/)\n\n---\n"
    e = rs.parse_llms(txt)
    assert e[0]["url"].endswith("/1/") and e[0]["published"] == "2026-10-02T07:15:00Z"


def test_consensus_and_update(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "STORE", tmp_path / "r.json")
    now = datetime.now(UTC)
    mk = lambda i, title, days: {"id": f"n{i}", "source": "AA", "source_type": "news", "title": title, "summary": "",
                                 "url": "u", "published": iso(now - timedelta(days=days)), "extra": {}}
    items = [mk(1, "İş Yatırım, THYAO için hedef fiyatını 400 TL'den 420 TL'ye yükseltti", 3),
             mk(2, "Ak Yatırım, THYAO için hedef fiyatını 380 TL olarak belirledi, tavsiyesini tut olarak korudu", 2),
             mk(3, "İş Yatırım, THYAO için hedef fiyatını 400 TL'den 420 TL'ye yükseltti", 1),   # aynı not, başka gün
             mk(4, "Borsa güne yükselişle başladı", 0)]
    watch = [Stock("THYAO", "Türk Hava Yolları", "BIST", ["THY"])]
    res = rs.update(items, {}, None, watch, {})
    data = json.loads((tmp_path / "r.json").read_text())
    assert res["added"] == 3 and len(data["notes"]) == 3
    c = data["consensus"]["THYAO"]
    assert c["n"] == 2 and c["median_tp"] == 400 and c["dist"]["TUT"] == 1
    assert rs.update(items, {}, None, watch, {})["added"] == 0


def test_merge_same_day_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "STORE", tmp_path / "r.json")
    now = iso(datetime.now(UTC))
    items = [{"id": "a", "source": "X", "source_type": "news", "title": "Yapı Kredi Yatırım Otokar İçin Hedef Fiyatını Açıkladı",
              "summary": "", "url": "u", "published": now, "extra": {}},
             {"id": "b", "source": "Y", "source_type": "news", "title": "Yapı Kredi Yatırım’dan Otokar için 780 TL hedef fiyat",
              "summary": "", "url": "u2", "published": now, "extra": {}}]
    rs.update(items, {}, None, [Stock("OTKAR", "Otokar", "BIST", [])], {})
    data = json.loads((tmp_path / "r.json").read_text())
    assert len(data["notes"]) == 1 and data["notes"][0]["tp"] == 780


def test_outlook_retried_until_summarized(tmp_path, monkeypatch):
    from radar import http
    from radar.config import TickerMatcher
    from radar.sources import Context, tr_official
    monkeypatch.setattr(rs, "STORE", tmp_path / "r.json")
    monkeypatch.setattr(tr_official, "STATE_FILE", tmp_path / "st.json")
    monkeypatch.setattr(rs, "OUTLOOKS", [{"key": "x", "house": "H", "title": "T", "url": "https://x/a.pdf", "pages": 2}])
    monkeypatch.setattr(rs, "_pdf_text", lambda data, pages: ("metin " * 100, 3))

    class R:
        headers = {"last-modified": "v1"}
        content = b"%PDF"
    monkeypatch.setattr(http, "get", lambda *a, **k: R())
    ctx = Context(settings={"sources": {"outlooks": {"interval_min": 0}}}, stocks=[], matcher=TickerMatcher([]),
                  since=datetime.now(UTC))
    first = rs.collect_outlooks(ctx)
    assert len(first) == 1
    assert rs.collect_outlooks(ctx) == []                      # aynı gün tekrar denenmez
    st = json.loads((tmp_path / "st.json").read_text())
    st["outlook_x_try"] = "2000-01-01"                          # ertesi gün: özet yok → yeniden
    (tmp_path / "st.json").write_text(json.dumps(st))
    again = rs.collect_outlooks(ctx)
    assert len(again) == 1 and again[0].id != first[0].id
    d = again[0].to_dict(); d["analysis"] = {"summary": "s", "key_points": [], "sentiment": "neutral"}
    rs.update([d], {}, None, [], {})
    st = json.loads((tmp_path / "st.json").read_text()); st["outlook_x_try"] = "2000-01-01"
    (tmp_path / "st.json").write_text(json.dumps(st))
    assert rs.collect_outlooks(ctx) == []                      # özet yazıldı: artık atlanır
