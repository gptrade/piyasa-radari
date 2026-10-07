import json, sys, logging
sys.path.insert(0, "app")
logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
from pathlib import Path
from radar import private_reports as pr
from radar.analyze import Analyzer
from radar.config import load_settings, load_watchlist
root = Path("_raporlar")
print("repo çekildi:", root.is_dir())
if not root.is_dir(): sys.exit(0)
us = pr.units(root)
print("rapor birimleri:", len(us), [(u["kind"], len(u["files"]), sorted({f.suffix.lower() for f in u["files"]})) for u in us])
for k in pr.KINDS: print("  klasör", k, (root / k).is_dir(), "dosya sayısı", len(list((root / k).rglob("*"))) if (root / k).is_dir() else 0)
other = [p.relative_to(root).parts[0] for p in root.iterdir() if not p.name.startswith(".")]
print("kök içerik:", other)
st = load_watchlist(); S = load_settings(); an = Analyzer(S)
watch = {s.symbol for s in st}
pr.telegram = lambda r, x: False                       # kuru çalıştırma: Telegram yok
res = pr.process(an, watch, {"max_per_run": 3}, root=root, done_path=Path("/tmp/done.json"))
print("durum", res["status"], "AI", an.status()["by_provider"], an.status()["errors"][:2])
for r in res["records"]:
    print("\n== KAYIT (sitede görünecek alanlar)"); print(json.dumps(r, ensure_ascii=False, indent=1)[:2500])
print("\nnot sayısı", len(res["notes"]), [(n["t"], n["rating"], n["tp"], n["src"]) for n in res["notes"]][:12])
print("akış kayıtları", [(i.title, i.tickers, i.analysis["affected_tickers"]) for i in res["items"]])
