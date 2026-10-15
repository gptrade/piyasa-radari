import requests, re, os, json, time
os.makedirs("probe54", exist_ok=True)
UA={"User-Agent":"Mozilla/5.0 (piyasa-radari takvim yoklamasi; github.com/gptrade/piyasa-radari)"}
def get(u, **kw):
    try:
        r=requests.get(u,headers=UA,timeout=60,**kw); print("==",u,r.status_code,len(r.content)); return r
    except Exception as e: print("==",u,"ERR",e)
# S&P 500 (Wikipedia)
r=get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
if r is not None:
    import pandas as pd, io
    t=pd.read_html(io.StringIO(r.text))[0]; print(t.columns.tolist()[:5], len(t))
    t[["Symbol","Security","GICS Sector"]].to_csv("probe54/sp500.csv",index=False)
# ECB
for u in ["https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html","https://www.ecb.europa.eu/robots.txt"]:
    r=get(u)
    if r is not None:
        open("probe54/"+u.split("/")[-1],"w").write(r.text)
        if "robots" in u: print(r.text[:800])
        else:
            txt=re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",r.text)); 
            for m in re.finditer(r"(\d{1-2}/\d{1,2}/\d{4}|\d{1,2} \w+ 202[67])[^.]{0,120}monetary policy",txt): print("  ",m.group(0)[:160])
            i=txt.find("Monetary policy meeting"); print(txt[i-300:i+1500] if i>0 else txt[:1500])
# Eurostat euro indicators release calendar
for u in ["https://ec.europa.eu/eurostat/api/dissemination/catalogue/rss/en/statistics-update.rss",
          "https://ec.europa.eu/eurostat/news/release-calendar","https://ec.europa.eu/eurostat/robots.txt"]:
    r=get(u)
    if r is not None and "robots" in u: print(r.text[:600])
# Yahoo Europe earnings via yfinance
import yfinance as yf
for t in ["ASML.AS","SAP.DE","MC.PA","NESN.SW","SHEL.L","NOVO-B.CO","SIE.DE","AZN.L"]:
    try:
        c=yf.Ticker(t).calendar; print(t, c.get("Earnings Date") if isinstance(c,dict) else c)
    except Exception as e: print(t,"ERR",e)
    time.sleep(1)
