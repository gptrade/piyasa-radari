import requests, re, os, time
UA={"User-Agent":"Mozilla/5.0 (piyasa-radari takvim yoklamasi; github.com/gptrade/piyasa-radari)","Accept-Language":"tr-TR,tr;q=0.9"}
O="probe44"; os.makedirs(O,exist_ok=True)
s=requests.Session(); s.headers.update(UA)
def get(name,url,show=0,**kw):
    for a in range(2):
        try:
            r=s.get(url,timeout=90,**kw)
            print(f"== {name} {url} -> {r.status_code} {r.headers.get('content-type')} {len(r.content)}B final={r.url}")
            if name: open(f"{O}/{name}","wb").write(r.content)
            if show: print(r.text[:show])
            links=sorted(set(re.findall(r'href="([^"]*(?:[Tt]akvim|[Cc]alendar|Takvimi|takvimi)[^"]*)"',r.text)))
            if links: print("  takvim links:",links[:30])
            return r
        except Exception as e:
            print(f"== {name} {url} -> ERR {e}"); time.sleep(5)
get("ri_robots.txt","https://www.resmiistatistik.gov.tr/robots.txt",600)
get("ri_home.html","https://www.resmiistatistik.gov.tr/")
for p in ["/takvim","/veri-yayimlama-takvimi","/Takvim","/tr/takvim"]:
    get(None,"https://www.resmiistatistik.gov.tr"+p)
get("tuik_robots.txt","https://www.tuik.gov.tr/robots.txt",400)
get("tuik_home.html","https://www.tuik.gov.tr/")
get("tuik_uvyt.html","https://www.tuik.gov.tr/Kurumsal/Ulusal_Veri_Yayimlama_Takvimi")
