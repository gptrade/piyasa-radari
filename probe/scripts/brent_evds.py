import json, os, sys, subprocess, time
import numpy as np, pandas as pd
sys.path.insert(0, "main")
from radar import guc, korku, kredili, http

out = []
P = lambda *a: out.append(" ".join(str(x) for x in a))

# ---------- 1) EVDS: tahvil / gösterge faiz serileri
key = os.environ.get("EVDS_API_KEY", "")
B = "https://evds3.tcmb.gov.tr/igmevdsms-dis/"
def j(path):
    r = http.get(B + path, headers={"key": key}, timeout=60)
    try: return r.json() if r is not None and r.status_code == 200 else None
    except ValueError: return None
cats = j("categories/type=json") or []
P("== EVDS kategori", len(cats))
hits = []
for c in cats:
    cid = c.get("CATEGORY_ID")
    groups = j(f"datagroups/mode=2&code={cid}&type=json") or []
    for g in groups:
        name = (g.get("DATAGROUP_NAME") or "") + " " + (g.get("DATAGROUP_NAME_ENG") or "")
        if any(w in name.lower() for w in ("dibs", "tahvil", "bond", "gösterge", "benchmark", "yield", "getiri")):
            hits.append((g.get("DATAGROUP_CODE"), name, g.get("FREQUENCY_STR"), g.get("START_DATE"), g.get("END_DATE")))
for h in hits: P("  grup", h)
for code, *_ in hits[:12]:
    sl = j(f"serieList/type=json&code={code}") or []
    for s in sl[:30]:
        P("    seri", s.get("SERIE_CODE"), "|", s.get("SERIE_NAME"), "|", s.get("FREQUENCY_STR"), s.get("START_DATE"), "-", s.get("END_DATE"))

# ---------- 2) Korku endeksi geçmişi + Brent / MOVE ilişkisi
px = pd.read_parquet("guc/px.parquet")
members = json.load(open("fin/_universe.json"))["members"]
codes = {m["code"] for m in members}
adj, close, vol = guc.wide(px, "adj"), guc.wide(px, "close"), guc.wide(px, "volume")
bench = guc.clean_index(adj["XU100"])
st = [c for c in adj.columns if c in codes]
a, cl, v = adj[st], close[st], vol[st]
cnt = a.notna().sum(axis=1); keep = cnt >= 0.5 * cnt.rolling(20, min_periods=1).median()
a, cl, v = a[keep], cl[keep], v[keep]
clean, ret = guc.clean_prices(a)
b = guc.breadth(clean, ret, (cl * v).where(cl.notna()), bench)
extra = {"USDTRY": adj["USDTRY"].dropna()}
if "GOLD" in adj: extra["GOLDTRY"] = (adj["GOLD"] * adj["USDTRY"].ffill()).dropna()
if "XBANK" in adj: extra["XBANK"] = guc.clean_index(adj["XBANK"])
kd = json.load(open("guc/kredili.json")) if os.path.exists("guc/kredili.json") else None
lv = kredili.leverage(kd, bench)
if lv is not None: extra["MARGIN"] = lv
idx, sc = korku.compute(b, bench, extra)
idx = idx.dropna()
P("== endeks", idx.index[0].date(), idx.index[-1].date(), "son", round(idx.iloc[-1], 1))

import yfinance as yf
dl = yf.download("BZ=F ^MOVE ^VIX", start="2010-01-01", progress=False, auto_adjust=True, threads=False)["Close"]
dl.index = pd.to_datetime(dl.index).tz_localize(None)
ix = idx.index
brent = dl["BZ=F"].reindex(ix).ffill()
move = dl["^MOVE"].reindex(ix).ffill()
vix = dl["^VIX"].reindex(ix).ffill()
usd = extra["USDTRY"].reindex(ix).ffill()
brent_tl = brent * usd
x = bench.reindex(ix).ffill()

def corr_block(name, s):
    P(f"-- {name}")
    lvl = pd.concat([idx, s], axis=1).dropna()
    P("   seviye korelasyonu (tüm dönem):", round(lvl.corr().iloc[0, 1], 3), "n", len(lvl))
    for h in (5, 20, 60):
        d = pd.concat([idx.diff(h), np.log(s).diff(h)], axis=1).dropna().iloc[::h]
        P(f"   {h}g değişim korelasyonu (örtüşmesiz):", round(d.corr().iloc[0, 1], 3), "n", len(d))
    # dönemsel
    for a0, a1 in (("2011", "2015"), ("2016", "2019"), ("2020", "2022"), ("2023", "2026")):
        d = pd.concat([idx.diff(20), np.log(s).diff(20)], axis=1).loc[a0:a1].dropna().iloc[::20]
        if len(d) > 8: P(f"   {a0}-{a1} 20g:", round(d.corr().iloc[0, 1], 3), "n", len(d))
    # yüzdelik bileşen olarak (20g değişim, 3y yüzdelik) endeksin geri kalanıyla korelasyon ve ileri getiri
    comp = korku.pct_rank(-np.log(s).diff(20))       # petrol yükselişi = korku (ithalatçı ülke)
    both = pd.concat([comp, idx], axis=1).dropna()
    P("   bileşen (ters 20g değişim, yüzdelik) ~ endeks seviye korelasyonu:", round(both.corr().iloc[0, 1], 3))
    xu = (x / usd)
    f63 = xu.shift(-63) / xu - 1
    zz = pd.cut(comp, [0, 20, 40, 60, 80, 100], labels=["0-20", "20-40", "40-60", "60-80", "80-100"])
    t = pd.DataFrame({"z": zz, "f63": f63}).loc["2013":].dropna().groupby("z", observed=True)["f63"].agg(["size", "median"])
    P("   bileşen dilimine göre 3 ay sonraki XU100 (USD) medyan:", t.round(4).to_dict())

corr_block("Brent (USD)", brent)
corr_block("Brent (TL)", brent_tl)
corr_block("MOVE", move)
corr_block("VIX", vix)
# XU100 ile doğrudan
for name, s in (("Brent", brent), ("MOVE", move), ("VIX", vix)):
    d = pd.concat([np.log(x / usd).diff(20), np.log(s).diff(20)], axis=1).loc["2013":].dropna().iloc[::20]
    P(f"== XU100(USD) 20g getiri ~ {name} 20g değişim korelasyonu:", round(d.corr().iloc[0, 1], 3), "n", len(d))
open("probe/log45.txt", "w").write("\n".join(out))
print("\n".join(out))
