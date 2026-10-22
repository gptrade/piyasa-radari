"""Kapalı grup sitesi kurulumu (tek seferlik, tekrar çalıştırılabilir): Cloudflare API.

- Pages projesine özel alan adı (radar.<alan adı>) + DNS CNAME
- Cloudflare Access uygulaması: özel alan adı ve *.pages.dev adresleri; izin yalnız CF_ACCESS_EMAILS listesine
- E-posta kodu (one-time PIN) giriş yöntemi
Kayıtlara gizli bilgi yazmaz: yalnız durum özeti (status.json) üretir.
Ortam: CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID, CF_ACCESS_EMAILS (virgülle), CF_DOMAIN, CF_SUB, CF_PROJECT
"""
import json
import os
import sys

import requests

API = "https://api.cloudflare.com/client/v4"
H = {"Authorization": f"Bearer {os.environ['CLOUDFLARE_API_TOKEN'].strip()}", "Content-Type": "application/json"}
ACC = os.environ["CLOUDFLARE_ACCOUNT_ID"].strip()
DOMAIN = os.environ.get("CF_DOMAIN", "lyracube.com")
HOST = f"{os.environ.get('CF_SUB', 'radar')}.{DOMAIN}"
PROJECT = os.environ.get("CF_PROJECT", "piyasa-radari")
EMAILS = [e.strip().lower() for e in os.environ.get("CF_ACCESS_EMAILS", "").split(",") if "@" in e]
APP_NAME = "Lyra Radar"
OLD_NAMES = ("Piyasa Radarı",)              # yeniden adlandırma: eski adlı uygulama bulunup bu ada çevrilir (kopya açılmaz)
st: dict = {"host": HOST}


def cf(method, path, **kw):
    import time
    for attempt in range(4):
        r = requests.request(method, API + path, headers=H, timeout=60, **kw)
        if r.status_code != 429:
            break
        time.sleep(20 * (attempt + 1))
    time.sleep(1)
    try:
        j = r.json()
    except ValueError:
        j = {"success": False, "errors": [{"message": f"HTTP {r.status_code}"}]}
    if not j.get("success"):
        return None, "; ".join(f"{e.get('code', '')} {e.get('message', '')}" for e in j.get("errors") or [])[:300]
    return j.get("result"), None


def step(name, fn):
    try:
        st[name] = fn()
    except Exception as e:  # noqa: BLE001
        st[name] = f"hata: {type(e).__name__}: {str(e)[:200]}"


def token():
    tok = os.environ.get("CLOUDFLARE_API_TOKEN", "")
    out = {"uzunluk": len(tok), "bosluk": tok != tok.strip(), "hesap_id_uzunluk": len(ACC.strip()),
           "hesap_id_hex": all(c in "0123456789abcdef" for c in ACC.strip().lower())}
    res, err = cf("GET", "/user/tokens/verify")
    if err:
        res, err2 = cf("GET", f"/accounts/{ACC.strip()}/tokens/verify")
        if err2:
            out["durum"] = "geçersiz"; out["hata"] = err; out["hata_hesap"] = err2
            return out
    out["durum"] = res.get("status")
    return out


def zone():
    res, err = cf("GET", "/zones", params={"name": DOMAIN})
    if err or not res:
        return {"durum": "bulunamadı", "hata": err}
    z = res[0]
    st["_zid"] = z["id"]
    return {"durum": z["status"], "ns": z.get("name_servers")}


def project():
    res, err = cf("GET", f"/accounts/{ACC}/pages/projects/{PROJECT}")
    if err:
        return {"durum": "yok", "hata": err}
    st["_sub"] = res["subdomain"]
    return {"durum": "var", "pages_dev": res["subdomain"], "domains": res.get("domains")}


def pages_domain():
    res, _ = cf("GET", f"/accounts/{ACC}/pages/projects/{PROJECT}/domains")
    have = {d["name"]: d for d in res or []}
    if HOST not in have:
        r, err = cf("POST", f"/accounts/{ACC}/pages/projects/{PROJECT}/domains", json={"name": HOST})
        if err:
            return {"durum": "eklenemedi", "hata": err}
        have[HOST] = r
    d = have[HOST]
    return {"durum": d.get("status"), "dogrulama": (d.get("validation_data") or {}).get("status")}


