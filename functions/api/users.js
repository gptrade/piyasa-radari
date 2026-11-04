/* Lyra Radar — site kullanıcılarını web'den yönetme (Cloudflare Pages Function).
   GET  /api/users                      → {admin, me, users:[{email, last}], limit}   (admin değilse yalnız {admin:false, me})
   POST /api/users {add:"e@posta"} | {remove:"e@posta"}   (yalnız yöneticiler)
   İzinli kişiler Cloudflare Access grubunda tutulur (Access uygulamasının politikası bu gruba izin verir); ekleme/çıkarma
   grubu Cloudflare API ile günceller. Çıkarılan kişinin açık oturumu da hemen kapatılır (revoke_user).
   Ortam: ACCESS_AUD, ACCESS_TEAM (JWT), CF_ACCOUNT_ID, ACCESS_GROUP_ID, ADMIN_EMAILS (virgülle),
          CF_USERS_TOKEN (gizli; yalnız "Access: Organizations, Identity Providers, and Groups — Edit" yetkili anahtar). */
import { verifyAccess } from "../../lib/access.js";

const LIMIT = 50;                     // Cloudflare Zero Trust ücretsiz planı: 50 kullanıcı
const EMAIL = /^[^@\s<>"',;]+@[^@\s<>"',;]+\.[^@\s<>"',;]{2,}$/;
const json = (obj, status = 200) => new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });
const norm = e => String(e || "").trim().toLowerCase();
const admins = env => (env.ADMIN_EMAILS || "").split(/[,;\s]+/).map(norm).filter(Boolean);

async function cf(env, method, path, body) {
  const r = await fetch(`https://api.cloudflare.com/client/v4/accounts/${env.CF_ACCOUNT_ID}${path}`, {
    method, headers: { authorization: `Bearer ${env.CF_USERS_TOKEN}`, "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  let j; try { j = await r.json(); } catch { j = { success: false, errors: [{ message: `HTTP ${r.status}` }] }; }
  if (!j.success) throw new Error((j.errors || []).map(e => `${e.code || ""} ${e.message || ""}`).join("; ").slice(0, 200) || `HTTP ${r.status}`);
  return j.result;
}
const groupEmails = g => (g.include || []).map(x => norm(x.email?.email)).filter(Boolean);

async function lastLogins(env) {           // isteğe bağlı: anahtarda "Access: Users Read" yoksa boş döner
  try {
    const xs = await cf(env, "GET", "/access/users?per_page=200");
    return Object.fromEntries((xs || []).map(u => [norm(u.email), u.last_successful_login || null]));
  } catch { return {}; }
}

export async function onRequest({ request, env }) {
  const me = norm(await verifyAccess(request, env));
  if (!me) return json({ error: "Giriş doğrulanamadı (Cloudflare Access)" }, 403);
  const isAdmin = admins(env).includes(me);
  if (!isAdmin) return request.method === "GET" ? json({ admin: false, me }) : json({ error: "Yalnız yöneticiler" }, 403);
  if (!env.CF_USERS_TOKEN || !env.ACCESS_GROUP_ID || !env.CF_ACCOUNT_ID) return json({ admin: true, me, error: "Sunucuda kullanıcı yönetimi anahtarı tanımlı değil (CF_USERS_TOKEN)" }, 503);

  let g;
  try { g = await cf(env, "GET", `/access/groups/${env.ACCESS_GROUP_ID}`); }
  catch (e) { return json({ admin: true, me, error: `Cloudflare okuma: ${e.message}` }, 502); }
  let list = groupEmails(g);

  if (request.method === "POST") {
    let body; try { body = await request.json(); } catch { return json({ error: "geçersiz istek" }, 400); }
    const add = norm(body.add), rem = norm(body.remove);
    if (add) {
      if (!EMAIL.test(add)) return json({ error: "Geçersiz e-posta" }, 400);
      if (list.includes(add)) return json({ error: "Bu kişi zaten listede" }, 409);
      if (list.length >= LIMIT) return json({ error: `En fazla ${LIMIT} kişi (Cloudflare ücretsiz plan)` }, 400);
      list = [...list, add];
    } else if (rem) {
      if (!list.includes(rem)) return json({ error: "Bu kişi listede yok" }, 404);
      if (admins(env).includes(rem)) return json({ error: "Yönetici buradan çıkarılamaz" }, 400);
      list = list.filter(e => e !== rem);
    } else return json({ error: "add ya da remove gerekli" }, 400);
    try {
      g = await cf(env, "PUT", `/access/groups/${env.ACCESS_GROUP_ID}`, { name: g.name, include: list.map(email => ({ email: { email } })), exclude: g.exclude || [], require: g.require || [] });
      list = groupEmails(g);
      if (rem) await cf(env, "POST", "/access/organizations/revoke_user", { email: rem }).catch(() => null);   // açık oturumu kapat
    } catch (e) { return json({ error: `Cloudflare yazma: ${e.message}` }, 502); }
  }
  const last = await lastLogins(env);
  return json({ admin: true, me, limit: LIMIT, users: list.map(email => ({ email, last: last[email] || null, admin: admins(env).includes(email) })) });
}
