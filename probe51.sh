set +e
mkdir -p probe51
{
echo "== .com kayıt (delegasyon)"; dig +norecurse NS lyracube.com @a.gtld-servers.net +short
echo "== GoDaddy NS hâlâ cevap veriyor mu"; dig radar.lyracube.com @ns21.domaincontrol.com +short; dig SOA lyracube.com @ns21.domaincontrol.com +short
for r in 8.8.8.8 1.1.1.1 9.9.9.9 208.67.222.222; do echo "== $r"; dig radar.lyracube.com @$r +short; dig NS lyracube.com @$r +short; done
echo "== Cloudflare NS"; dig radar.lyracube.com @dawn.ns.cloudflare.com +short
echo "== GoDaddy SOA negatif TTL"; dig SOA lyracube.com @ns21.domaincontrol.com
} > probe51/sonuc.txt 2>&1
