"""ABD temel veri hattı: SEC companyfacts → BIST seri şeması (sentetik, Apple benzeri eylül mali yılı)."""
from radar.fundamentals import metrics as M, us as U


def _facts():
    """FY: Eki–Eyl. Gelir tablosu çeyreklik (3 ay) + yıllık; nakit akışı yalnız YTD (3/6/9/12 ay)."""
    fy = [("2023-10-01", ["2023-12-30", "2024-03-30", "2024-06-29", "2024-09-28"]),
          ("2024-09-29", ["2024-12-28", "2025-03-29", "2025-06-28", "2025-09-27"]),
          ("2025-09-28", ["2025-12-27", "2026-03-28", "2026-06-27", "2026-09-26"])]
    rev, ni, cfo, capex, assets, shares = [], [], [], [], [], []
    qrev = 100.0
    for start, ends in fy:
        prev_end, ytd_c, tot_r = start, 0.0, 0.0
        for i, e in enumerate(ends):
            qrev += 5
            tot_r += qrev
            ytd_c += qrev * 0.3
            filed = e[:8] + "28"
            if i < 3:                                    # 10-Q: 3 aylık gelir (+ yıl başından)
                rev.append({"start": prev_end if i else start, "end": e, "val": qrev, "filed": filed, "form": "10-Q"})
                ni.append({"start": prev_end if i else start, "end": e, "val": qrev * 0.2, "filed": filed, "form": "10-Q"})
            cfo.append({"start": start, "end": e, "val": ytd_c, "filed": filed})
            capex.append({"start": start, "end": e, "val": ytd_c / 3, "filed": filed})
            assets.append({"end": e, "val": 1000 + qrev, "filed": filed})
            shares.append({"end": e, "val": 50.0, "filed": filed, "accn": "a" + e})
            prev_end = e
        rev.append({"start": start, "end": ends[-1], "val": tot_r, "filed": "x", "form": "10-K"})
        ni.append({"start": start, "end": ends[-1], "val": tot_r * 0.2, "filed": "x", "form": "10-K"})
    usd = lambda xs: {"units": {"USD": xs}}  # noqa: E731
    return {"entityName": "Örnek Inc.", "facts": {
        "us-gaap": {"Revenues": usd(rev), "NetIncomeLoss": usd(ni), "NetCashProvidedByUsedInOperatingActivities": usd(cfo),
                    "PaymentsToAcquirePropertyPlantAndEquipment": usd(capex), "Assets": usd(assets),
                    "StockholdersEquity": usd([dict(a, val=a["val"] / 2) for a in assets]),
                    "OperatingIncomeLoss": usd([dict(r, val=r["val"] * 0.3) for r in rev])},
        "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": shares}}}}}


def test_quarter_key_nearest_calendar_quarter():
    assert U.quarter_key("2025-09-27") == "2025/09" and U.quarter_key("2025-12-27") == "2025/12"
    assert U.quarter_key("2026-01-02") == "2025/12" and U.quarter_key("2025-10-31") == "2025/09"
    assert U._shift("2026/03", -1) == "2025/12" and U._shift("2025/12", 1) == "2026/03"


def test_series_q4_and_ytd_cashflow():
    ser = U.build_series(_facts(), quarters=8)
    p = ser["periods"]
    assert p[-1] == "2026/09" and len(p) == 8
    i = p.index("2026/09")
    # Q4 gelir = yıllık − 3 çeyrek; son çeyrek geliri 100 + 12×5 = 160
    assert abs(ser["q"]["revenue"][i] - 160) < 1e-6
    # Nakit akışı YTD farkından: çeyreklik = gelir × 0,3; capex eksi işaretli
    assert abs(ser["q"]["cfo"][i] - 48) < 1e-6 and ser["q"]["capex"][i] < 0
    assert abs(ser["ttm"]["revenue"][i] - sum(ser["q"]["revenue"][i - 3:i + 1])) < 1e-6
    assert abs(ser["ttm"]["fcf"][i] - (ser["ttm"]["cfo"][i] + ser["ttm"]["capex"][i])) < 1e-6
    assert ser["bs"]["paid_capital"][i] == 50.0 and ser["bs"]["total_assets"][i] == 1160


def test_metrics_engine_reads_us_series():
    doc = {"code": "ORN", "currency": "USD", "template": "sanayi", "series": U.build_series(_facts(), quarters=8)}
    m = M.company(doc, 40.0)
    assert m and m["valuation"]["mcap"] == 2000 and m["ratios"]["roe"] > 0
    assert m["ratios"]["rev_growth"] > 0                     # nominal büyüme (USD'de TÜFE dönüşümü yok)


def test_dei_share_classes_summed():
    f = {"facts": {"dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        {"end": "2026-10-20", "val": 5.0, "accn": "q3", "filed": "2026-10-28"},
        {"end": "2026-10-20", "val": 3.0, "accn": "q3", "filed": "2026-10-28"}]}}}}}
    assert U.shares_series(f, ["2026/09", "2026/12"]) == [8.0, 8.0]          # kapak tarihi (20 Eki) çeyrek sonuna (Eylül) yazılır, sonra ileri taşınır
