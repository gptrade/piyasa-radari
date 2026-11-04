/* Lyra Radar — izleme listesini web'den düzenleme (Cloudflare Pages Function).
   GET  /api/watchlist                → {bist:[...], us:[...], editable}
   POST /api/watchlist {add:{market,symbol,name?,aliases?,tv?}} | {remove:{symbol}}
   Yalnız Cloudflare Access ile giriş yapmış kişiler (JWT doğrulanır). Değişiklik config/watchlist.yml'e GitHub API ile
   kaydedilir; bu commit radar iş akışını tetikler (fiyat/haber/sinyal birkaç dakikada gelir).
   Ortam: GH_TOKEN (gizli; yalnız bu reponun içeriğine yazma), GH_REPO, ACCESS_AUD, ACCESS_TEAM (ör. xxx.cloudflareaccess.com). */

import { parse, removeEntry, addEntry } from "../../lib/watchlist_yaml.js";
import { verifyAccess } from "../../lib/access.js";

const PATH = "config/watchlist.yml";
const MAX = 80;
const json = (obj, status = 200) => new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });

// ───────────── GitHub
const gh = (env, path, init = {}) => fetch(`https://api.github.com/repos/${env.GH_REPO}/${path}`, {
  ...init, headers: { authorization: `Bearer ${env.GH_TOKEN}`, accept: "application/vnd.github+json", "user-agent": "lyra-radar-watchlist", ...(init.headers || {}) } });
const dec = b64 => new TextDecoder().decode(Uint8Array.from(atob(b64.replace(/\n/g, "")), c => c.charCodeAt(0)));
const enc = s => { const b = new TextEncoder().encode(s); let o = ""; for (let i = 0; i < b.length; i += 0x8000) o += String.fromCharCode(...b.subarray(i, i + 0x8000)); return btoa(o); };
async function readFile(env) {
  const r = await gh(env, `contents/${PATH}?ref=main`);
  if (!r.ok) throw new Error(`GitHub okuma ${r.status}`);
  const j = await r.json();
  return { text: dec(j.content), sha: j.sha };
}

const clean = s => String(s || "").replace(/[\u0000-\u001f"\\]/g, "").trim();
const shortName = t => clean(t).replace(/\s+(A\.Ş\.|T\.A\.Ş\.|A\.O\.|T\.A\.O\.|Anonim Şirketi)\.?$/i, "").replace(/\s+/g, " ").slice(0, 80);
const trTitle = t => t.toLocaleLowerCase("tr").replace(/(^|[\s(/-])(\S)/g, (m, a, c) => a + c.toLocaleUpperCase("tr"));
// KAP unvanından haberde geçen kısa ad: ilk kelime (genel kelimeyse ilk iki). Ör. "ASELSAN ELEKTRONİK…" → "Aselsan"
const GENERIC = new Set(["TÜRK", "TÜRKİYE", "GLOBAL", "ANADOLU", "İSTANBUL", "EGE", "DOĞU", "BATI", "YENİ", "BÜYÜK", "ATA", "ULUSAL", "AKDENİZ", "KARADENİZ", "MARMARA", "PETROL", "ENERJİ", "GIDA", "TEKSTİL", "YATIRIM"]);
function kapShort(title) {
  const w = shortName(title).split(" ").filter(Boolean);
  const k = w.length > 1 && (GENERIC.has(w[0].toLocaleUpperCase("tr")) || w[0].length < 4) ? 2 : 1;
  return trTitle(w.slice(0, k).join(" "));
}

export async function onRequest({ request, env }) {
  const who = await verifyAccess(request, env);
  if (request.method === "GET") {
    try { const { text } = await readFile(env); return json({ ...parse(text), editable: !!who }); }
    catch (e) { return json({ error: String(e.message || e) }, 502); }
  }
  if (request.method !== "POST") return json({ error: "yöntem desteklenmiyor" }, 405);
  if (!who) return json({ error: "Giriş doğrulanamadı (Cloudflare Access)" }, 403);
  if (!env.GH_TOKEN || !env.GH_REPO) return json({ error: "Sunucuda GitHub yazma anahtarı tanımlı değil" }, 503);
  let body; try { body = await request.json(); } catch { return json({ error: "geçersiz istek" }, 400); }

  for (let attempt = 0; attempt < 2; attempt++) {
    const { text, sha } = await readFile(env);
    const cur = parse(text), all = [...cur.bist, ...cur.us];
    let next, msg;
    if (body.remove) {
      const sym = clean(body.remove.symbol).toUpperCase();
      next = removeEntry(text, sym);
      if (next == null) return json({ error: `${sym} listede yok` }, 404);
      msg = `İzleme listesi: ${sym} çıkarıldı (web)`;
    } else if (body.add) {
      const a = body.add, market = a.market === "US" ? "us" : "bist", sym = clean(a.symbol).toUpperCase();
      if (all.length >= MAX) return json({ error: `Liste en fazla ${MAX} hisse` }, 400);
      if (all.some(x => x.symbol === sym)) return json({ error: `${sym} zaten listede` }, 409);
      let name = shortName(a.name), tv = null;
      if (market === "bist") {
        if (!/^[A-Z0-9]{3,6}$/.test(sym)) return json({ error: "BIST kodu 3–6 harf/rakam" }, 400);
        const u = await env.ASSETS.fetch(new URL("/data/fin/_universe.json", request.url)).then(r => r.ok ? r.json() : null).catch(() => null);
        const m = u?.members?.find(x => x.code === sym);
        if (u && !m) return json({ error: `${sym} BIST Tüm evreninde bulunamadı` }, 400);
        const kap = m?.title ? kapShort(m.title) : null;
        if (!name || name === shortName(m?.title || "")) name = kap ? trTitle(shortName(m.title)) : sym;
        if (kap) a.aliases = [kap, ...[].concat(a.aliases || [])];
      } else {
        if (!/^[A-Z][A-Z0-9.-]{0,7}$/.test(sym)) return json({ error: "ABD sembolü geçersiz" }, 400);
        tv = clean(a.tv).toUpperCase();
        if (tv && !/^[A-Z]{2,8}:[A-Z0-9.-]{1,8}$/.test(tv)) return json({ error: "TradingView sembolü BORSA:KOD biçiminde olmalı (ör. NASDAQ:AMD)" }, 400);
        name = name || sym;
      }
      const aliases = [...new Set([name, ...[].concat(a.aliases || []).map(clean)].filter(x => x && x.length >= 3))].slice(0, 6).map(x => x.slice(0, 60));
      next = addEntry(text, market, { symbol: sym, name, aliases, tv: tv || null });
      msg = `İzleme listesi: ${sym} eklendi (web)`;
    } else return json({ error: "add ya da remove gerekli" }, 400);

    const r = await gh(env, `contents/${PATH}`, { method: "PUT", body: JSON.stringify({ message: msg, content: enc(next), sha, branch: "main",
      committer: { name: "Lyra Radar web", email: "radar-bot@users.noreply.github.com" } }) });
    if (r.status === 409 && attempt === 0) continue;                 // eşzamanlı değişiklik: yeniden oku, tekrar dene
    if (!r.ok) return json({ error: `GitHub yazma ${r.status}` }, 502);
    return json({ ok: true, ...parse(next), editable: true });
  }
  return json({ error: "Eşzamanlı değişiklik, tekrar dene" }, 409);
}