def dns():
    zid, sub = st.get("_zid"), st.get("_sub")
    if not zid or not sub:
        return "atlandı (alan adı ya da proje yok)"
    res, err = cf("GET", f"/zones/{zid}/dns_records", params={"name": HOST})
    if err:
        return {"hata": err}
    body = {"type": "CNAME", "name": HOST, "content": sub, "proxied": True, "ttl": 1, "comment": "Lyra Radar (Cloudflare Pages)"}
    if res:
        rec = res[0]
        if rec["type"] == "CNAME" and rec["content"] == sub and rec.get("proxied"):
            return "var"
        _, err = cf("PUT", f"/zones/{zid}/dns_records/{rec['id']}", json=body)
        return "güncellendi" if not err else {"hata": err}
    _, err = cf("POST", f"/zones/{zid}/dns_records", json=body)
    return "eklendi" if not err else {"hata": err}


def otp():
    res, err = cf("GET", f"/accounts/{ACC}/access/identity_providers")
    if err:
        return {"hata": err}
    if any(p.get("type") == "onetimepin" for p in res or []):
        return "var"
    _, err = cf("POST", f"/accounts/{ACC}/access/identity_providers", json={"name": "E-posta kodu", "type": "onetimepin", "config": {}})
    return "eklendi" if not err else {"hata": err}


def access():
    sub = st.get("_sub")
    if not EMAILS:
        return "atlandı (CF_ACCESS_EMAILS secret'ı yok)"
    domains = [HOST] + ([sub, f"*.{sub}"] if sub else [])
    res, err = cf("GET", f"/accounts/{ACC}/access/apps")
    if err:
        return {"hata": err}
    app = next((a for a in res or [] if a.get("name") in (APP_NAME, *OLD_NAMES)), None)
    body = {"name": APP_NAME, "type": "self_hosted", "domain": HOST, "self_hosted_domains": domains,
            "session_duration": "720h", "app_launcher_visible": True, "auto_redirect_to_identity": False}
    if app:
        app, err = cf("PUT", f"/accounts/{ACC}/access/apps/{app['id']}", json=body)
    else:
        app, err = cf("POST", f"/accounts/{ACC}/access/apps", json=body)
    if err:
        return {"uygulama": "kurulamadı", "hata": err}
    pol = {"name": "Grup üyeleri", "decision": "allow", "precedence": 1,
           "include": [{"email": {"email": e}} for e in EMAILS]}
    pols, err = cf("GET", f"/accounts/{ACC}/access/apps/{app['id']}/policies")
    p = next((x for x in pols or [] if x.get("name") == pol["name"]), None)
    if p:
        _, err = cf("PUT", f"/accounts/{ACC}/access/apps/{app['id']}/policies/{p['id']}", json=pol)
    else:
        _, err = cf("POST", f"/accounts/{ACC}/access/apps/{app['id']}/policies", json=pol)
    return {"uygulama": "hazır", "korunan": domains, "izinli_kisi": len(EMAILS), "politika": "hazır" if not err else err}


def verify():
    out = {}
    for h in [HOST] + ([st["_sub"]] if st.get("_sub") else []):
        try:
            r = requests.get(f"https://{h}/", timeout=30, allow_redirects=False)
            loc = r.headers.get("location", "")
            out[h] = f"HTTP {r.status_code}" + (" → giriş ekranı" if "cloudflareaccess.com" in loc else (" → AÇIK (korumasız!)" if r.status_code == 200 else ""))
        except Exception as e:  # noqa: BLE001
            out[h] = f"erişilemedi ({type(e).__name__})"
    return out


step("anahtar", token)
if (st.get("anahtar") or {}).get("durum") != "active":
    json.dump({k: v for k, v in st.items() if not k.startswith("_")}, open(sys.argv[1] if len(sys.argv) > 1 else "status.json", "w"), ensure_ascii=False, indent=1)
    sys.exit(0)
for n, f in [("alan_adi", zone), ("pages_projesi", project), ("pages_ozel_alan", pages_domain), ("dns", dns),
             ("eposta_kodu", otp), ("access", access), ("dogrulama", verify)]:
    step(n, f)
st = {k: v for k, v in st.items() if not k.startswith("_")}
json.dump(st, open(sys.argv[1] if len(sys.argv) > 1 else "status.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps({k: (v if k in ("alan_adi",) else "…") for k, v in st.items()}, ensure_ascii=False))
