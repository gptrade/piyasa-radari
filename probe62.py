"""p62b: tutar bulunamayan sözleşme bildirimlerinin metin biçimi."""
import sys, re
from datetime import date, timedelta
sys.path.insert(0, "app")
from radar import deals, http
from radar.documents import kap_body
from radar.sources.kap import LIST_URL, _codes
rows = []
for k in range(0, 21, 7):
    to = date.today() - timedelta(days=k); fr = to - timedelta(days=6)
    r = http.post(LIST_URL, json={"fromDate": fr.isoformat(), "toDate": to.isoformat(), "mkkMemberOidList": [], "subjectList": []},
                  headers={"Referer": "https://www.kap.org.tr/tr/bildirim-sorgu", "Accept": "application/json", "Content-Type": "application/json"})
    if r is not None:
        rows += [x for x in r.json() if re.search(r"yeni iş ilişkisi|ihale", x.get("subject") or "", re.I)]
for x in rows:
    if not set(_codes(x)) & {"MASFN", "MEDTR", "PCILT", "CLEBI"}: continue
    p = http.get(f"https://www.kap.org.tr/tr/Bildirim/{x.get('disclosureIndex')}", timeout=45, retries=1)
    body = kap_body(p.text, x.get("kapTitle"))
    print("\n=====", _codes(x), x.get("subject"))
    for m in re.finditer(r"oda_[A-Za-z]*(Amount|Value|Price|Cost|Currency|Bedel|Tutar|Sum)[A-Za-z]*\|", body):
        print(re.sub(r"\s*\|\s*", " | ", body[m.start():m.start() + 420]))
    i = body.find("oda_ExplanationSection"); j = body.find("Açıklamalar")
    print("AÇIKLAMA:", re.sub(r"\s+", " ", body[max(i, j):max(i, j) + 900]))
