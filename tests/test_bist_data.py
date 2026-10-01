import io
import json
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from radar import bist_data as bd
from radar import calendar_events as ce
from radar.config import Stock
from radar.enrich import classify_event
from radar.scorecard import kind

FIX = (Path(__file__).parent / "fixtures" / "thb_sample.csv").read_text(encoding="utf-8")
IST = ZoneInfo("Europe/Istanbul")
STOCKS = [Stock("AEFES", "Anadolu Efes", "BIST", []), Stock("A1CAP", "A1 Capital", "BIST", []), Stock("NVDA", "Nvidia", "US", [])]


def zipped(name, data: bytes) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr(name, data)
    return b.getvalue()


def test_parse_bulletin_real_format():
    rows = bd.parse_bulletin(FIX)
    assert "AEFES" in rows and "A1CAP" in rows and "AEFES.AOF" not in rows and "AKBNK" not in rows
    a = rows["AEFES"]
    assert a["value"] == 910556909.59 and a["short_value"] == 90033809.2
    assert a["short_pct"] == round(90033809.2 / 910556909.59 * 100, 2) and a["short_ok"] is True
    assert rows["A1CAP"]["short_pct"] == 0.0 and rows["A1CAP"]["short_ok"] is False


def test_update_flows_accumulates_and_summarizes(tmp_path, monkeypatch):
    monkeypatch.setattr(bd, "FLOWS", tmp_path / "flows.json")
    monkeypatch.setattr(bd, "now_utc", lambda: datetime(2026, 10, 1, 20, tzinfo=IST))
    hdr = "\n".join(FIX.splitlines()[:2])
    base = FIX.splitlines()[6]                                        # AEFES satırı
    calls = []

    def fake_get(url, timeout=40):
        calls.append(url)
        d = url.rsplit("thb", 1)[1][:8]
        if d == "20261001":
            return None                                               # bugünün bülteni henüz yok
        line = base.replace("2026-09-30", f"{d[:4]}-{d[4:6]}-{d[6:]}")
        return zipped(f"thb{d}1.csv", (hdr + "\n" + line + "\n").encode("cp1254"))
    monkeypatch.setattr(bd, "_get", fake_get)
    out = bd.update_flows(STOCKS, max_fetch=12)
    assert len(out["days"]) == 12 and "2026-10-01" not in out["days"]
    s = out["summary"]["AEFES"]
    assert s["n"] == 11 and s["avg20"] == s["short_pct"] and len(s["series"]) == 12
    n0 = len(calls)
    bd.update_flows(STOCKS, max_fetch=12)                             # bugün saatte bir; geçmiş günler tekrar denenmez
    assert len(calls) - n0 <= 1 + 12


def test_flow_item_on_spike_only():
    flows = {"summary": {"AEFES": {"date": "2026-09-30", "short_pct": 12.0, "avg20": 4.0, "n": 20, "short_value": 1, "value": 1},
                         "A1CAP": {"date": "2026-09-30", "short_pct": 3.0, "avg20": 1.0, "n": 20, "short_value": 1, "value": 1}}}
    items = bd.flow_items(STOCKS, flows)
    assert [i.tickers[0] for i in items] == ["AEFES"]                 # A1CAP %5 tabanının altında
    it = items[0]
    assert "işlemlerin %12,0'i (30.09)" in it.title and it.analysis["materiality"] == "medium"
    d = it.to_dict()
    assert classify_event(d) == "short" and kind(d) == "Açığa satış (BIST)"
    assert bd.flow_items(STOCKS, flows)[0].id == it.id


def gk_zip():
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Sorgu Tarihi / Query Date", "Başlangıç Tarihi / Start Date", "Bitiş Tarihi / End Date", "Pay Kodu / Code",
               "Şirket Adı / Company Name", "Pay Grubu / Stock Type", "Toplanti Türü / Meeting Type", "Toplantı Tarihi / Meeting Date",
               "Toplantı Saati / Meeting Time", "Toplanti Adresi / Meeting Address", "Hesap Dönemi / Accounting Period",
               "Gündemde Yer Alan Hak Kullanım Süreçleri / Corporate Actions Involved In Agenda", "Toplantı İptal Edildi mi? / Was Meeting Cancelled?",
               "Web Sayfası / Web Page"])
    ws.append(["", None, None, "A1CAP", "A1 CAPİTAL", None, "Olağanüstü Genel Kurul", datetime(2026, 10, 13), "11:00:00", "", "",
               "Kayıtlı Sermaye Tavanı", "Hayır", "https://www.kap.org.tr/tr/Bildirim/1656417"])
    ws.append(["", None, None, "AEFES", "ANADOLU EFES", None, "Olağan Genel Kurul", datetime(2026, 10, 20), "10:00:00", "", "",
               "Kar Payı Dağıtım", "Evet", "https://kap"])
    ws.append(["", None, None, "XXXXX", "X", None, "Olağan Genel Kurul", datetime(2026, 10, 21), "10:00:00", "", "", "", "Hayır", ""])
    b = io.BytesIO()
    wb.save(b)
    return zipped("gk2026.xlsx", b.getvalue())


def test_agm_parse_and_calendar(monkeypatch):
    items = bd.parse_gk(gk_zip())
    assert len(items) == 3 and items[0]["date"] == "2026-10-13" and items[0]["time"] == "11:00"
    evs = bd.agm_events(STOCKS, items)
    assert [e["ticker"] for e in evs] == ["A1CAP"]                    # AEFES iptal, XXXXX listede yok
    assert evs[0]["title"] == "A1CAP olağanüstü genel kurul" and evs[0]["importance"] == 2
    monkeypatch.setattr(ce, "now_utc", lambda: datetime(2026, 10, 1, 9, tzinfo=ZoneInfo("UTC")))
    cal = ce.build(STOCKS, {}, conf={"events": []}, extra=evs)
    a = next(e for e in cal["events"] if e["kind"] == "agm")
    assert a["when"].startswith("2026-10-13T11:00") and a["timed"] and "Kayıtlı Sermaye Tavanı" in a["detail"]


def test_agm_cache_used_when_fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(bd, "GK_CACHE", tmp_path / "gk.json")
    from radar.models import iso, now_utc
    (tmp_path / "gk.json").write_text(json.dumps({"updated": iso(now_utc()), "items": [{"code": "A1CAP"}]}))
    monkeypatch.setattr(bd, "_get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("indirme yapılmamalı")))
    assert bd.agm_list() == [{"code": "A1CAP"}]
