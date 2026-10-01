import os, re, json, time, requests
from datetime import date, timedelta, datetime, timezone
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/128.0 piyasa-radari/1.0"}
def p(*a): print(*a, flush=True)
names = ["FINNHUB_API_KEY","FINNHUB_TOKEN","FINNHUB_KEY","FINNHUB_API_TOKEN","FINNHUB",
         "ALPHAVANTAGE_API_KEY","ALPHA_VANTAGE_API_KEY","ALPHA_VANTAGE_KEY","ALPHAVANTAGE_KEY","AV_API_KEY"]
p("== secrets"); [p(n, bool(os.environ.get(n))) for n in names]
fh = next((os.environ[n] for n in names[:5] if os.environ.get(n)), None)
av = next((os.environ[n] for n in names[5:] if os.environ.get(n)), None)
def show(label, r, n=600):
    try: p(label, r.status_code, r.text[:n].replace("\n"," "))
    except Exception as e: p(label, "ERR", e)
if fh:
    p("== finnhub")
    to = date.today(); fr = to - timedelta(days=2)
    for path, params in [("company-news", {"symbol":"AAPL","from":fr,"to":to}),
                         ("company-news", {"symbol":"THYAO.IS","from":fr,"to":to}),
                         ("stock/metric", {"symbol":"AAPL","metric":"all"}),
                         ("stock/metric", {"symbol":"THYAO.IS","metric":"all"}),
                         ("stock/recommendation", {"symbol":"AAPL"}),
                         ("stock/earnings", {"symbol":"AAPL"}),
                         ("stock/peers", {"symbol":"AAPL"}),
                         ("news", {"category":"general"}),
                         ("news", {"category":"merger"}),
                         ("stock/price-target", {"symbol":"AAPL"}),
                         ("news-sentiment", {"symbol":"AAPL"}),
                         ("stock/profile2", {"symbol":"THYAO.IS"})]:
        params = {**params, "token": fh}
        r = requests.get(f"https://finnhub.io/api/v1/{path}", params=params, timeout=30)
        if path == "company-news" and r.status_code == 200:
            js = r.json(); p(path, params["symbol"], "n=", len(js))
            for a in js[:3]: p("   ", {k: a.get(k) for k in ("datetime","source","headline","url","related","category")})
        elif path == "stock/metric" and r.status_code == 200:
            m = r.json().get("metric") or {}
            p(path, params["symbol"], "keys", len(m), {k: m.get(k) for k in ("peTTM","pbQuarterly","psTTM","evEbitdaTTM","currentEv/freeCashFlowTTM","roeTTM","netProfitMarginTTM","dividendYieldIndicatedAnnual","beta","52WeekHigh","marketCapitalization","revenueGrowthTTMYoy","epsGrowthTTMYoy","totalDebt/totalEquityQuarterly")})
        else:
            show(f"{path} {params.get('symbol') or params.get('category')}", r, 400)
        time.sleep(1.2)
if av:
    p("== alphavantage")
    r = requests.get("https://www.alphavantage.co/query", params={"function":"NEWS_SENTIMENT","tickers":"AAPL","limit":50,"sort":"LATEST","apikey":av}, timeout=30)
    js = r.json(); p("keys", list(js)[:6], js.get("items"), js.get("Information") or js.get("Note"))
    for a in (js.get("feed") or [])[:4]:
        ts = [t for t in a.get("ticker_sentiment",[]) if t["ticker"]=="AAPL"]
        p("   ", a.get("time_published"), a.get("source"), "|", a.get("title")[:90], "|", ts, "| overall", a.get("overall_sentiment_score"))
    time.sleep(2)
    r = requests.get("https://www.alphavantage.co/query", params={"function":"NEWS_SENTIMENT","tickers":"AAPL,MSFT","limit":50,"apikey":av}, timeout=30)
    js = r.json(); p("AAPL,MSFT items", js.get("items"), js.get("Information") or js.get("Note"))
    for a in (js.get("feed") or [])[:3]: p("   ", a.get("title")[:80], [t["ticker"] for t in a.get("ticker_sentiment",[])][:8])
