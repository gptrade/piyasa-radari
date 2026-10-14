"""TÜİK Ulusal Veri Yayımlama Takvimi: ayrıştırma, sınıflandırma, birleştirme ve takvime ekleme."""
import json
from pathlib import Path

from radar import calendar_events, tr_calendar as tc

FIX = Path(__file__).parent / "fixtures" / "trcal" / "uvyt_2026_ekim.json"


def _rows():
    return tc.compact(json.loads(FIX.read_text(encoding="utf-8")))


def test_compact_keeps_unpublished_rows_with_zero_id():
    rows = _rows()
    upcoming = [r for r in rows if r["t"] >= "2026-10-15"]
    assert len({(r["adi"], r["t"]) for r in upcoming if r["k"] == "TÜİK"}) >= 8   # id=0 satırlar tek kayda inmemeli
    assert {"Hizmet Üretim Endeksi", "İnşaat Üretim Endeksi", "Motorlu Kara Taşıtları"} <= {r["adi"] for r in rows}
    assert all(r["t"][10] == "T" and len(r["t"]) == 16 for r in rows)


def test_classify():
    assert tc.classify("Tüketici Fiyat Endeksi (TÜFE)", "TÜİK")["importance"] == 3
    assert tc.classify("Ödemeler Dengesi İstatistikleri   ", "TCMB")["key"] == "odemeler"
    assert tc.classify("Bankacılık Sektörü Kar-Zarar Tablosu Bilgileri (Fonksiyon ve Sahiplik Grubu Detayında)", "BDDK")["key"] == "bddk_aylik"
    assert tc.classify("Bankacılık Sektörü Mevduat Bilgileri (Fonksiyon ve Sahiplik Grubu Detayında)", "BDDK")["key"] == "bddk"
    assert tc.classify("Gösterge Niteliğindeki Merkez Bankası Kurları", "TCMB")["importance"] == 0
    assert tc.classify("Düzensiz Göç İstatistikleri", "İB") is None
    assert tc.classify("Tüketici Fiyat Endeksi", "TCMB") is None            # kurum da eşleşmeli


def test_events_week():
    evs, daily = tc.events(_rows(), "2026-10-12", "2026-10-16")
    by = {(e["key"], e["date"]): e for e in evs}
    cari = by[("odemeler", "2026-10-13")]
    assert cari["kind"] == "macro" and cari["importance"] == 3 and cari["title"] == "Ödemeler Dengesi (cari denge) · Ağustos 2026"
    assert cari["when"] == "2026-10-13T10:00+03:00" and cari["timed"] and cari["inst"] == "TCMB"
    assert cari["assets"] and cari["group"] == "Dış denge"
    bddk = by[("bddk", "2026-10-15")]                                      # 6 alt tablo tek olay
    assert bddk["kind"] == "data" and "6 tablo" in bddk["detail"] and len(bddk["items"]) == 6
    assert ("hizmet", "2026-10-15") in by and ("konut", "2026-10-16") in by and ("kfe", "2026-10-16") in by
    assert not any(e["key"] in ("kur", "analitik", "odeme_sis") for e in evs)  # her iş günü olanlar ızgarada yok
    assert {d["name"] for d in daily} >= {"TCMB gösterge kurları", "Ödeme sistemleri (PÖS, EFT)"}
    assert all("2026-10-12" <= e["date"] <= "2026-10-16" for e in evs)
    assert [e["when"] for e in evs] == sorted(e["when"] for e in evs)


def test_official_replaces_config_duplicate(monkeypatch):
    rows = _rows()
    tr_evs, daily = tc.events(rows, "2026-01-01", "2026-12-31")
    conf = {"events": [{"name": "Türkiye TÜFE (enflasyon)", "uvyt": "tufe", "market": "BIST", "kind": "macro",
                        "importance": 3, "time": "10:00", "dates": ["2026-11-03", "2026-12-03"]},
                       {"name": "TCMB faiz kararı (PPK)", "market": "BIST", "kind": "cb", "importance": 3,
                        "time": "14:00", "dates": ["2026-10-22"]}]}
    monkeypatch.setattr(calendar_events, "now_utc", lambda: __import__("datetime").datetime(2026, 10, 14, 9, tzinfo=__import__("datetime").timezone.utc))
    cal = calendar_events.build([], {}, conf=conf, tr=(tr_evs, daily, {"ok": True}))
    tufe = [e for e in cal["events"] if "TÜFE" in e["title"] and e["date"] >= "2026-11-01"]
    assert [e.get("src") for e in tufe] == ["uvyt", "uvyt"]                 # resmi takvim satırı, yedek değil
    assert any(e["kind"] == "cb" for e in cal["events"])
    assert cal["daily"] and cal["tr_until"] == "2026-12-03"


def test_load_rows_uses_cache_when_fetch_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(tc, "RAW_FILE", tmp_path / "raw.json")
    monkeypatch.setattr(tc, "fetch_year", lambda y: _rows() if y == 2026 else [])
    rows, st = tc.load_rows(force=True)
    assert st["ok"] and not st["cached"] and len(rows) == len(_rows())
    monkeypatch.setattr(tc, "fetch_year", lambda y: None)
    rows2, st2 = tc.load_rows(force=True)
    assert st2["ok"] and st2["cached"] and st2.get("error") and len(rows2) == len(rows)


def test_last_values_from_evds(tmp_path, monkeypatch):
    monkeypatch.setattr(tc, "LAST_FILE", tmp_path / "last.json")
    items = [{"Tarih": f"2025-{m}", "TP_TUKFIY2025_GENEL": str(100 + m)} for m in range(9, 13)]
    items += [{"Tarih": f"2026-{m}", "TP_TUKFIY2025_GENEL": str(112 + m)} for m in range(1, 10)]
    items += [{"Tarih": "02-10-2026", "TP_MKNETHAR_M7": "-189.9", "TP_AB_TOPLAM": "167387.7"}]

    class R:
        def json(self):
            return {"items": items}
    calls = []
    monkeypatch.setattr(tc.http, "get", lambda url, **k: calls.append(url) or R())
    v = tc.last_values("anahtar")
    assert v["tufe"] == "TÜFE (Eylül 2026): aylık %0,8, yıllık %11,0"
    assert v["menkul"] == "Yabancıların hisse net alımı (2 Ekim 2026): -189,9 milyon $"
    assert v["rezerv"] == "TCMB brüt rezervi (2 Ekim 2026): 167,4 milyar $"
    assert len(calls) == 2 and "TP.MKNETHAR.M7" in calls[1] and "TP.MKNETHAR.M7" not in calls[0]
    monkeypatch.setattr(tc.http, "get", lambda *a, **k: None)              # önbellek taze → istek yok
    assert tc.last_values("anahtar") == v
    assert tc.last_values(None) == v
