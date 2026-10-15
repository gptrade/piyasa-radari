import requests, os, json
os.makedirs("probe50", exist_ok=True)
out={}
for u in ["https://piyasa-radari.pages.dev/","https://piyasa-radari.pages.dev/data/feed.json","https://radar.lyracube.com/","https://radar.lyracube.com/data/feed.json"]:
    try:
        r=requests.get(u,timeout=30,allow_redirects=False); out[u]=[r.status_code, r.headers.get("location","")[:80], len(r.content)]
    except Exception as e: out[u]=str(e)[:120]
print(json.dumps(out,indent=1))
