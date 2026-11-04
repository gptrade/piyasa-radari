"""Pages Functions (JS) testleri: node varsa tests/js/*.mjs çalıştırılır."""
import shutil
import subprocess
from pathlib import Path

import pytest

JS = sorted((Path(__file__).parent / "js").glob("*.test.mjs"))


@pytest.mark.skipif(not shutil.which("node"), reason="node yok")
@pytest.mark.parametrize("path", JS, ids=[p.name for p in JS])
def test_js(path):
    r = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
