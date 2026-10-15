"""rapor@<alan adı> e-posta kutusu kurulumu (tekrar çalıştırılabilir): Cloudflare Email Routing → rapor-posta Worker.

Worker'ı iş akışındaki wrangler adımı yükler; bu betik Email Routing'i açar ve adresi Worker'a bağlayan kuralı kurar.
Gizli bilgi yazmaz: yalnız durum özeti üretir.
Ortam: CLOUDFLARE_API_TOKEN, CF_DOMAIN, RAPOR_ADRES (ör. rapor), RAPOR_WORKER (ör. rapor-posta)
"""
import json
import os
import sys
import time

import requests

API = "https://api.cloudflare.com/client/v4"
H = {"Authorization": f"Bearer {os.environ['CLOUDFLARE_API_TOKEN'].strip()}", "Content-Type": "application/json"}
DOMAIN = os.environ.get("CF_DOMAIN", "lyracube.com")
ADDR = f"{os.environ.get('RAPOR_ADRES', 'rapor')}@{DOMAIN}"
WORKER = os.environ.get("RAPOR_WORKER", "rapor-posta")
st: dict = {"adres": ADDR}


def cf(method, path, **kw):
    for attempt in range(4):
        r = requests.request(method, API + path, headers=H, timeout=60, **kw)
        if r.status_code != 429:
            break
        time.sleep(20 * (attempt + 1))
    try:
        j = r.json()
    except ValueError:
        j = {"success": False, "errors": [{"message": f"HTTP {r.status_code}"}]}
    if not j.get("success"):
        return None, "; ".join(f"{e.get('code', '')} {e.get('message', '')}" for e in j.get("errors") or [])[:300]
    return j.get("result"), None


def main():
    z, err = cf("GET", "/zones", params={"name": DOMAIN})
    if err or not z:
        st["alan_adi"] = f"bulunamadı: {err}"
        return
    zid = z[0]["id"]
    st["alan_adi"] = z[0]["status"]

    s, err = cf("GET", f"/zones/{zid}/email/routing")
    if err:
        st["routing"] = f"okunamadı: {err} (token'a 'Email Routing Rules: Edit' ve 'Zone Settings: Edit' gerekir)"
        return
    if not s.get("enabled"):
        _, e1 = cf("POST", f"/zones/{zid}/email/routing/dns", json={})
        _, e2 = cf("POST", f"/zones/{zid}/email/routing/enable", json={})
        s, _ = cf("GET", f"/zones/{zid}/email/routing")
        if not (s or {}).get("enabled"):
            st["routing"] = f"açılamadı: {e1 or e2 or 'bilinmiyor'} → panelden Email → Email Routing → Enable"
            return
    st["routing"] = {"acik": s.get("enabled"), "durum": s.get("status")}
    dns, _ = cf("GET", f"/zones/{zid}/email/routing/dns")
    if isinstance(dns, list):
        st["dns_kayit"] = len(dns)
    elif isinstance(dns, dict):
        st["dns_hata"] = [e.get("code") for e in dns.get("errors") or []][:5]

    rule = {"name": "Rapor kutusu", "enabled": True, "priority": 0,
            "matchers": [{"type": "literal", "field": "to", "value": ADDR}],
            "actions": [{"type": "worker", "value": [WORKER]}]}
    rules, err = cf("GET", f"/zones/{zid}/email/routing/rules", params={"per_page": 50})
    if err:
        st["kural"] = f"okunamadı: {err}"
        return
    cur = next((r for r in rules if any(m.get("value") == ADDR for m in r.get("matchers") or [])), None)
    if cur:
        _, err = cf("PUT", f"/zones/{zid}/email/routing/rules/{cur['tag']}", json=rule)
    else:
        _, err = cf("POST", f"/zones/{zid}/email/routing/rules", json=rule)
    st["kural"] = f"hata: {err}" if err else "tamam"


try:
    main()
except Exception as e:  # noqa: BLE001
    st["hata"] = f"{type(e).__name__}: {str(e)[:200]}"
json.dump(st, open(sys.argv[1] if len(sys.argv) > 1 else "status.json", "w"), ensure_ascii=False, indent=1)
