import requests, re, time, json, html
UA = {"User-Agent": "Mozilla/5.0 piyasa-radari/1.0 (+https://github.com/gptrade/piyasa-radari)"}
pages = ["/stocks/aapl/forecast/", "/stocks/aapl/statistics/", "/stocks/aapl/", "/quote/ist/THYAO/", "/quote/ist/THYAO/forecast/",
         "/quote/ist/THYAO/statistics/", "/stocks/aapl/financials/", "/stocks/aapl/dividend/", "/markets/gainers/", "/ipos/calendar/", "/stocks/earnings-calendar/", "/etf/spy/holdings/"]
for p in pages:
    r = requests.get("https://stockanalysis.com" + p, headers=UA, timeout=30)
    t = r.text
    title = re.search(r"<title>(.*?)</title>", t, re.S)
    hs = [html.unescape(re.sub("<[^>]+>", "", h)).strip() for h in re.findall(r"<h[23][^>]*>(.*?)</h[23]>", t, re.S)]
    # gömülü veri anahtarları (SvelteKit)
    keys = sorted(set(re.findall(r'\b([a-zA-Z_]{3,24}):', t[t.find("__sveltekit") if "__sveltekit" in t else 0:][:200000])))[:80]
    pro = len(re.findall(r"(?i)upgrade to pro|pro only|locked", t))
    print("==", p, r.status_code, len(t), "|", title.group(1).strip()[:100] if title else "")
    print("   bolumler:", hs[:25])
    print("   pro-kilit izi:", pro)
    print("   anahtarlar:", keys[:80])
    time.sleep(3)
