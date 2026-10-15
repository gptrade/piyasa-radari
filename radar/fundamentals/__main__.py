"""`python -m radar.fundamentals [bütçe_sn] [tur] [ara_sn]` — temel.yml iş akışı.

KAP rapor indirme sınırı (~5 dakikada 10) nedeniyle tek tur en fazla 9 rapor indirir. Birikmiş kuyruk varken
aynı çalıştırmada birkaç tur atılır; turlar arasında KAP için en az 6 dakika beklenir (store.KAP_SLOT_H).
"""
import logging
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from .store import run  # noqa: E402

if __name__ == "__main__":
    budget = float(sys.argv[1]) if len(sys.argv) > 1 else 180.0
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    gap = float(sys.argv[3]) if len(sys.argv) > 3 else 390.0
    for i in range(rounds):
        t0 = time.monotonic()
        s = run(budget)
        if i == rounds - 1 or s.get("rate_limited") or not (s.get("pending") or s.get("div_pending")):
            break
        time.sleep(max(0.0, gap - (time.monotonic() - t0)))
