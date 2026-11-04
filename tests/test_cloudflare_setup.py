import importlib


def _mod(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "x" * 40)
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a" * 32)
    src = open("tools/cloudflare_setup.py", encoding="utf-8").read().split("\nstep(\"anahtar\", token)")[0]
    ns = {}
    exec(compile(src, "cfs", "exec"), ns)
    return ns


def test_token_extracted_from_curl_snippet(monkeypatch):
    m = _mod(monkeypatch)
    tok = "cfut_" + "AbC123_-" * 5
    snippet = f'curl "https://api.cloudflare.com/client/v4/user/tokens/verify" \\\n-H "Authorization: Bearer {tok}"'
    assert m["clean_token"](snippet) == tok
    assert m["clean_token"](f"  {tok}\n") == tok
    assert m["clean_token"]("bu bir anahtar değil") == ""


def test_redact_hides_token(monkeypatch):
    m = _mod(monkeypatch)
    tok = "cfut_" + "Zz9" * 12
    out = m["redact"](f"Invalid header value: 'Bearer {tok}' and {tok}")
    assert tok not in out and "cfut_" not in out
