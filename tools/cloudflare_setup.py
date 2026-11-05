"""Kapalı grup sitesi kurulumu (tek seferlik, tekrar çalıştırılabilir): Cloudflare API.

- Pages projesine özel alan adı (radar.<alan adı>) + DNS CNAME
- Cloudflare Access uygulaması: özel alan adı ve *.pages.dev adresleri; izin yalnız CF_ACCESS_EMAILS listesine
- E-posta kodu (one-time PIN) giriş yöntemi
Kayıtlara gizli bilgi yazmaz: yalnız durum özeti (status.json) üretir.
Ortam: CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID, CF_ACCESS_EMAILS (virgülle), CF_DOMAIN, CF_SUB, CF_PROJECT
Kullanıcı yönetimi (isteğe bağlı): CF_USERS_TOKEN (Access grupları düzenleme yetkili anahtar), CF_ADMIN_EMAILS (yoksa
CF_ACCESS_EMAILS'in ilki). Anahtar varsa izinli kişiler "Lyra Radar kullanıcıları" Access grubunda tutulur ve sitedeki
Kullanıcılar sayfasından (functions/api/users.js) yönetilir; CF_ACCESS_EMAILS yalnız grubu ilk kez doldurur.
"""
import json
import os
import re
import sys

import requests

API = "https://api.cloudflare.com/client/v4"
H = {"Authorization": f"Bearer {os.environ['CLOUDFLARE_API_TOKEN'].strip()}", "Content-Type": "application/json"}
ACC = os.environ["CLOUDFLARE_ACCOUNT_ID"].strip()
DOMAIN = os.environ.get("CF_DOMAIN", "lyracube.com")
HOST = f"{os.environ.get('CF_SUB', 'radar')}.{DOMAIN}"
PROJECT = os.environ.get("CF_PROJECT", "piyasa-radari")
# virgül, noktalı virgül, boşluk ya da yeni satırla ayrılmış olabilir; tekrarlar ve hatalı biçimliler atılır
EMAILS = list(dict.fromkeys(e.strip().strip("<>\"'").lower() for e in re.split(r"[,;\s]+", os.environ.get("CF_ACCESS_EMAILS", ""))
                            if re.fullmatch(r"[^@\s<>\"']+@[^@\s<>\"']+\.[^@\s<>\"']+", e.strip().strip("<>\"'"))))
def clean_token(raw: str) -> str:
    """Gizli değişkene yanlışlıkla Cloudflare'in "test" komutu (curl … -H "Authorization: Bearer XXX") yapıştırılmış olabilir:
    'Bearer'dan sonraki parçayı al; yoksa tek parça olmalı (boşluk/tırnak içermeyen)."""
    raw = (raw or "").strip()
    m = re.search(r"Bearer\s+([A-Za-z0-9_\-.]{20,})", raw)
    if m:
        return m.group(1)
    return raw if re.fullmatch(r"[A-Za-z0-9_\-.]{20,}", raw) else ""


def redact(text: str) -> str:
    """Hata metinlerinde anahtar benzeri dizileri ve Authorization başlıklarını gizle (durum dosyası herkese açık dalda)."""
    text = re.sub(r"(?i)(bearer|authorization)[^,;}\]]*", r"\1 [gizlendi]", str(text))
    return re.sub(r"[A-Za-z0-9_\-]{24,}", "[gizlendi]", text)


UTOK_RAW = os.environ.get("CF_USERS_TOKEN", "")
UTOK = clean_token(UTOK_RAW)
ADMINS = [e.strip().lower() for e in re.split(r"[,;\s]+", os.environ.get("CF_ADMIN_EMAILS", "")) if "@" in e] or EMAILS[:1]
GROUP_NAME = "Lyra Radar kullanıcıları"
APP_NAME = "Lyra Radar"
OLD_NAMES = ("Piyasa Radarı",)              # yeniden adlandırma: eski adlı uygulama bulunup bu ada çevrilir (kopya açılmaz)
st: dict = {"host": HOST}


def mask(e: str) -> str:
    """Durum dosyası herkese açık dalda: e-postayı maskele (g***@alan.com)."""
    u, _, d = e.partition("@")
    return f"{u[:1]}***@{d}"


def cf(method, path, tok=None, **kw):
    import time
    hd = {**H, "Authorization": f"Bearer {tok}"} if tok else H
    for attempt in range(4):
        r = requests.request(method, API + path, headers=hd, timeout=60, **kw)
        if r.status_code != 429:
            break
        time.sleep(20 * (attempt + 1))
    time.sleep(1)
    try:
        j = r.json()
    except ValueError:
        j = {"success": False, "errors": [{"message": f"HTTP {r.status_code}"}]}
    if not j.get("success"):
        return None, redact("; ".join(f"{e.get('code', '')} {e.get('message', '')}" for e in j.get("errors") or []))[:300]
    return j.get("result"), None


