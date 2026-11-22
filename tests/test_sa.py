import json
from datetime import date

from radar import sa


def flat(obj):
    """devalue kodlayıcı (test için): nesneyi düz diziye çevirir."""
    arr = []
    def enc(v):
        i = len(arr); arr.append(None)
        if isinstance(v, dict):
            arr[i] = {k: enc(x) for k, x in v.items()}
        elif isinstance(v, list):
            arr[i] = [enc(x) for x in v]
        else:
            arr[i] = v
        return i
    enc(obj)
    return arr


def page(info, data):
    return {"type": "data", "nodes": [{"type": "data", "data": flat({"session": None})}, {"type": "data", "data": flat({"info": info})},
                                      {"type": "data", "data": flat(data)}]}


FC = {"priceTargets": {"avg": 454.31, "median": 460.5, "low": 315, "high": 580, "numPriceTargets": 14},
      "currentRatings": {"consensus": "Buy", "score": 7.5, "count": 14, "strongBuy": 9, "buy": 3, "hold": 2, "sell": 0, "strongSell": 0},
      "recommendations": [{"date": "2026-11-20", "score": 7.5, "total": 14}],
      "estimatesCharts": {"eps": {"2026-12-31": {"no": 6, "avg": 1.62, "low": 1.3, "high": 2.04}, "2027-12-31": "[PRO]"},
                          "revenue": {"2026-12-31": {"no": 8, "avg": 3.1e10, "low": 2.9e10, "high": 3.2e10}}},
      "estimates": {"stats": {"annual": {"epsThis": {"last": 2.11, "this": 1.62, "growth": -23.0}}, "quarterly": {"epsThis": {"last": None, "this": None, "growth": None}}},
                    "table": {"quarterly": {"dates": ["2026-06-30", "2026-09-30", "2026-12-31"], "eps": [0.5, 0.9, "[PRO]"], "revenue": [7e9, 8e9, 9e9], "lastDate": "2026-09-30"}}}}


def test_parse_forecast_skips_pro():
    info, d = sa.nodes(page({"curr": {"price": "TRY", "financial": "USD"}}, FC))
    f = sa.parse_forecast(info, d)
    assert f["pt"] == {"avg": 454.31, "med": 460.5, "low": 315.0, "high": 580.0, "n": 14}
    assert f["rt"]["c"] == "Buy" and f["rt"]["strongBuy"] == 9 and f["fy"]["end"] == "2026-12-31" and f["fy"]["eps"]["n"] == 6
    assert f["cur"] == "TRY" and f["fcur"] == "USD" and "qt" not in f and f["tq"]["eps"][2] is None


def test_parse_stats_percent_and_suffix():
    d = {"shortSelling": {"data": [{"id": "shortInterest", "value": "144.79M", "hover": "144,791,472"}, {"id": "shortFloat", "value": "1.00%", "hover": "1.003%"}]},
         "ratios": {"data": [{"id": "peForward", "value": "36.37", "hover": "36.367"}, {"id": "lynchFairValue", "value": None, "proOnly": True}]},
         "dates": {"data": [{"id": "earningsdate", "value": "Jan 29, 2027", "hover": "Jan 29, 2027"}]}}
    s = sa.parse_stats(d)
    assert s == {"shortInterest": 144791472.0, "shortFloat": 0.01003, "peForward": 36.367, "earningsdate": "Jan 29, 2027"}


def test_surprise_uses_last_estimate_before_report():
    h = {}
    fc = {"tq": {"dates": ["2026-09-30", "2026-12-31"], "eps": [0.5, 0.6], "rev": [8e9, 9e9], "last": "2026-06-30"}}
    sa.snapshot(h, "BIST:X", fc, "2026-10-01")
    fc2 = {"tq": {"dates": ["2026-09-30", "2026-12-31"], "eps": [0.55, 0.6], "rev": [8e9, 9e9], "last": "2026-06-30"}}
    sa.snapshot(h, "BIST:X", fc2, "2026-10-20")                              # tahmin güncellendi
    fc3 = {"tq": {"dates": ["2026-09-30", "2026-12-31"], "eps": [0.66, 0.62], "rev": [8.8e9, 9e9], "last": "2026-09-30"}}
    sa.snapshot(h, "BIST:X", fc3, "2026-11-10")                              # rapor geldi
    s = sa.surprises(h["BIST:X"])
    assert len(s) == 1 and s[0]["eps_e"] == 0.55 and s[0]["eps_a"] == 0.66 and abs(s[0]["eps_s"] - 0.2) < 1e-9 and abs(s[0]["rev_s"] - 0.1) < 1e-9


class Sess:
    def __init__(self, pages, robots="User-agent: *\nDisallow: /e/\nDisallow: /p/\n"):
        self.pages, self.robots, self.calls = pages, robots, []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        class R:
            pass
        r = R()
        path = url.replace(sa.BASE, "")
        if path == "/robots.txt":
            r.status_code, r.text = 200, self.robots
            return r
        p = self.pages.get(path)
        r.status_code = 200 if p is not None else 404
        r.json = lambda: p
        r.raise_for_status = lambda: None
        return r


def test_run_writes_rows_and_respects_robots(tmp_path, monkeypatch):
    monkeypatch.setattr(sa, "universe", lambda: [("BIST", "THYAO", 1e10), ("BIST", "ADESE", 1e6), ("US", "AAPL", 4e12)])
    monkeypatch.setattr(sa, "watch_codes", lambda: {"THYAO"})
    pages = {"/quote/ist/THYAO/forecast/__data.json": page({"curr": {"price": "TRY"}}, FC),
             "/stocks/aapl/forecast/__data.json": page({"curr": {"price": "USD"}}, FC),
             "/stocks/aapl/statistics/__data.json": page({}, {"ratios": {"data": [{"id": "peForward", "hover": "36.4"}]}})}
    s = Sess(pages)
    doc = sa.run(tmp_path, session=s, today=date(2026, 11, 23), sleep=lambda x: None)
    assert set(doc["rows"]) == {"BIST:THYAO", "US:AAPL"} and doc["rows"]["US:AAPL"]["st"]["peForward"] == 36.4
    st = json.loads((tmp_path / "sa_state.json").read_text())
    assert st["BIST:ADESE"]["empty"] and s.calls[1].endswith("/quote/ist/THYAO/forecast/__data.json")   # izleme listesi önce
    # robots.txt hisse sayfalarını kapatırsa hiç okunmaz
    s2 = Sess(pages, robots="User-agent: *\nDisallow: /\n")
    sa.run(tmp_path / "b", session=s2, today=date(2026, 11, 23), sleep=lambda x: None)
    assert s2.calls == [sa.BASE + "/robots.txt"]
