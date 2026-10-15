"""p62: gerçek KAP 'Yeni İş İlişkisi' bildirimlerinde tutar çıkarma (onizleme-sozlesme)."""
import json, sys, re, subprocess
from datetime import date, timedelta
sys.path.insert(0, "app")
from radar import deals, http
from radar.documents import kap_body
from radar.sources.kap import LIST_URL, _codes
rows = []
for k in range(0, 60, 7):
    to = date.today() - timedelta(days=k); fr = to - timedelta(days=6)
    r = http.post(LIST_URL, json={"fromDate": fr.isoformat(), "toDate": to.isoformat(), "mkkMemberOidList": [], "subjectList": []},
                  headers={"Referer": "https://www.kap.org.tr/tr/bildirim-sorgu", "Accept": "application/json", "Content-Type": "application/json"})
    if r is not None:
        rows += [x for x in r.json() if deals.SUBJECT.search(x.get("subject") or "")]
    if len(rows) > 40: break
print("bulunan", len(rows))
macro = {"series": [{"code": "TP.DK.USD.A.YTL", "history": [["x", 49.3]]}, {"code": "TP.DK.EUR.A.YTL", "history": [["x", 55.2]]}]}
rates = deals.fx_rates(macro)
seen = 0
for x in rows[:25]:
    codes = _codes(x)
    url = f"https://www.kap.org.tr/tr/Bildirim/{x.get('disclosureIndex')}"
    p = http.get(url, timeout=45, retries=1)
    if p is None: continue
    body = kap_body(p.text, x.get("kapTitle"))
    rev = None
    if codes:
        try:
            doc = json.loads(subprocess.check_output(["git", "-C", "app", "show", f"origin/fin:{codes[0]}.json"], stderr=subprocess.DEVNULL))
            rv = [v for v in doc["series"]["ttm"]["revenue"] if v]; rev = rv[-1] if rv else None
        except Exception: pass
    d = deals.size(body, rates, rev)
    am = deals.amounts(body)
    print(f"\n{codes} {x.get('subject')} | {x.get('summary','')[:80]}\n  bulunan: {am[:6]}\n  seçilen: {d}")
    if d:
        i = body.find(f"{d['cur']}") 
    m = re.search(r"(Sözleşme|İşin|İhale|Sipariş|Toplam)[^\n]{0,30}(Tutar|Bedel)[^\n]{0,160}", body)
    print("  bağlam:", m.group(0)[:200] if m else body[:300].replace("\n", " "))