def step(name, fn):
    try:
        st[name] = fn()
    except Exception as e:  # noqa: BLE001
        st[name] = f"hata: {type(e).__name__}: {redact(str(e))[:200]}"


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
    st["_aud"] = app.get("aud")
    include, grp = [{"email": {"email": e}} for e in EMAILS], None
    if UTOK:                                       # kişiler Access grubunda; sitedeki Kullanıcılar sayfası grubu düzenler
        gs, gerr = cf("GET", f"/accounts/{ACC}/access/groups", tok=UTOK)
        g = next((x for x in gs or [] if x.get("name") == GROUP_NAME), None)
        if g is None and not gerr:                 # ilk kez: CF_ACCESS_EMAILS ile doldur
            g, gerr = cf("POST", f"/accounts/{ACC}/access/groups", tok=UTOK, json={"name": GROUP_NAME, "include": include})
        elif g:                                    # var olan grup: üyeliğe dokunma, yalnız yöneticiler eksikse ekle
            have = {(x.get("email") or {}).get("email", "").lower() for x in g.get("include") or []}
            miss = [a for a in ADMINS if a not in have]
            if miss:
                g, gerr = cf("PUT", f"/accounts/{ACC}/access/groups/{g['id']}", tok=UTOK,
                             json={"name": GROUP_NAME, "include": (g.get("include") or []) + [{"email": {"email": a}} for a in miss]})
        if g and not gerr:
            grp = g
            st["_group"] = g["id"]
            include = [{"group": {"id": g["id"]}}]
        else:
            st["_group_err"] = gerr
    pol = {"name": "Grup üyeleri", "decision": "allow", "precedence": 1, "include": include}
    pols, err = cf("GET", f"/accounts/{ACC}/access/apps/{app['id']}/policies")
    p = next((x for x in pols or [] if x.get("name") == pol["name"]), None)
    if p:
        _, err = cf("PUT", f"/accounts/{ACC}/access/apps/{app['id']}/policies/{p['id']}", json=pol)
    else:
        _, err = cf("POST", f"/accounts/{ACC}/access/apps/{app['id']}/policies", json=pol)
    n = len((grp or {}).get("include") or []) if grp else len(EMAILS)
    return {"uygulama": "hazır", "korunan": domains, "izinli_kisi": n, "politika": "hazır" if not err else err,
            "kisi_yonetimi": ("Access grubu (sitedeki Kullanıcılar sayfası)" if grp else
                              f"e-posta listesi (CF_USERS_TOKEN {'hatası: ' + str(st.get('_group_err')) if UTOK else ('biçimi geçersiz: yalnız anahtarın kendisini yapıştır' if UTOK_RAW.strip() else 'yok')})"),
            "yonetici": [mask(a) for a in ADMINS]}


def pages_env():
    """İzleme listesini web'den düzenleme (functions/api/watchlist.js) için Pages ortam değişkenleri.
    ACCESS_AUD/ACCESS_TEAM: Access JWT doğrulaması; GH_REPO; GH_TOKEN (gizli): WATCHLIST_TOKEN secret'ı varsa.
    Değişkenler bir sonraki Pages dağıtımında (radar turu) geçerli olur."""
    aud = st.get("_aud")
    org, err = cf("GET", f"/accounts/{ACC}/access/organizations")
    team = (org or {}).get("auth_domain")
    if not team:                                   # anahtarda Access-kuruluş okuma yetkisi yoksa: giriş yönlendirmesinden
        try:
            loc = requests.get(f"https://{HOST}/", timeout=30, allow_redirects=False).headers.get("location", "")
            m = re.match(r"https://([a-z0-9-]+\.cloudflareaccess\.com)/", loc)
            team = m.group(1) if m else None
            err = None if team else err
        except Exception:  # noqa: BLE001
            pass
    if not aud or not team:
        return {"hata": err or "Access uygulaması/ekip alan adı bulunamadı"}
    env = {"ACCESS_AUD": {"type": "plain_text", "value": aud}, "ACCESS_TEAM": {"type": "plain_text", "value": team},
           "GH_REPO": {"type": "plain_text", "value": os.environ.get("GH_REPO", "gptrade/piyasa-radari")}}
    if UTOK and st.get("_group"):
        env |= {"CF_ACCOUNT_ID": {"type": "plain_text", "value": ACC}, "ACCESS_GROUP_ID": {"type": "plain_text", "value": st["_group"]},
                "ADMIN_EMAILS": {"type": "plain_text", "value": ",".join(ADMINS)}, "CF_USERS_TOKEN": {"type": "secret_text", "value": UTOK}}
    tok = os.environ.get("WATCHLIST_TOKEN", "").strip()
    if tok:
        env["GH_TOKEN"] = {"type": "secret_text", "value": tok}
    _, err = cf("PATCH", f"/accounts/{ACC}/pages/projects/{PROJECT}",
                json={"deployment_configs": {"production": {"env_vars": env}, "preview": {"env_vars": env}}})
    return {"durum": "hazır" if not err else err, "ekip": team, "github_yazma_anahtari": "var" if tok else "YOK (WATCHLIST_TOKEN secret'ı ekle)",
            "kullanici_yonetimi": "hazır" if "CF_USERS_TOKEN" in env else "kapalı (ayrıntı: access → kisi_yonetimi)"}


