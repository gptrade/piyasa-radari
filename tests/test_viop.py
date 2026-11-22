from datetime import date

import pandas as pd

from radar import viop

H = ("TARIH;SOZLESME KODU;SOZLESME ADI;PAZAR;PAZAR SEGMENTI;SOZLESME TIPI;SOZLESME SINIFI;DAYANAK VARLIK;VADE TARIHI;UZLASMA FIYATI;"
     "ONCEKI UZLASMA FIYATI;UZLASMA FIYATI DEGISIMI (%);ACILIS FIYATI;EN DUSUK FIYAT;EN YUKSEK FIYAT;KAPANIS FIYATI; AGIRLIKLI ORTALAMA FIYAT;"
     "ISLEM HACMI;PRIM HACMI;ISLEM MIKTARI;ISLEM SAYISI;ACIK POZISYON;ACIK POZISYON DEGISIMI\nTRADE DATE;...\n")


def row(d, code, exp, settle, prev, vwap, oi, doi, qty=100):
    return f"{d};{code};x;x;x;x;x;x;{exp};{settle};{prev};0;0;0;0;{settle};{vwap};{qty * settle * 10};0;{qty};1;{oi};{doi}\n"


def test_parse_keeps_only_xu030_and_usdtry():
    t = H + row("2026-11-20", "F_XU0301226", "2026-12-31", 14798, 14500, 14700, 522771, 1000) + \
        row("2026-11-20", "F_XU0301226_ESNEK", "2026-12-31", 1, 1, 1, 1, 1) + row("2026-11-20", "O_XU0301226C15000", "2026-12-31", 1, 1, 1, 1, 1) + \
        row("2026-11-20", "F_USDTRY1226", "2026-12-31", 52.1, 52.0, 52.05, 900000, 10) + row("2026-11-20", "F_THYAO1226", "2026-12-31", 300, 299, 300, 10, 1)
    rows = viop.parse_bulletin(t)
    assert [r[0] for r in rows] == ["F_XU0301226", "F_USDTRY1226"]
    assert rows[0][2] == 14798 and rows[0][5] == 14700 and rows[0][8] == 522771


def test_states():
    assert viop.state(10, 5) == "lb" and viop.state(-10, 5) == "sb" and viop.state(10, -5) == "sc" and viop.state(-10, -5) == "lu"
    assert viop.state(0, 5) is None


def test_cost_series_weighted_on_increase_unchanged_on_decrease():
    xu = {"d1": {"F": {"oi": 100, "vwap": 100, "settle": 100}}, "d2": {"F": {"oi": 200, "vwap": 130, "settle": 130}},
          "d3": {"F": {"oi": 150, "vwap": 90, "settle": 90}}}
    s = viop.cost_series(xu, "F")
    assert [x[1] for x in s] == [100, 115, 115]


def test_update_and_build(tmp_path):
    days = [date(2026, 11, 16) + pd.Timedelta(days=i) for i in range(5)]
    files = {}
    for i, d in enumerate(days):
        k = d.isoformat()
        files[d.strftime("%Y%m%d")] = H + row(k, "F_XU0301226", "2026-12-31", 14000 + 100 * i, 14000 + 100 * (i - 1), 14000 + 100 * i, 1000 + 100 * i, 100) + \
            row(k, "F_XU0300227", "2027-02-26", 14500 + 100 * i, 14400 + 100 * i, 14500, 50 + 10 * i, 10) + \
            row(k, "F_USDTRY1226", "2026-12-31", 52.0, 51.9, 52.0, 1000, 1) + row(k, "F_USDTRY0327", "2027-03-31", 55.0, 54.9, 55.0, 1000, 1)
    get = lambda url: files.get(url.rsplit("_", 1)[1][:8])
    hist = viop.update({}, today=date(2026, 11, 20), max_fetch=20, get=get)
    assert len(hist["days"]) == 5 and "2026-11-13" in hist["missing"]          # 404 + eski = tatil sayılır
    px = pd.DataFrame([{"sym": s, "date": d, "close": v, "adj": v, "volume": 0} for d in days
                       for s, v in (("XU030", 13900.0), ("USDTRY", 50.5), ("IRX", 4.0))])
    doc = viop.build(hist, px)
    last = doc["last"]
    assert last["c"] == "F_XU0301226" and last["f"] == 14400 and last["st"] == "lb" and last["basis"] == 500
    assert doc["counts20"]["lb"] == 5 and doc["roll"] is None                  # vadeye > 20 iş günü
    assert doc["fx"]["curve"][0]["r"] > 0.3 and doc["carry"]["xu_ann"] > 0
    assert doc["cost"]["F_XU0301226"][-1][1] > 14000
