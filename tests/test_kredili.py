import io

import openpyxl
import pandas as pd

from radar import kredili


def _xlsx(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([None, "ARACI KURUMLAR - KREDİLİ İŞLEMLER"])
    ws.append([None, "Tarih", "No.", "Sözleşmeli", "Kullanan", "Kredi Hacmi (TL)", "Ort."])
    for r in rows:
        ws.append([None, *r])
    ws.append(["Güncellenme Tarihi:", None, "04.11.2026"])
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def test_parse_monthly_and_archive_formats():
    raw = _xlsx([("2026 - 09", 54, 633158, 42536, 101213107859.0, 1), ("2002-03", 80, 27107, 7687, 66928597.16, 1)])
    d = kredili.parse_xlsx(raw)
    assert d["2026-09"] == (101213107859.0, 42536, 633158) and "2002-03" in d


def test_links_pick_margin_files_only():
    html = '<a href="https://tspb.org.tr/wp-content/uploads/2026/11/BTVY_Araci_Kurumlarin_Kredili_Islemleri_20261104_140043.xlsx">x</a>' \
           '<a href="https://tspb.org.tr/wp-content/uploads/2026/02/BTVY_Krediler_2002-202512.xlsx">y</a>' \
           '<a href="https://tspb.org.tr/wp-content/uploads/2026/11/UYE_Factsheet_2026_10.xlsx">z</a>'
    assert len(kredili.links(html)) == 2


def test_leverage_uses_publication_lag_and_relative_growth():
    ix = pd.bdate_range("2026-01-01", "2026-11-20")
    bench = pd.Series(100.0, index=ix)
    doc = {"rows": [["2026-07", 131.6e9, 48935, 1], ["2026-10", 82.2e9, 38558, 1]]}
    s = kredili.leverage(doc, bench)
    assert s.loc[:"2026-11-06"].isna().all()                  # Ekim verisi 7 Kasım'dan itibaren
    assert abs(s.loc["2026-11-09"] - (-0.4707)) < 1e-3       # log(82,2/131,6), endeks yatay
    lt = kredili.latest(doc)
    assert lt["peak_ym"] == "2026-07" and lt["ym"] == "2026-10"
