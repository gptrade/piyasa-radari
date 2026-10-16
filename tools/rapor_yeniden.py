"""Rapor kutusundaki bir raporu yeniden okutur: data dalındaki "okundu" listesinden ve kayıtlardan çıkarır.

Radar her turda data dalını baştan yazar (tek commit, zorla gönderim); bu yüzden değişiklik bir radar turu
sırasında yapılırsa ezilebilir. Betik değişikliği uygular, sonraki radar turunun bitmesini bekler ve rapor
yeniden okunmuş ya da sıraya girmiş görünene kadar (en fazla birkaç deneme) tekrarlar.
Ortam: RID (rapor-… kimliği), GH_TOKEN, REPO (sahip/ad)
"""
import json
import os
import re
import subprocess
import sys
import time

import requests

RID = os.environ["RID"].strip()
PRE = re.sub(r"^rapor-", "", RID)[:16]
if not re.fullmatch(r"[0-9a-f]{6,16}", PRE):
    sys.exit("geçersiz kimlik")
API = f"https://api.github.com/repos/{os.environ['REPO']}"
START = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
H = {"Authorization": f"Bearer {os.environ['GH_TOKEN']}", "Accept": "application/vnd.github+json"}


def sh(*a):
    return subprocess.run(a, check=True, capture_output=True, text=True).stdout


def radar_busy() -> bool:
    for st in ("in_progress", "queued"):
        r = requests.get(f"{API}/actions/workflows/radar.yml/runs", headers=H, params={"status": st, "per_page": 5}, timeout=30)
        if r.ok and r.json().get("total_count"):
            return True
    return False


def apply() -> bool:
    sh("git", "fetch", "-q", "origin", "data")
    sh("git", "checkout", "-q", "-B", "data", "origin/data")
    done = json.load(open("private_reports_done.json"))
    kept = [s for s in done if not s.startswith(PRE)]
    res = json.load(open("research.json"))
    if len(kept) == len(done):
        return False                                    # okundu listesinde değil: sırada, radar okuyacak
    if any(r["id"].startswith("rapor-" + PRE) and r.get("ts", "") > START for r in res.get("reports", [])):
        return False                                    # bu iş akışı başladıktan sonra yeniden okunmuş
    json.dump(kept, open("private_reports_done.json", "w"))
    res["reports"] = [r for r in res.get("reports", []) if not r["id"].startswith("rapor-" + PRE)]
    res["notes"] = [n for n in res.get("notes", []) if not str(n.get("id", "")).startswith("rapor-" + PRE)]
    json.dump(res, open("research.json", "w"), ensure_ascii=False, separators=(",", ":"))
    feed = json.load(open("feed.json"))
    feed["items"] = [i for i in feed.get("items", []) if not str(i.get("id", "")).startswith("rapor-" + PRE)]
    json.dump(feed, open("feed.json", "w"), ensure_ascii=False, separators=(",", ":"))
    st = json.load(open("state.json"))
    st["seen"] = [x for x in st.get("seen", []) if not str(x).startswith("rapor-" + PRE)]
    json.dump(st, open("state.json", "w"), ensure_ascii=False, separators=(",", ":"))
    sh("git", "commit", "-qam", f"Rapor yeniden okunacak: {RID}")
    sh("git", "push", "-q", "origin", "data")
    return True


for attempt in range(8):
    for _ in range(60):                                 # radar turu bitene kadar bekle (en fazla ~10 dk)
        if not radar_busy():
            break
        time.sleep(10)
    if not apply():
        print("Tamam: rapor sırada ya da yeniden okundu.")
        sys.exit(0)
    print(f"Deneme {attempt + 1}: okundu listesinden çıkarıldı; radar turu bekleniyor")
    time.sleep(90)                                      # sonraki tur başlasın; bitince kontrol et
sys.exit("Radar turlarıyla çakıştı; daha sonra yeniden çalıştır.")
