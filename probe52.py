import requests, os, json, collections, csv, io
from datetime import date, timedelta
os.makedirs("probe52", exist_ok=True)
UA={"User-Agent":"Mozilla/5.0 (piyasa-radari takvim yoklamasi; github.com/gptrade/piyasa-radari)"}
for u in ["https://earningshub.com/robots.txt","https://www.earningshub.com/robots.txt","https://earningshub.com/terms","https://api.nasdaq.com/robots.txt","https://www.nasdaq.com/robots.txt"]:
    try:
        r=requests.get(u,headers=UA,timeout=30); print("==",u,r.status_code,len(r.content)); print(r.text[:1200] if "robots" in u else "")
    except Exception as e: print("==",u,"ERR",e)
fk=os.environ.get("FINNHUB_API_KEY"); d0=date.today(); d1=d0+timedelta(days=30)
if fk:
    r=requests.get("https://finnhub.io/api/v1/calendar/earnings",params={"from":d0,"to":d1,"token":fk},timeout=60)
    print("FINNHUB",r.status_code)
    try:
        ev=r.json().get("earningsCalendar") or []
        print(" n",len(ev)); print(" sample",ev[:3])
        print(" suffix",collections.Counter((e["symbol"].split(".")[1] if "." in e["symbol"] else "US") for e in ev).most_common(20))
        print(" hour",collections.Counter(e.get("hour") for e in ev))
        for s in ["SAP","ASML","NESN.SW","SAP.DE","MC.PA","AAPL","MSFT","TSLA","NVDA"]:
            print("  ",s,[ (e["date"],e.get("hour")) for e in ev if e["symbol"]==s])
    except Exception as e: print(r.text[:300])
    r=requests.get("https://finnhub.io/api/v1/calendar/earnings",params={"from":d0,"to":d1,"symbol":"SAP.DE","token":fk},timeout=60); print("FINNHUB SAP.DE",r.status_code,r.text[:300])
ak=os.environ.get("ALPHAVANTAGE_API_KEY")
if ak:
    r=requests.get("https://www.alphavantage.co/query",params={"function":"EARNINGS_CALENDAR","horizon":"3month","apikey":ak},timeout=60)
    print("AV",r.status_code,r.headers.get("content-type"))
    rows=list(csv.DictReader(io.StringIO(r.text)))
    print(" n",len(rows), rows[:2] if rows else r.text[:300])
    print(" cur",collections.Counter(x.get("currency") for x in rows).most_common(15))
    print(" suffix",collections.Counter((x["symbol"].split(".")[1] if "." in x["symbol"] else "US") for x in rows).most_common(15))
    for s in ["SAP","ASML","AAPL","NVDA"]: print("  ",s,[x for x in rows if x["symbol"]==s][:1])
