import requests, json, os, collections
os.makedirs("probe57", exist_ok=True)
s=requests.Session(); s.headers.update({"User-Agent":"Mozilla/5.0 (piyasa-radari takvim yoklamasi; github.com/gptrade/piyasa-radari)"})
r=s.get("https://ec.europa.eu/eurostat/news/release-calendar",timeout=60); print("page",r.status_code,list(s.cookies.keys()))
for base in ["https://ec.europa.eu/eurostat/o/calendars/eventsJson","https://ec.europa.eu/eurostat/en/o/calendars/eventsJson"]:
  for meth in ["GET","POST"]:
    p={"start":"2026-10-12T00:00:00+02:00","end":"2026-12-31T00:00:00+01:00","theme":"","category":"","keywords":"","isEuroindicator":"true","authorInclude":"","authorExclude":""}
    h={"X-Requested-With":"XMLHttpRequest","Accept":"application/json, text/javascript, */*; q=0.01","Referer":"https://ec.europa.eu/eurostat/news/release-calendar"}
    r=s.request(meth,base,params=p if meth=="GET" else None,data=p if meth=="POST" else None,headers=h,timeout=60)
    print("==",base,meth,r.status_code,len(r.content),r.headers.get("content-type"))
    if r.content:
        try:
            d=r.json(); json.dump(d,open("probe57/ev.json","w")); print(len(d)); print(json.dumps(d[:2],ensure_ascii=False)[:1200])
            print([ (x.get("start"),x.get("title")) for x in d if "nflation" in json.dumps(x) or "HICP" in json.dumps(x)][:20])
        except Exception as e: print(r.text[:300])
r=s.get("https://ec.europa.eu/eurostat/web/main/subscribe/ics.format",timeout=60); print("ics page",r.status_code,len(r.text))
import re; print(set(re.findall(r'href="([^"]*\.ics[^"]*)"',r.text)))
