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
for p in ["/quote/ist/THYAO/forecast/", "/stocks/aapl/statistics/", "/quote/ist/ADESE/forecast/"]:
    r = requests.get("https://stockanalysis.com" + p + "__data.json", headers=UA, timeout=30)
    print("=====", p, r.status_code, len(r.content), r.headers.get("content-type"))
    try:
        j = r.json()
    except Exception as e:
        print("json degil", r.text[:300]); continue
    nodes = j.get("nodes") or []
    for ni, n in enumerate(nodes):
        if not n or n.get("type") != "data": continue
        d = unflatten(n["data"])
        print("--- node", ni, list(d)[:30] if isinstance(d, dict) else type(d))
        if ni == len(nodes) - 1: show(d, 0, 2)
    time.sleep(4)
