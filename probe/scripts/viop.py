import requests
UA = {"User-Agent": "Mozilla/5.0 piyasa-radari/1.0 (+https://github.com/gptrade/piyasa-radari)"}
r = requests.get("https://stockanalysis.com/robots.txt", headers=UA, timeout=30)
print(r.status_code); print(r.text[:4000])
