"""p65: BIST faktör geri testi (noktasal). Mali tablo: KAP (fin dalı). Fiyat: Yahoo.
- Oluşum tarihi = dönem sonu + 3 ay (raporlar bu sürede yayımlanmış olur; yıllıklar için de güvenli tarafta).
- Değerleme: oluşum ayı sonu GERÇEK fiyat × dönemin ödenmiş sermayesi.
- Getiri: Yahoo düzeltilmiş kapanış (bedelsiz+temettü), sonraki 3 ve 6 ay; ±%80/%300 kırpılır.
- Kesit: sanayi şablonu (banka/sigorta hariç), en küçük %20 piyasa değeri atılır.
"""
import json, math, sys, subprocess, tarfile, io, statistics as stt
from pathlib import Path
sys.path.insert(0, "app")
from radar.fundamentals import metrics as M, store
import yfinance as yf, pandas as pd

FIN = Path("fin"); FIN.mkdir(exist_ok=True)
tar = subprocess.check_output(["git", "-C", "app", "archive", "origin/fin"])
tarfile.open(fileobj=io.BytesIO(tar)).extractall(FIN)
uni = json.loads((FIN / "_universe.json").read_text())
sector = {m["code"]: m.get("sector") for m in uni["members"]}
codes = sorted(sector)
# fiyatlar
store.FIN = FIN; store.PX_HIST = FIN / "_raw.json"
store.update_price_history(codes)
raw = {c: dict(v) for c, v in json.loads(store.PX_HIST.read_text())["p"].items()}
adj = {}
for i in range(0, len(codes) + 1, 100):
    part = [f"{c}.IS" for c in codes[i:i + 100]] + (["XU100.IS"] if i == 0 else [])
    df = yf.download(" ".join(part), period="5y", interval="1d", auto_adjust=True, group_by="ticker", threads=True, progress=False)
    for t in part:
        try:
            s = df[t]["Close"].dropna()
        except KeyError:
            continue
        me = s.groupby(s.index.to_period("M")).last()
        adj[t.replace(".IS", "")] = {str(k): float(v) for k, v in me.items()}
print("fiyat:", len(raw), "ham,", len(adj), "düzeltilmiş")

def madd(m, k):
    y, mo = map(int, m.split("-")); mo += k
    y += (mo - 1) // 12; mo = (mo - 1) % 12 + 1
    return f"{y}-{mo:02d}"

rows = []
for p in sorted(FIN.glob("[A-Z0-9]*.json")):
    doc = json.loads(p.read_text())
    if doc.get("template") != "sanayi" or not doc.get("series"):
        continue
    code = doc.get("code") or p.stem
    v = M.View(doc["series"], doc.get("currency") or "TRY")
    if code not in raw or code not in adj:
        continue
    for pk in v.p:
        if v.v("ttm", "revenue", pk) is None:
            continue
        y, mo = pk.split("/"); F = madd(f"{y}-{mo}", 3)
        px, sh = raw[code].get(F), v.v("bs", "paid_capital", pk)
        a0, a3, a6, am1, am12 = (adj[code].get(madd(F, k)) for k in (0, 3, 6, -1, -12))
        if not px or not sh or not a0:
            continue
        mcap = px * sh
        r = M.ratios(v, pk)
        t = lambda k: v.v("ttm", k, pk); b = lambda k: v.v("bs", k, pk)
        nd = b("net_debt") or 0
        cats = M.category_scores(r)
        qs = [x for x in cats.values() if x is not None]
        pio = M.piotroski(v, pk)["score"]
        row = {"code": code, "sec": sector.get(code), "pk": pk, "F": F, "mcap": mcap,
               "ep": (t("net_parent") or 0) / mcap if t("net_parent") is not None else None,
               "bp": (b("equity_parent") / mcap) if b("equity_parent") else None,
               "ebev": (t("ebitda") / (mcap + nd)) if t("ebitda") is not None and mcap + nd > 0 else None,
               "sp": (t("revenue") / mcap), "fcfy": (t("fcf") / mcap) if t("fcf") is not None else None,
               "roe": r.get("roe"), "roic": r.get("roic"), "cfo_ni": r.get("cfo_ni"),
               "accr": (-r["accruals"]) if r.get("accruals") is not None else None,
               "growth": r.get("rev_growth"), "pio": pio, "quality": sum(qs) / len(qs) if len(qs) >= 4 else None,
               "mon": (-r["mon_share"]) if r.get("mon_share") is not None else None,
               "lowlev": (-r["net_debt_ebitda"]) if r.get("net_debt_ebitda") is not None else None,
               "mom": (am1 / am12 - 1) if am1 and am12 else None,
               "f3": (a3 / a0 - 1) if a3 else None, "f6": (a6 / a0 - 1) if a6 else None}
        for k in ("f3", "f6"):
            if row[k] is not None:
                row[k] = max(-0.8, min(3.0, row[k]))
        rows.append(row)
xu = adj.get("XU100", {})
print("gözlem:", len(rows))
json.dump(rows, open("probe65/rows.json", "w"))
json.dump({"XU100": xu}, open("probe65/xu.json", "w"))