p("== yfinance info")
import yfinance as yf
for s in ["AAPL","THYAO.IS","VAKBN.IS","GLRMK.IS"]:
    try:
        i = yf.Ticker(s).info
        p(s, {k: i.get(k) for k in ("trailingPE","forwardPE","priceToBook","enterpriseToEbitda","priceToSalesTrailing12Months","pegRatio","trailingPegRatio","dividendYield","marketCap","returnOnEquity","profitMargins","debtToEquity","revenueGrowth","earningsGrowth","beta","sector","industry","bookValue","trailingEps","forwardEps","enterpriseValue","ebitda","freeCashflow")})
    except Exception as e: p(s, "ERR", e)
p("== KAP")
r = requests.post("https://www.kap.org.tr/tr/api/disclosure/members/byCriteria", json={"fromDate": (date.today()-timedelta(days=60)).isoformat(), "toDate": date.today().isoformat(), "mkkMemberOidList": [], "subjectList": []}, headers={**UA, "Referer":"https://www.kap.org.tr/tr/bildirim-sorgu","Accept":"application/json","Content-Type":"application/json"}, timeout=60)
p("list", r.status_code, len(r.content))
rows = r.json() if r.status_code == 200 else []
p("rows", len(rows), "dates", rows[-1].get("publishDate") if rows else None, rows[0].get("publishDate") if rows else None)
if rows: p("row keys", list(rows[0].keys()))
from collections import Counter
c = Counter(x.get("subject") for x in rows); p("top subjects", c.most_common(40))
pick = {}
for x in rows:
    s = (x.get("subject") or "").lower()
    for k in ("sunum", "finansal rapor", "faaliyet raporu", "analist"):
        if k in s and k not in pick: pick[k] = x
for k, x in pick.items():
    p("--", k, x.get("disclosureIndex"), x.get("stockCodes") or x.get("relatedStocks"), x.get("subject"), x.get("publishDate"), x.get("attachmentCount"))
    d = requests.get(f"https://www.kap.org.tr/tr/Bildirim/{x['disclosureIndex']}", headers=UA, timeout=60)
    t = d.text; p("  detail", d.status_code, len(t))
    links = sorted(set(re.findall(r'(?:https://www\.kap\.org\.tr)?/tr/api/[^"\'\s<>\\]+', t)))[:15]; p("  api links", links)
    p("  file/download", sorted(set(re.findall(r'[^"\'\s<>]*file/download[^"\'\s<>\\]*', t)))[:10])
    p("  pdf", sorted(set(re.findall(r'[^"\'\s<>]*\.pdf[^"\'\s<>\\]*', t, re.I)))[:10])
    for m in re.finditer(r'attach', t, re.I):
        p("  ctx:", t[max(0,m.start()-150):m.start()+250].replace("\n"," ")); break
    txt = re.sub(r"<[^>]+>", " ", re.sub(r"(?s)<script.*?</script>|<style.*?</style>", " ", t))
    txt = re.sub(r"\s+", " ", txt); p("  text len", len(txt), "|", txt[:500])
    time.sleep(1)
p("== SEC")
SEC = {"User-Agent": os.environ.get("SEC_USER_AGENT") or "piyasa-radari research gptrade@users.noreply.github.com"}
r = requests.get("https://data.sec.gov/submissions/CIK0000320193.json", headers=SEC, timeout=30)
p("submissions", r.status_code)
if r.ok:
    f = r.json()["filings"]["recent"]
    for i, form in enumerate(f["form"]):
        if form == "8-K":
            acc = f["accessionNumber"][i].replace("-", ""); p("8-K", f["filingDate"][i], f["items"][i], f["primaryDocument"][i])
            idx = requests.get(f"https://www.sec.gov/Archives/edgar/data/320193/{acc}/index.json", headers=SEC, timeout=30)
            p("  index", idx.status_code, [x["name"] for x in idx.json()["directory"]["item"]][:12] if idx.ok else idx.text[:200])
            break
r = requests.get("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=AAPL&type=8-K&dateb=&owner=include&count=5&output=atom", headers=SEC, timeout=30)
p("atom", r.status_code, re.findall(r"<link[^>]+href=\"([^\"]+)\"", r.text)[:3])
r = requests.get("https://www.sec.gov/files/company_tickers.json", headers=SEC, timeout=30); p("tickers", r.status_code, len(r.content))
