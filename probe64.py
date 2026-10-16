"""p64c: sayfaları fixture olarak kaydet + BoE içeriği."""
import re, requests
UA = {"User-Agent": "Mozilla/5.0 (compatible; PiyasaRadari/1.0; +https://gptrade.github.io/piyasa-radari/)"}
p = requests.get("https://www.bankofengland.co.uk/monetary-policy/upcoming-mpc-dates", headers=UA, timeout=30).text
open("probe64/boe.html", "w").write(p)
open("probe64/boj.html", "w").write(requests.get("https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm", headers=UA, timeout=30).text)
t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", p, flags=re.S)
for m in list(re.finditer(r"(Thursday|Wednesday|Tuesday)\s+\d", t))[:3]:
    print("-----"); print(t[max(0, m.start() - 1200):m.start() + 2500])
