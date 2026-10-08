"""`python -m radar.fundamentals [bütçe_sn]` — radar iş akışında ayrı adım olarak çalışır."""
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from .store import run  # noqa: E402

if __name__ == "__main__":
    run(float(sys.argv[1]) if len(sys.argv) > 1 else 180.0)
