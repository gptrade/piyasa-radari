/* Cloudflare Access JWT doğrulama (Pages Functions ortak): imza (RS256, ekibin açık anahtarları), aud, iss ve süre.
   Ortam: ACCESS_AUD, ACCESS_TEAM (ör. xxx.cloudflareaccess.com). Dönüş: giriş yapan e-posta ya da null. */
let CERTS = null, CERTS_AT = 0;
const b64u = s => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4)), c => c.charCodeAt(0));
export async function verifyAccess(request, env) {
  const tok = request.headers.get("Cf-Access-Jwt-Assertion") || (request.headers.get("Cookie") || "").match(/CF_Authorization=([^;]+)/)?.[1];
  if (!tok || !env.ACCESS_AUD || !env.ACCESS_TEAM) return null;
  const [h, p, sig] = tok.split(".");
  if (!sig) return null;
  let header, payload;
  try { header = JSON.parse(new TextDecoder().decode(b64u(h))); payload = JSON.parse(new TextDecoder().decode(b64u(p))); } catch { return null; }
  if (!CERTS || Date.now() - CERTS_AT > 3600e3) {
    const r = await fetch(`https://${env.ACCESS_TEAM}/cdn-cgi/access/certs`);
    CERTS = (await r.json()).keys; CERTS_AT = Date.now();
  }
  const jwk = CERTS.find(k => k.kid === header.kid);
  if (!jwk) return null;
  const key = await crypto.subtle.importKey("jwk", jwk, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
  const ok = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, b64u(sig), new TextEncoder().encode(`${h}.${p}`));
  const aud = [].concat(payload.aud || []);
  if (!ok || !aud.includes(env.ACCESS_AUD) || payload.exp * 1000 < Date.now() || payload.iss !== `https://${env.ACCESS_TEAM}`) return null;
  return payload.email || "kullanıcı";
}
