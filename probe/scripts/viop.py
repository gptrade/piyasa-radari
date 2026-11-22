import requests, json, time
UA = {"User-Agent": "Mozilla/5.0 piyasa-radari/1.0 (+https://github.com/gptrade/piyasa-radari)"}
def unflatten(arr):
    """SvelteKit devalue: düz dizi + indeks referansları → nesne"""
    memo = {}
    def h(i):
        if i in memo: return memo[i]
        if i < 0: return None
        v = arr[i]
        if isinstance(v, list):
            if v and isinstance(v[0], str) and v[0] in ("Date", "Set", "Map", "BigInt", "RegExp"):
                out = v[1] if len(v) > 1 else None
            else:
                out = [h(x) for x in v]
        elif isinstance(v, dict):
            out = {k: h(x) for k, x in v.items()}
        else:
            out = v
        memo[i] = out
        return out
    return h(0)
def show(o, depth=0, maxd=3, pre=""):
    if depth > maxd: return
    if isinstance(o, dict):
        for k, v in list(o.items())[:40]:
            s = json.dumps(v, ensure_ascii=False)[:160] if not isinstance(v, (dict, list)) or depth == maxd else ("{" + ",".join(list(v)[:15]) + "}" if isinstance(v, dict) else f"[{len(v)}] " + json.dumps(v[:2], ensure_ascii=False)[:160])
            print(pre + k + ": " + s)
            if isinstance(v, dict) and depth < maxd: show(v, depth + 1, maxd, pre + "  ")
for p in ["/quote/ist/ASELS/forecast/", "/stocks/aapl/forecast/"]:
    r = requests.get("https://stockanalysis.com" + p + "__data.json", headers=UA, timeout=30)
    j = r.json(); nodes = j["nodes"]
    info = unflatten(nodes[1]["data"])["info"]
    print("=====", p); print("info keys:", list(info)[:80])
    print({k: info.get(k) for k in ("currency", "financialCurrency", "reportingCurrency", "fiscalYearEnd", "exchange", "symbol", "ticker", "earningsDate", "nextEarnings") if k in info})
    for k, v in info.items():
        if any(w in k.lower() for w in ("curr", "earn", "fisc")): print("  info.", k, json.dumps(v, ensure_ascii=False)[:200])
    d = unflatten(nodes[-1]["data"])
    print("stats.annual", json.dumps(d["estimates"]["stats"]["annual"], ensure_ascii=False)[:600])
    print("stats.quarterly", json.dumps(d["estimates"]["stats"]["quarterly"], ensure_ascii=False)[:600])
    print("table.quarterly keys", list(d["estimates"]["table"]["quarterly"])[:40])
    print("table.quarterly dates", json.dumps({k: d["estimates"]["table"]["quarterly"].get(k) for k in ("dates", "fiscalQuarter", "fiscalYear", "period", "date")}, ensure_ascii=False)[:500])
    print("table.annual dates", json.dumps({k: d["estimates"]["table"]["annual"].get(k) for k in ("dates", "fiscalYear", "date")}, ensure_ascii=False)[:300])
    print("eps chart", json.dumps(d["estimatesCharts"]["eps"], ensure_ascii=False)[:400]); print("meta", d["meta"], "rec", json.dumps(d["recommendations"][-2:], ensure_ascii=False))
    time.sleep(4)
