import requests, os, json, collections
UA={"User-Agent":"Mozilla/5.0 (piyasa-radari takvim yoklamasi; github.com/gptrade/piyasa-radari)","Accept-Language":"tr-TR,tr;q=0.9","Accept":"application/json"}
O="probe47"; os.makedirs(O,exist_ok=True)
for y in (2026,2027):
    r=requests.get(f"https://www.tuik.gov.tr/Kurumsal/GetYillikHaberBulteniListesi?yil={y}",headers=UA,timeout=120)
    print(y,r.status_code,r.headers.get("content-type"),len(r.content))
    try: d=r.json()
    except Exception as e: print(r.text[:500]); continue
    json.dump(d,open(f"{O}/y{y}.json","w"),ensure_ascii=False)
    print(" keys",list(d) if isinstance(d,dict) else type(d))
    for k,v in (d.items() if isinstance(d,dict) else []):
        print(" ",k,len(v) if isinstance(v,list) else v)
        if isinstance(v,list) and v:
            print("   sample",json.dumps(v[0],ensure_ascii=False)[:600])
            print("   kurum",collections.Counter(x.get("sorumluKisaAd") for x in v).most_common(30))
            oct_=[x for x in v if str(x.get("gTarih","")).startswith(f"{y}-10-1")]
            for x in sorted(oct_,key=lambda x:x["gTarih"])[:60]: print("    ",x["gTarih"],x.get("sorumluKisaAd"),"|",x.get("adi"))
