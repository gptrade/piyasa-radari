import requests, re, os, time
UA={"User-Agent":"Mozilla/5.0 (piyasa-radari takvim yoklamasi; github.com/gptrade/piyasa-radari)","Accept-Language":"tr-TR,tr;q=0.9"}
O="probe42"; os.makedirs(O,exist_ok=True)
s=requests.Session(); s.headers.update(UA)
B="https://veriportali.tuik.gov.tr/assets/"
todo=["main-C0Z3qMtl.js"]; done=set(); hits=[]; urls=set()
while todo and len(done)<120:
    c=todo.pop(0)
    if c in done: continue
    done.add(c)
    try: r=s.get(B+c,timeout=60)
    except Exception as e: print("ERR",c,e); continue
    t=r.text
    for n in re.findall(r'["\'`/]([\w-]+-[\w-]{8}\.js)',t):
        if n not in done: todo.append(n)
    if re.search(r'[Tt]akvim|VeriYayimlama|UlusalVeri',t):
        hits.append(c); open(f"{O}/{c}","w").write(t)
    for m in re.findall(r'["\'`]((?:https?://[\w.-]+)?/(?:api|Api|API|odata|service|Service)[^"\'`\s]{0,160})["\'`]',t): urls.add((c,m))
    for m in re.findall(r'["\'`](https?://[\w.-]+\.(?:gov\.tr|tuik[\w.]*)[^"\'`\s]{0,160})["\'`]',t): urls.add((c,m))
    time.sleep(0.3)
print("chunks",len(done),"hits",hits)
for c,u in sorted(urls): print(c,u)
for c in hits:
    t=open(f"{O}/{c}").read()
    for m in list(re.finditer(r'[Tt]akvim|UlusalVeri',t))[:12]:
        print("---",c, t[max(0,m.start()-250):m.end()+350].replace("\n"," "))
r=s.get("https://veriportali.tuik.gov.tr/sitemap.xml",timeout=60); print("sitemap",r.status_code,len(r.content)); open(f"{O}/sitemap.xml","wb").write(r.content)