REDIR_LIST = "lyra_radar_pagesdev"


def pagesdev_redirect():
    """*.pages.dev → özel alan adı (Cloudflare Bulk Redirects; Pages belgelerinde önerilen yöntem). Kimse pages.dev adresinde
    giriş yapmaya çalışmasın: bazı ağlar *.pages.dev'i engelliyor ve giriş sonrası dönüş orada kopuyor.
    Yol ve sorgu korunur, önizleme alt alan adları (*.piyasa-radari.pages.dev) da yönlenir. Yetki: Account Filter Lists +
    Account Rulesets (düzenleme); ana anahtarda yoksa kullanıcı anahtarıyla denenir."""
    sub = st.get("_sub")
    if not sub:
        return "atlandı (pages.dev adı bilinmiyor)"
    item = {"redirect": {"source_url": f"{sub}/", "target_url": f"https://{HOST}/", "status_code": 301, "include_subdomains": True,
                         "subpath_matching": True, "preserve_path_suffix": True, "preserve_query_string": True}}
    last = None
    for tok in [None] + ([UTOK] if UTOK else []):
        lists, err = cf("GET", f"/accounts/{ACC}/rules/lists", tok=tok)
        if err:
            last = err
            continue
        lst = next((x for x in lists or [] if x.get("name") == REDIR_LIST), None)
        if not lst:
            lst, err = cf("POST", f"/accounts/{ACC}/rules/lists", tok=tok, json={"name": REDIR_LIST, "kind": "redirect", "description": "Lyra Radar: pages.dev → özel alan adı"})
            if err:
                last = err
                continue
        # listeyi tek kayda indir (PUT tüm öğeleri değiştirir)
        _, err = cf("PUT", f"/accounts/{ACC}/rules/lists/{lst['id']}/items", tok=tok, json=[item])
        if err:
            last = err
            continue
        rs, err = cf("GET", f"/accounts/{ACC}/rulesets/phases/http_request_redirect/entrypoint", tok=tok)
        rules = [r for r in (rs or {}).get("rules") or [] if REDIR_LIST not in (r.get("expression") or "")]
        rules.append({"expression": f"http.request.full_uri in ${REDIR_LIST}", "description": "Lyra Radar pages.dev yönlendirmesi",
                      "action": "redirect", "action_parameters": {"from_list": {"name": REDIR_LIST, "key": "http.request.full_uri"}}})
        _, err = cf("PUT", f"/accounts/{ACC}/rulesets/phases/http_request_redirect/entrypoint", tok=tok,
                    json={"name": "default", "kind": "root", "phase": "http_request_redirect", "rules": rules})
        if err:
            last = err
            continue
        return {"durum": "hazır", "anahtar": "ana" if tok is None else "kullanıcı", "hedef": f"https://{HOST}/"}
    return {"hata": last, "cozum": "Cloudflare anahtarına 'Account Filter Lists: Edit' ve 'Account Rulesets: Edit' (hesap) izinlerini ekle"}


def verify():
    out = {}
    for h in [HOST] + ([st["_sub"]] if st.get("_sub") else []):
        try:
            r = requests.get(f"https://{h}/", timeout=30, allow_redirects=False)
            loc = r.headers.get("location", "")
            out[h] = f"HTTP {r.status_code}" + (" → giriş ekranı" if "cloudflareaccess.com" in loc else f" → {HOST}" if HOST in loc else (" → AÇIK (korumasız!)" if r.status_code == 200 else ""))
        except Exception as e:  # noqa: BLE001
            out[h] = f"erişilemedi ({type(e).__name__})"
    return out


step("anahtar", token)
if (st.get("anahtar") or {}).get("durum") != "active":
    json.dump({k: v for k, v in st.items() if not k.startswith("_")}, open(sys.argv[1] if len(sys.argv) > 1 else "status.json", "w"), ensure_ascii=False, indent=1)
    sys.exit(0)
for n, f in [("alan_adi", zone), ("pages_projesi", project), ("pages_ozel_alan", pages_domain), ("dns", dns),
             ("eposta_kodu", otp), ("access", access), ("pages_ortam", pages_env), ("pagesdev_yonlendirme", pagesdev_redirect), ("dogrulama", verify)]:
    step(n, f)
st = {k: v for k, v in st.items() if not k.startswith("_")}
json.dump(st, open(sys.argv[1] if len(sys.argv) > 1 else "status.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps({k: (v if k in ("alan_adi",) else "…") for k, v in st.items()}, ensure_ascii=False))
