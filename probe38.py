import requests, re, os, json
UA={"User-Agent":"Mozilla/5.0 (piyasa-radari takvim yoklamasi; github.com/gptrade/piyasa-radari)","Accept-Language":"tr-TR,tr;q=0.9"}
O="probe38"; os.makedirs(O,exist_ok=True)
s=requests.Session(); s.headers.update(UA)
def get(name,url,**kw):
    try:
        r=s.get(url,timeout=40,**kw)
        print(f"== {name} {url} -> {r.status_code} {r.headers.get('content-type')} {len(r.content)}B final={r.url}")
        open(f"{O}/{name}","wb").write(r.content)
        return r
    except Exception as e:
        print(f"== {name} {url} -> ERR {e}")
for h in ["www.turkiye.gov.tr","www.tuik.gov.tr","data.tuik.gov.tr","www.tcmb.gov.tr","evds3.tcmb.gov.tr","www.bddk.org.tr","www.hmb.gov.tr","www.spk.gov.tr"]:
    r=get(f"robots_{h}.txt",f"https://{h}/robots.txt")
    if r is not None and r.status_code==200: print(r.text[:1500])
r=get("tg.html","https://www.turkiye.gov.tr/tuik-ulusal-veri-yayimlama-takvimi")
if r is not None:
    t=r.text
    print("forms:",re.findall(r"<form[^>]*>",t)[:5])
    print("selects:",re.findall(r"<select[^>]*name=\"([^\"]+)\"",t))
    print("options sample:",re.findall(r"<option[^>]*value=\"([^\"]*)\"[^>]*>([^<]*)<",t)[:60])
    print("pagination:",re.findall(r"href=\"([^\"]*(?:sayfa|page|Sayfa)[^\"]*)\"",t)[:10])
    print("rows:",t.count("<tr"))
for name,url in [("tuik_home.html","https://www.tuik.gov.tr/"),("dtuik_home.html","https://data.tuik.gov.tr/"),
                 ("dtuik_takvim.html","https://data.tuik.gov.tr/Kurumsal/UlusalVeriYayimlamaTakvimi"),
                 ("dtuik_takvim2.html","https://data.tuik.gov.tr/Bulten/Takvim"),
                 ("tcmb_takvim.html","https://www.tcmb.gov.tr/wps/wcm/connect/TR/TCMB+TR/Main+Menu/Istatistikler/Veri+Yayimlama+Takvimi"),]:
    r=get(name,url)
    if r is not None and r.ok:
        links=set(re.findall(r"href=\"([^\"]*(?:[Tt]akvim|[Cc]alendar|Yayim|yayim)[^\"]*)\"",r.text))
        print("  takvim links:",list(links)[:25])
