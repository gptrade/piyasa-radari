"""Ücretsiz AI seçenekleri: Gemini API model listesi + Gemma denemesi, GitHub Models denemesi."""
import json, os, time, requests
K = os.environ.get("GEMINI_API_KEY", "")
B = "https://generativelanguage.googleapis.com/v1beta"
r = requests.get(f"{B}/models", params={"key": K, "pageSize": 200}, timeout=30)
print("models HTTP", r.status_code)
for m in r.json().get("models", []):
    n = m["name"]
    if any(x in n for x in ("gemma", "flash", "pro")):
        print(" ", n, m.get("inputTokenLimit"), m.get("outputTokenLimit"), ",".join(m.get("supportedGenerationMethods", [])))
SYS = "Sen bir piyasa analistisin. Yanıtı yalnız JSON ver: {\"sentiment\":\"bullish|bearish|neutral\",\"confidence\":0-100,\"headline_tr\":\"...\",\"summary\":\"...\"}"
NEWS = "BAŞLIK: Türk Telekom için hedef fiyat 85 TL'ye yükseltildi\nMETİN: Aracı kurum, güçlü mobil abone büyümesi ve fiber yatırımları nedeniyle Türk Telekom hedef fiyatını 70 TL'den 85 TL'ye çıkardı ve AL tavsiyesini korudu."
names = [m["name"].split("/")[-1] for m in r.json().get("models", []) if "gemma" in m["name"]]
for name in names[:8]:
    t = time.time()
    body = {"contents": [{"role": "user", "parts": [{"text": SYS + "\n\n" + NEWS}]}], "generationConfig": {"maxOutputTokens": 400, "temperature": 0.2}}
    x = requests.post(f"{B}/models/{name}:generateContent", params={"key": K}, json=body, timeout=60)
    txt = ""
    try:
        txt = x.json()["candidates"][0]["content"]["parts"][-1]["text"][:300]
    except Exception:
        txt = x.text[:300]
    print(f"\n== {name} HTTP {x.status_code} {time.time()-t:.1f}s\n{txt}")
    # systemInstruction destekleniyor mu
    body2 = {"systemInstruction": {"parts": [{"text": SYS}]}, **body}
    y = requests.post(f"{B}/models/{name}:generateContent", params={"key": K}, json=body2, timeout=60)
    print("  systemInstruction:", y.status_code, (y.text[:150] if y.status_code != 200 else "ok"))
    time.sleep(3)
for name in ("gemini-3.5-flash-lite", "gemini-3.8-flash"):
    x = requests.post(f"{B}/models/{name}:generateContent", params={"key": K}, json={"contents": [{"parts": [{"text": "merhaba"}]}]}, timeout=60)
    print(f"\n== {name} HTTP {x.status_code} {x.text[:400] if x.status_code != 200 else 'ok'}")
# GitHub Models
G = os.environ.get("GH_MODELS_TOKEN", "")
c = requests.get("https://models.github.ai/catalog/models", headers={"Authorization": f"Bearer {G}"}, timeout=30)
print("\nGitHub catalog HTTP", c.status_code)
try:
    for m in c.json():
        print(" ", m.get("id"), m.get("rate_limit_tier"), m.get("publisher"))
except Exception:
    print(c.text[:300])
for mid in ("openai/gpt-4.1-mini", "openai/gpt-4o-mini"):
    x = requests.post("https://models.github.ai/inference/chat/completions", headers={"Authorization": f"Bearer {G}", "Content-Type": "application/json"},
                      json={"model": mid, "messages": [{"role": "system", "content": SYS}, {"role": "user", "content": NEWS}], "max_tokens": 300}, timeout=60)
    print(f"\n== GH {mid} HTTP {x.status_code}", x.text[:400])
    print("  limits:", {k: v for k, v in x.headers.items() if "ratelimit" in k.lower()})
