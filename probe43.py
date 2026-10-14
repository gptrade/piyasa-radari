import requests, re, os, time, json
UA={"User-Agent":"Mozilla/5.0 (piyasa-radari takvim yoklamasi; github.com/gptrade/piyasa-radari)","Accept-Language":"tr-TR,tr;q=0.9","Accept":"application/json, text/plain, */*"}
O="probe43"; os.makedirs(O,exist_ok=True)
s=requests.Session(); s.headers.update(UA)
B="https://veriportali.tuik.gov.tr"
for c in ["main-C0Z3qMtl.js","press-WcRk5lkh.js"]:
    t=s.get(B+"/assets/"+c,timeout=60).text; open(f"{O}/{c}","w").write(t)
    for m in list(re.finditer(r'Kurumsal|[Cc]alendar|Takvim|takvim|release',t))[:30]:
        print("---",c,t[max(0,m.start()-200):m.end()+250].replace("\n"," "))
t=open(f"{O}/press-WcRk5lkh.js").read()
print("PRESS ctx:"); 
for m in re.finditer(r'/api/',t): print("  ",t[max(0,m.start()-400):m.end()+300].replace("\n"," "))
def api(path,**p):
    try:
        r=s.get(B+path,params=p,timeout=60)
        print(f"== {path} {p} -> {r.status_code} {r.headers.get('content-type')} {len(r.content)}B")
        print("   ",r.text[:1500])
        return r
    except Exception as e: print("ERR",path,e)
api("/api/tr/press/latest")
api("/api/tr/press")
api("/api/tr/press",page=0,size=5)
