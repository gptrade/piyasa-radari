"""p64: BoE ve BoJ toplantı takvimleri: robots.txt ve sayfa biçimi."""
import re, requests
UA = {"User-Agent": "Mozilla/5.0 (compatible; PiyasaRadari/1.0; +https://gptrade.github.io/piyasa-radari/)"}
for base, path in [("https://www.bankofengland.co.uk", "/monetary-policy/upcoming-mpc-dates"),
                   ("https://www.boj.or.jp", "/en/mopo/mpmsche_minu/index.htm")]:
    r = requests.get(base + "/robots.txt", headers=UA, timeout=30)
    print("=====", base, "robots", r.status_code); print(r.text[:1500])
    p = requests.get(base + path, headers=UA, timeout=30)
    print("--- sayfa", p.status_code, len(p.text))
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", p.text, flags=re.S)
    i = max(t.find("2026"), 0)
    print(re.sub(r"\s+", " ", t[i - 3000:i + 6000]))
