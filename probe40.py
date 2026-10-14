import requests, re, os, json, time
UA={"User-Agent":"Mozilla/5.0 (piyasa-radari takvim yoklamasi; github.com/gptrade/piyasa-radari)","Accept-Language":"tr-TR,tr;q=0.9"}
O="probe40"; os.makedirs(O,exist_ok=True)
s=requests.Session(); s.headers.update(UA)
def get(name,url,**kw):
    for a in range(3):
        try:
            r=s.get(url,timeout=60,**kw)
            print(f"== {name} {url} -> {r.status_code} {r.headers.get('content-type')} {len(r.content)}B final={r.url}")
            if name: open(f"{O}/{name}","wb").write(r.content)
            return r
        except Exception as e:
            print(f"== {name} {url} -> ERR {e}"); time.sleep(5)
r=get("vp_index.html","https://data.tuik.gov.tr/Kurumsal/UlusalVeriYayimlamaTakvimi")
base="https://veriportali.tuik.gov.tr"
get("vp_robots.txt",base+"/robots.txt")
urls=set()
if r is not None and r.ok:
    base=re.match(r"https://[^/]+",r.url).group(0)
    for j in re.findall(r'src="(/assets/[^"]+\.js)"',r.text):
        jr=get("vp_bundle.js",base+j)
        t=jr.text
        urls|=set(re.findall(r'["`\'](https?://[^"`\'\s]{5,150})["`\']',t))
        urls|=set(re.findall(r'["`\'](/(?:api|Api|API)/[^"`\'\s]{0,150})["`\']',t))
        ctx=[t[max(0,m.start()-300):m.end()+400] for m in re.finditer(r'[Tt]akvim|VeriYayimlama|Calendar',t)][:25]
        open(f"{O}/takvim_ctx.txt","w").write("\n-----\n".join(ctx))
        chunks=sorted(set(re.findall(r'(?:\./|assets/)([\w.-]+\.js)',t)))
        print("chunks",len(chunks)); print([c for c in chunks if re.search('akvim|alendar|Kurumsal|Yayim',c,re.I)])
        for c in [c for c in chunks if re.search('akvim|alendar|Kurumsal|Yayim',c,re.I)][:6]:
            cr=get("chunk_"+c,base+"/assets/"+c)
            if cr is not None and cr.ok:
                urls|=set(re.findall(r'["`\'](/[A-Za-z]+/[^"`\'\s]{0,150})["`\']',cr.text))
                urls|=set(re.findall(r'["`\'](https?://[^"`\'\s]{5,150})["`\']',cr.text))
print("URLS:"); [print("  ",u) for u in sorted(urls)]
# IMF DSBB
r=get("imf.html","https://dsbb.imf.org/sdds/advance-release-calendar/country/TUR")
if r is not None:
    for j in re.findall(r'src="([^"]+\.js)"',r.text)[:6]:
        u=j if j.startswith("http") else "https://dsbb.imf.org/"+j.lstrip("/")
        jr=get(None,u)
        if jr is not None and jr.ok:
            for m in set(re.findall(r'["\'](/?api/[^"\'\s]{0,120}|https?://[^"\'\s]*api[^"\'\s]{0,120})["\']',jr.text)): print("  IMF api:",m)
for u in ["https://dsbb.imf.org/api/sdds/arc/TUR","https://dsbb.imf.org/api/arc/country/TUR","https://dsbb.imf.org/api/v1/arc/TUR"]:
    r=get(None,u); 
    if r is not None: print("   ",r.text[:300])
