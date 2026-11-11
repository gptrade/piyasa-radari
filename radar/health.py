"""Günlük sağlık denetimi (yalnız yönetici): veri tazeliği, içerik makullüğü, iş akışı hataları, kaynak durumu.

Çalışma: .github/workflows/saglik.yml her sabah (İstanbul ~08:20) — veri dallarını (data, fin, fin_us, guc, olay,
yontem, enerji, regulasyon) okur, GitHub Actions'ın son 24 saatlik çalıştırmalarını sorgular ve
  * yöneticiye Telegram özeti gönderir (TELEGRAM_ADMIN_CHAT_ID; yoksa TELEGRAM_CHAT_ID),
  * saglik dalına saglik.json yazar (sitede yalnız yöneticinin gördüğü Kullanıcılar sayfasında, /api/health üzerinden).
Kural: her denetim ok / warn / fail döner; genel durum en kötüsüdür. Eşikler veri üreticisinin takvimine göre seçildi
(hafta sonu ve tatilde piyasa verisi beklenmez: iş günü saatleriyle değil, takvim saatiyle ama cömert eşikle).
`python -m radar.health` (ortam: GITHUB_TOKEN, GITHUB_REPOSITORY; isteğe bağlı TELEGRAM_*).
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime, timedelta, timezone

from . import http
from .models import parse_iso

log = logging.getLogger("radar.health")

# (dal, dosya, zaman alanı, uyarı saati, hata saati, etiket, makullük denetimi)
FILES = [
    ("data", "feed.json", "generated", 2, 6, "Sinyal akışı (15 dk)", lambda d: (len(d.get("items") or []) >= 200, f"{len(d.get('items') or [])} kayıt")),
    ("data", "piyasa.json", "generated", 2, 8, "Piyasa şeridi", None),
    ("data", "macro.json", "updated", 6, 30, "Makro / TCMB", None),
    ("data", "calendar.json", "generated", 6, 30, "Takvim", None),
    ("data", "research.json", "generated", 6, 30, "Araştırma", None),
    ("data", "us_map.json", "generated", 30, 80, "ABD ısı haritası", lambda d: (len(d.get("stocks") or []) >= 450, f"{len(d.get('stocks') or [])} hisse")),
    ("fin", "_screen.json", "updated", 8, 50, "BIST temel analiz", lambda d: (len(d.get("rows") or []) >= 500, f"{len(d.get('rows') or [])} şirket")),
    ("fin_us", "_screen.json", "updated", 30, 80, "ABD temel analiz", lambda d: (len(d.get("rows") or []) >= 450, f"{len(d.get('rows') or [])} şirket")),
    ("guc", "guc.json", "generated", 30, 80, "Piyasa Gücü", lambda d: ((d.get("korku") or {}).get("value") is not None,
                                                                      f"korku {(d.get('korku') or {}).get('value')} · {len((d.get('korku') or {}).get('components') or [])} bileşen")),
    ("guc", "kredili.json", "updated", 24 * 5, 24 * 10, "TSPB kredili işlem", None),
    ("olay", "summary.json", "generated", 30, 80, "Olay Karnesi", None),
    ("yontem", "yontem.json", "generated", 24 * 8, 24 * 15, "Yöntem Karnesi", None),
    ("enerji", "kurulu_guc.json", "generated", 24 * 4, 24 * 8, "Enerji", None),
    ("regulasyon", "regwatch.json", "generated", 30, 80, "Regülasyon", None),
]
SCHEDULED = {"radar", "temel", "temel-abd", "guc", "olay", "yontem", "enerji", "regulasyon"}   # 24 saatte en az bir kez beklenir
RANK = {"ok": 0, "warn": 1, "fail": 2}
ICON = {"ok": "✅", "warn": "⚠️", "fail": "❌"}


def _git_json(branch: str, path: str):
    try:
        out = subprocess.check_output(["git", "show", f"origin/{branch}:{path}"], stderr=subprocess.DEVNULL)
        return json.loads(out)
    except (subprocess.CalledProcessError, ValueError, OSError):
        return None


def check_files(now: datetime, reader=_git_json) -> list[dict]:
    out = []
    for branch, path, key, warn_h, fail_h, label, sane in FILES:
        d = reader(branch, path)
        row = {"group": "veri", "label": label, "where": f"{branch}/{path}"}
        if not isinstance(d, dict):
            out.append({**row, "status": "fail", "detail": "dosya okunamadı"})
            continue
        try:
            age = (now - parse_iso(str(d.get(key)))).total_seconds() / 3600
        except (TypeError, ValueError):
            out.append({**row, "status": "fail", "detail": f"zaman alanı yok ({key})"})
            continue
        st = "ok" if age <= warn_h else "warn" if age <= fail_h else "fail"
        detail = f"{_age(age)} önce"
        if sane:
            try:
                good, note = sane(d)
            except Exception:  # noqa: BLE001
                good, note = False, "içerik denetimi hata verdi"
            detail += f" · {note}"
            if not good:
                st = max(st, "warn", key=RANK.get)
        out.append({**row, "status": st, "detail": detail, "age_h": round(age, 1)})
    return out


def check_sources(feed: dict | None) -> list[dict]:
    """Sinyal akışındaki kaynakların son durumu (sitedeki "N/M kaynak aktif" göstergesinin aynısı)."""
    srcs = [s for s in (feed or {}).get("sources") or [] if s.get("name") != "Telegram"]
    bad = [s["name"] for s in srcs if not s.get("ok")]
    tg = next((s for s in (feed or {}).get("sources") or [] if s.get("name") == "Telegram"), None)
    out = [{"group": "kaynak", "label": "Haber / duyuru kaynakları",
            "status": "ok" if not bad else "warn" if len(bad) <= 2 else "fail",
            "detail": f"{len(srcs) - len(bad)}/{len(srcs)} aktif" + (f" · sorunlu: {', '.join(bad[:5])}" if bad else "")}]
    if tg:
        out.append({"group": "kaynak", "label": "Telegram bildirimi", "status": "ok" if tg.get("ok") else "fail",
                    "detail": "çalışıyor" if tg.get("ok") else (tg.get("error") or "hata")[:120]})
    return out


def check_runs(now: datetime, repo: str | None, token: str | None) -> list[dict]:
    """Son 24 saatte iş akışı çalıştırmaları: başarısızlar ve hiç çalışmayan zamanlanmış akışlar."""
    if not repo or not token:
        return [{"group": "iş akışı", "label": "GitHub Actions", "status": "warn", "detail": "GITHUB_TOKEN yok, denetlenmedi"}]
    since = (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    runs, page = [], 1
    while page <= 5:
        r = http.get(f"https://api.github.com/repos/{repo}/actions/runs?created=%3E{since}&per_page=100&page={page}",
                     headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}, timeout=30)
        if r is None or r.status_code != 200:
            return [{"group": "iş akışı", "label": "GitHub Actions", "status": "warn", "detail": "API yanıt vermedi"}]
        xs = r.json().get("workflow_runs") or []
        runs += xs
        if len(xs) < 100:
            break
        page += 1
    by: dict[str, list] = {}
    for x in runs:
        if x.get("head_branch") not in ("main", None) and x.get("event") != "schedule":
            continue                                   # önizleme dallarındaki elle denemeler sayılmaz
        name = (x.get("path") or "").rsplit("/", 1)[-1].removesuffix(".yml") or x.get("name")
        by.setdefault(name, []).append(x)
    out = []
    for name in sorted(set(by) | SCHEDULED):
        xs = by.get(name, [])
        done = [x for x in xs if x.get("status") == "completed"]
        fails = [x for x in done if x.get("conclusion") in ("failure", "timed_out", "startup_failure")]
        last = max(done, key=lambda x: x.get("created_at") or "", default=None)
        if not xs and name in SCHEDULED:
            st, detail = "warn", "24 saatte hiç çalışmadı"
        elif not done:
            st, detail = "ok", f"{len(xs)} çalışma sürüyor"
        else:
            last_bad = last.get("conclusion") in ("failure", "timed_out", "startup_failure")
            st = "fail" if last_bad else "warn" if fails else "ok"
            detail = f"{len(done)} çalışma, {len(fails)} hata" + (" · son çalışma başarısız" if last_bad else "")
        row = {"group": "iş akışı", "label": name, "status": st, "detail": detail}
        if fails:
            row["url"] = max(fails, key=lambda x: x.get("created_at") or "").get("html_url")
        out.append(row)
    return out


def _age(h: float) -> str:
    return f"{h * 60:.0f} dk" if h < 1 else f"{h:.0f} sa" if h < 48 else f"{h / 24:.0f} gün"


def run(now: datetime | None = None, reader=_git_json) -> dict:
    now = now or datetime.now(timezone.utc)
    checks = check_files(now, reader) + check_sources(reader("data", "feed.json")) + \
        check_runs(now, os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN"))
    overall = max((c["status"] for c in checks), key=RANK.get, default="ok")
    return {"generated": now.isoformat(timespec="seconds"), "overall": overall,
            "counts": {k: sum(c["status"] == k for c in checks) for k in RANK}, "checks": checks}


def message(doc: dict, site: str | None = None) -> str:
    c = doc["counts"]
    head = f"{ICON[doc['overall']]} <b>Lyra Radar günlük sağlık</b> · {c['ok']} tamam, {c['warn']} uyarı, {c['fail']} hata"
    lines = [head]
    issues = [x for x in doc["checks"] if x["status"] != "ok"]
    if not issues:
        lines.append("Tüm veri akışları güncel, iş akışlarında hata yok.")
    for x in sorted(issues, key=lambda x: -RANK[x["status"]]):
        lines.append(f"{ICON[x['status']]} {_esc(x['label'])}: {_esc(x['detail'])}")
    if site:
        lines.append(f'<a href="{site.rstrip("/")}/#kullanicilar">Ayrıntı</a>')
    return "\n".join(lines)


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send(doc: dict) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_ADMIN_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        log.warning("Telegram ayarı yok; sağlık özeti gönderilmedi")
        return False
    r = http.post(f"https://api.telegram.org/bot{token}/sendMessage",
                  json={"chat_id": chat, "text": message(doc, os.environ.get("SITE_URL")), "parse_mode": "HTML",
                        "disable_web_page_preview": True}, timeout=30)
    return r is not None and r.status_code == 200


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    d = run()
    os.makedirs("out", exist_ok=True)
    with open("out/saglik.json", "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    print(message(d))
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        log.info("Telegram: %s", "gönderildi" if send(d) else "gönderilemedi")
