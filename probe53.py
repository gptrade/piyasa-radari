import requests, re, os
os.makedirs("probe53", exist_ok=True)
UA={"User-Agent":"Mozilla/5.0 (piyasa-radari takvim yoklamasi)"}
for u in ["https://earningshub.com/terms","https://earningshub.com/terms-of-service","https://earningshub.com/tos"]:
    r=requests.get(u,headers=UA,timeout=30); t=re.sub(r"<script.*?</script>|<style.*?</style>","",r.text,flags=re.S); t=re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",t))
    print("==",u,r.status_code,len(t)); print(t[:6000])
    links=set(re.findall(r'href="([^"]*(?:term|legal|api|developer)[^"]*)"',r.text,re.I)); print("links",links)
