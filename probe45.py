import requests, re, os, time
UA={"User-Agent":"Mozilla/5.0 (piyasa-radari takvim yoklamasi; github.com/gptrade/piyasa-radari)","Accept-Language":"tr-TR,tr;q=0.9"}
O="probe45"; os.makedirs(O,exist_ok=True)
s=requests.Session(); s.headers.update(UA)
def get(name,url,**kw):
    for a in range(2):
        try:
            r=s.get(url,timeout=90,**kw)
            print(f"== {name} {url} -> {r.status_code} {r.headers.get('content-type')} {len(r.content)}B final={r.url}")
            if name: open(f"{O}/{name}","wb").write(r.content)
            return r
        except Exception as e:
            print(f"== {name} {url} -> ERR {e}"); time.sleep(5)
r=get("vt.html","https://www.tuik.gov.tr/Kurumsal/Veri_Takvimi")
if r is not None:
    t=r.text
    print("forms",re.findall(r"<form[^>]*>",t)[:5]); print("tables",len(re.findall("<table",t)),"tr",t.count("<tr"))
    print("ajax/api:",sorted(set(re.findall(r'["\']((?:/[\w]+)+/(?:Get|get|Ajax|ajax|Takvim|Liste)[\w/]*[^"\']{0,80})["\']',t)))[:30])
    print("scripts:",re.findall(r'<script[^>]*src="([^"]+)"',t)[:20])
    body=re.sub(r"<script.*?</script>|<style.*?</style>","",t,flags=re.S)
    txt=re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",body)); i=txt.find("Takvim"); print("TEXT:",txt[i:i+2500])
    for m in list(re.finditer(r"\$\.ajax|fetch\(|url\s*:",t))[:10]: print("JS:",t[m.start()-100:m.start()+400].replace("\n"," "))
r=get("ri.html","https://www.resmiistatistik.gov.tr/")
for j in re.findall(r'src="([^"]+\.js)"',r.text if r is not None else ""):
    jr=get(None,("https://www.resmiistatistik.gov.tr" if j.startswith("/") else "https://www.resmiistatistik.gov.tr/")+j.lstrip("/") if not j.startswith("http") else j)
    if jr is not None and jr.ok:
        t=jr.text
        print("  api:",sorted(set(re.findall(r'["\'`]((?:https?://[\w.-]+)?/(?:api|Api|API)[^"\'`\s]{0,120})["\'`]',t)))[:40])
        print("  hosts:",sorted(set(re.findall(r'["\'`](https?://[\w.-]+\.gov\.tr[^"\'`\s]{0,80})["\'`]',t)))[:30])
        for m in list(re.finditer(r'[Tt]akvim',t))[:8]: print("  ctx:",t[max(0,m.start()-200):m.end()+300].replace("\n"," "))
