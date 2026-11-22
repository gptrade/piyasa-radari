import io, zipfile, requests
UA = {"User-Agent": "Mozilla/5.0 piyasa-radari/1.0 (+https://github.com/gptrade/piyasa-radari)"}
B = "https://www.borsaistanbul.com/data/vadeli/"
def get(name):
    r = requests.get(B + name, headers=UA, timeout=60)
    print("##", name, r.status_code, len(r.content))
    return r.content if r.status_code == 200 and len(r.content) > 200 else None
def text(b):
    if b[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(b)); print("  zip:", z.namelist()); b = z.read(z.namelist()[0])
    for enc in ("utf-8-sig", "cp1254"):
        try: return b.decode(enc)
        except UnicodeDecodeError: pass
    return b.decode("latin-1")
D = "20261120"
b = get(f"viop_{D}.csv")
if b:
    L = text(b).splitlines(); print("  satir", len(L)); print("  baslik:", L[0][:900]); print("  ", L[1][:600])
    for l in L:
        if "XU030" in l and ("1226" in l or "0227" in l) and l.startswith(("F_", "\"F_")): print("  >", l[:700])
        if "USDTRY" in l and l.startswith(("F_", "\"F_")) and ("1126" in l or "1226" in l or "0127" in l or "0627" in l): print("  $", l[:400])
for name in (f"viopgs_{D}.csv", f"viopishac_{D}.zip", f"viopms_{D}.csv", "viopyyishac202610.zip"):
    b = get(name)
    if not b: continue
    L = text(b).splitlines()
    print("  satir", len(L)); print("  baslik:", [l[:500] for l in L[:2]])
    hits = [l for l in L if "XU030" in l][:3]
    print("  XU030 ornek:", [h[:400] for h in hits])
    if "ishac" in name: print("  diger:", [l[:300] for l in L[2:5]])
