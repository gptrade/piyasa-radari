import io, zipfile, requests, re, datetime as dt
UA = {"User-Agent": "Mozilla/5.0 piyasa-radari/1.0 (+https://github.com/gptrade/piyasa-radari)"}
r = requests.get("https://borsaistanbul.com/files/datafilepaths_viop.zip", headers=UA, timeout=40)
print("paths", r.status_code, len(r.content))
z = zipfile.ZipFile(io.BytesIO(r.content))
for n in z.namelist():
    t = z.read(n).decode("utf-8", "replace")
    print("==", n); print(t[:3000])
