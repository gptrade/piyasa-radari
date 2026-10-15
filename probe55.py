import requests, re, os
os.makedirs("probe55", exist_ok=True)
UA={"User-Agent":"Mozilla/5.0 (piyasa-radari takvim yoklamasi; github.com/gptrade/piyasa-radari)"}
for u in ["https://ec.europa.eu/eurostat/news/release-calendar","https://ec.europa.eu/eurostat/web/main/news/release-calendar"]:
    try:
        r=requests.get(u,headers=UA,timeout=60); print("==",u,r.status_code,len(r.text),r.url)
        t=r.text; open("probe55/"+str(len(t))+".html","w").write(t)
        print(" json/ics:",sorted(set(re.findall(r'["\'](/eurostat/[^"\']*(?:json|ics|calendar|events|Event)[^"\']{0,120})["\']',t)))[:30])
        for m in list(re.finditer(r"(?i)flash estimate[^<]{0,80}inflation|HICP|euro area annual inflation",t))[:5]: print("  ctx",re.sub(r"\s+"," ",t[m.start()-300:m.end()+200]))
    except Exception as e: print("ERR",u,e)
