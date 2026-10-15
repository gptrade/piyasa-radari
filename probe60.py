"""p60b: Gemma 4 JSON çıktısı (düşünme kapalı/açık), hız; GitHub Models ayrıntı."""
import json, os, time, requests
K = os.environ.get("GEMINI_API_KEY", "")
B = "https://generativelanguage.googleapis.com/v1beta"
SYS = ("Sen bir piyasa analistisin. Yanıtı yalnız JSON ver, başka metin yazma: "
       "{\"sentiment\":\"bullish|bearish|neutral\",\"confidence\":0-100,\"headline_tr\":\"...\",\"summary\":\"...\"}")
NEWS = "BAŞLIK: Türk Telekom için hedef fiyat 85 TL'ye yükseltildi\nMETİN: Aracı kurum, güçlü mobil abone büyümesi ve fiber yatırımları nedeniyle Türk Telekom hedef fiyatını 70 TL'den 85 TL'ye çıkardı ve AL tavsiyesini korudu."
variants = {
    "json_mime": {"responseMimeType": "application/json"},
    "think_min": {"responseMimeType": "application/json", "thinkingConfig": {"thinkingLevel": "minimal"}},
    "think_0": {"thinkingConfig": {"thinkingBudget": 0}},
}
for name in ("gemma-4-26b-a4b-it", "gemma-4-31b-it"):
    for vn, gc in variants.items():
        t = time.time()
        body = {"systemInstruction": {"parts": [{"text": SYS}]}, "contents": [{"role": "user", "parts": [{"text": NEWS}]}],
                "generationConfig": {"maxOutputTokens": 3000, "temperature": 0.2, **gc}}
        x = requests.post(f"{B}/models/{name}:generateContent", params={"key": K}, json=body, timeout=120)
        try:
            j = x.json(); parts = j["candidates"][0]["content"]["parts"]
            out = " | ".join(f"[{'thought' if p.get('thought') else 'text'}] {p.get('text','')[:250]}" for p in parts)
            out += f"\n   usage={j.get('usageMetadata')}"
        except Exception:
            out = x.text[:300]
        print(f"\n== {name} {vn} HTTP {x.status_code} {time.time()-t:.1f}s\n{out}")
        time.sleep(4)
G = os.environ.get("GH_MODELS_TOKEN", "")
H = {"Authorization": f"Bearer {G}", "Content-Type": "application/json", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
c = requests.get("https://models.github.ai/catalog/models", headers=H, timeout=30)
print("\nGitHub catalog HTTP", c.status_code, c.headers.get("content-type"), len(c.text))
try:
    for m in c.json()[:80]:
        print(" ", m.get("id"), m.get("rate_limit_tier"))
except Exception as e:
    print(repr(c.text[:300]))
for mid in ("openai/gpt-4.1-mini", "openai/gpt-4.1", "deepseek/deepseek-v3-0324"):
    x = requests.post("https://models.github.ai/inference/chat/completions", headers=H,
                      json={"model": mid, "messages": [{"role": "system", "content": SYS}, {"role": "user", "content": NEWS}], "max_tokens": 300}, timeout=60)
    print(f"\n== GH {mid} HTTP {x.status_code}", x.headers.get("content-type"), repr(x.text[:500]))
    print("  hdr:", {k: v for k, v in x.headers.items() if any(s in k.lower() for s in ("ratelimit", "limit", "remaining"))})
