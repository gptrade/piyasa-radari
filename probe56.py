import requests, json, os, collections
os.makedirs("probe56", exist_ok=True)
UA={"User-Agent":"Mozilla/5.0 (piyasa-radari takvim yoklamasi; github.com/gptrade/piyasa-radari)","Accept":"application/json"}
for p in [{"start":"2026-10-12","end":"2026-12-31","isEuroindicator":"true"},{"start":"2026-10-12T00:00:00","end":"2026-11-30T00:00:00","isEuroindicator":"true","theme":"","category":"","keywords":"","authorInclude":"","authorExclude":""}]:
    r=requests.get("https://ec.europa.eu/eurostat/o/calendars/eventsJson",params=p,headers=UA,timeout=60)
    print("==",r.status_code,r.headers.get("content-type"),len(r.content))
    try:
        d=r.json(); print(type(d), len(d)); print(json.dumps(d[:2],ensure_ascii=False)[:1500])
        json.dump(d,open("probe56/ev.json","w"))
        print(collections.Counter(x.get("title","")[:60] for x in d).most_common(40))
        break
    except Exception as e: print(r.text[:500])
