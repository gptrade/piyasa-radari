import io, zipfile, requests
UA = {"User-Agent": "Mozilla/5.0 piyasa-radari/1.0 (+https://github.com/gptrade/piyasa-radari)"}
D = "20261120"
def get(name):
    for base in ("https://www.borsaistanbul.com/data/viopdata/", "https://borsaistanbul.com/data/viopdata/"):
        r = requests.get(base + name, headers=UA, timeout=40)
        print(name, base, r.status_code, len(r.content), r.headers.get("content-type"))
        if r.status_code == 200 and len(r.content) > 100:
            return r.content
def text(b):
    if b[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(b)); print("  zip:", z.namelist()); b = z.read(z.namelist()[0])
    for enc in ("utf-8", "cp1254", "latin-1"):
        try: return b.decode(enc)
        except UnicodeDecodeError: pass
for name, show in (("viop_%s.csv" % D, "XU030"), ("viopgs_%s.csv" % D, None), ("viopishac_%s.zip" % D, None), ("viopms_%s.csv" % D, "XU030"), ("viopyyishac202610.zip", None)):
    b = get(name)
    if not b: continue
    t = text(b); lines = t.splitlines()
    print("  satir", len(lines)); print("  ", lines[:3] if not show else lines[:2])
    if show:
        for l in lines:
            if show in l and ("1226" in l or "0227" in l or "Aralık" in l or "D_XU030" in l): print("   >", l[:400])
    else:
        print("  ornek:", [l[:300] for l in lines[2:6]])
