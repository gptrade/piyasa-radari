"""p64b: BoE ve BoJ toplantı takvimi bölümleri."""
import re, requests
UA = {"User-Agent": "Mozilla/5.0 (compatible; PiyasaRadari/1.0; +https://gptrade.github.io/piyasa-radari/)"}
p = requests.get("https://www.bankofengland.co.uk/monetary-policy/upcoming-mpc-dates", headers=UA, timeout=30).text
t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", p, flags=re.S)
i = t.find("MPC dates"); j = t.find("2026", i)
print("=== BoE ham HTML parçası"); print(t[max(0, j - 1500):j + 3500])
q = requests.get("https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm", headers=UA, timeout=30).text
u = re.sub(r"<script.*?</script>|<style.*?</style>", " ", q, flags=re.S)
k = u.find("Schedule")
for m in re.finditer(r"Schedule|Meeting", u):
    pass
k = u.find("Monetary Policy Meetings</h1>") if "Monetary Policy Meetings</h1>" in u else u.find("<main")
print("=== BoJ ana içerik"); print(u[k:k + 6000])
