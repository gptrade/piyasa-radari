import requests, re, os, time, json
UA={"User-Agent":"Mozilla/5.0 (piyasa-radari takvim yoklamasi; github.com/gptrade/piyasa-radari)","Accept-Language":"tr-TR,tr;q=0.9"}
O="probe46"; os.makedirs(O,exist_ok=True)
s=requests.Session(); s.headers.update(UA)
r=s.get("https://www.tuik.gov.tr/ulusaltakvim/index.js",timeout=90); print(r.status_code,len(r.content))
t=r.text; open(f"{O}/index.js","w").write(t)
urls=sorted(set(re.findall(r'["\'`]((?:https?://[\w.-]+)?/[\w/.-]*(?:api|Api|API|Takvim|takvim|Get|Liste|json)[^"\'`\s]{0,150})["\'`]',t)))
print("URLS",urls[:60])
for m in list(re.finditer(r'fetch\(|axios|\.get\(|\.post\(|XMLHttpRequest',t))[:20]:
    print("CALL:",t[max(0,m.start()-300):m.start()+400].replace("\n"," "))
