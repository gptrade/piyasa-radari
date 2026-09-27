"""Komut satırı: `python -m radar` (normal çalışma) veya `python -m radar demo` (örnek veri)."""
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "demo":
        from .demo import write_demo
        write_demo()
    else:
        from .pipeline import run
        run()


if __name__ == "__main__":
    main()
