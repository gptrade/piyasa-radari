import requests, re, os, json
UA={"User-Agent":"Mozilla/5.0 (piyasa-radari takvim yoklamasi; github.com/gptrade/piyasa-radari)","Accept-Language":"tr-TR,tr;q=0.9"}
O="probe39"; os.makedirs(O,exist_ok=True)
s=requests.Session(); s.headers.update(UA)
def get(name,url,**kw):
    try:
        r=s.get(url,timeout=60,**kw)
        print(f"== {name} {url} -> {r.status_code} {r.headers.get('content-type')} {len(r.content)}B final={r.url}")
        if name: open(f"{O}/{name}","wb").write(r.content)
        return r
    except Exception as e:
        print(f"== {name} {url} -> ERR {e}")
# TÜİK veri portalı bundle → API uçları
r=get("vp_robots.txt","https://veriportali.tuik.gov.tr/robots.txt"); 
if r is not None: print(r.text[:500])
r=get("vp_index.html","https://veriportali.tuik.gov.tr/Kurumsal/UlusalVeriYayimlamaTakvimi")
js=re.findall(r'src="(/assets/[^"]+\.js)"',r.text) if r is not None else []
seen=set()
for j in js:
    jr=get("vp_bundle.js","https://veriportali.tuik.gov.tr"+j)
    if jr is None: continue
    t=jr.text
    for m in re.findall(r'["`](https?://[^"`\s]{5,120})["`]',t): seen.add(m)
    for m in re.findall(r'["`](/(?:api|Api|API)[^"`\s]{0,120})["`]',t): seen.add(m)
    ctx=[t[max(0,m.start()-200):m.end()+300] for m in re.finditer(r'[Tt]akvim',t)][:15]
    open(f"{O}/takvim_ctx.txt","w").write("\n-----\n".join(ctx))
    chunks=re.findall(r'"(\./[^"]+\.js|assets/[^"]+\.js)"',t)
    print("chunks:",len(chunks), [c for c in chunks if re.search('akvim|alendar',c,re.I)])
    for c in [c for c in chunks if re.search('akvim|alendar|Kurumsal',c,re.I)][:5]:
        cr=get(None,"https://veriportali.tuik.gov.tr/assets/"+c.split("/")[-1])
        if cr is not None and cr.ok:
            open(f"{O}/chunk_{c.split('/')[-1]}","w").write(cr.text)
            for m in re.findall(r'["`](/[A-Za-z]+/[^"`\s]{0,120})["`]',cr.text): seen.add(m)
print("URLS:"); [print("  ",u) for u in sorted(seen)]
# TCMB olay takvimi ve İngilizce veri takvimi
get("tcmb_duyuru_takvim.html","https://www.tcmb.gov.tr/wps/wcm/connect/TR/TCMB+TR/Main+Menu/Duyurular/Takvim")
get("tcmb_en_cal.html","https://www.tcmb.gov.tr/wps/wcm/connect/EN/TCMB+EN/Main+Menu/Statistics/Data+Release+Calendar")
# IMF DSBB ARC
for n,u in [("imf_arc.html","https://dsbb.imf.org/sdds/advance-release-calendar/country/TUR"),
            ("imf_arc2.html","https://dsbb.imf.org/sdds/arc/country/TUR"),("imf_robots.txt","https://dsbb.imf.org/robots.txt")]:
    r=get(n,u)
    if r is not None and n.endswith("txt"): print(r.text[:400])
