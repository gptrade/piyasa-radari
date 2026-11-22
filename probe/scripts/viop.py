import re, requests
UA = {"User-Agent": "Mozilla/5.0 piyasa-radari/1.0 (+https://github.com/gptrade/piyasa-radari)"}
for u in ["https://www.borsaistanbul.com/veriler/vadeli-islem-ve-opsiyon-piyasasi-verileri/bulten-ve-piyasa-verileri",
          "https://www.borsaistanbul.com/veriler/viop", "https://www.borsaistanbul.com/veriler/pay-piyasasi-verileri/bulten-verileri"]:
    r = requests.get(u, headers=UA, timeout=40)
    t = r.text
    print("==", u, r.status_code, len(t))
    for m in sorted(set(re.findall(r'["\'(]([^"\'()\s]*(?:viop|thb|data/|api/|\.zip|\.csv)[^"\'()\s]*)', t, re.I)))[:80]:
        print("  ", m[:200])
    for m in re.findall(r'.{120}(?:Günlük Bülteni|Üye Bazında).{300}', t)[:4]:
        print("  CTX", m)
