/* Lyra Radar — günlük sağlık özeti (yalnız yöneticiler).
   GET /api/health → saglik dalındaki saglik.json (radar/health.py, .github/workflows/saglik.yml üretir).
   Ortam: ACCESS_AUD, ACCESS_TEAM (JWT), ADMIN_EMAILS; isteğe bağlı GH_REPO (varsayılan gptrade/piyasa-radari). */
import { verifyAccess } from "../../lib/access.js";

const json = (obj, status = 200) => new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });
const norm = e => String(e || "").trim().toLowerCase();

export async function onRequest({ request, env }) {
  const me = norm(await verifyAccess(request, env));
  if (!me) return json({ error: "Giriş doğrulanamadı (Cloudflare Access)" }, 403);
  const admins = (env.ADMIN_EMAILS || "").split(/[,;\s]+/).map(norm).filter(Boolean);
  if (!admins.includes(me)) return json({ error: "Yalnız yöneticiler" }, 403);
  const repo = env.GH_REPO || "gptrade/piyasa-radari";
  const r = await fetch(`https://raw.githubusercontent.com/${repo}/saglik/saglik.json?t=${Date.now()}`, { cf: { cacheTtl: 60 } });
  if (!r.ok) return json({ error: `Sağlık özeti henüz yok (HTTP ${r.status})` }, 404);
  return json(await r.json());
}
