// node tests/js/users.test.mjs — /api/users uç noktası: sahte Access JWT + sahte Cloudflare API
import assert from "node:assert/strict";
import { onRequest } from "../../functions/api/users.js";

const { subtle } = globalThis.crypto;
const kp = await subtle.generateKey({ name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" }, true, ["sign", "verify"]);
const jwk = { ...(await subtle.exportKey("jwk", kp.publicKey)), kid: "k1", alg: "RS256" };
const b64u = b => Buffer.from(b).toString("base64").replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
async function jwt(email) {
  const h = b64u(JSON.stringify({ alg: "RS256", kid: "k1" })), p = b64u(JSON.stringify({ email, aud: ["AUD"], iss: "https://t.cloudflareaccess.com", exp: Date.now() / 1000 + 600 }));
  const s = await subtle.sign("RSASSA-PKCS1-v1_5", kp.privateKey, new TextEncoder().encode(`${h}.${p}`));
  return `${h}.${p}.${b64u(new Uint8Array(s))}`;
}
let group = { id: "G", name: "Lyra Radar kullanıcıları", include: [{ email: { email: "admin@x.com" } }, { email: { email: "a@x.com" } }] };
const calls = [];
globalThis.fetch = async (url, init = {}) => {
  url = String(url); calls.push([init.method || "GET", url]);
  if (url.endsWith("/cdn-cgi/access/certs")) return new Response(JSON.stringify({ keys: [jwk] }));
  if (url.includes("/access/groups/G") && (init.method || "GET") === "GET") return new Response(JSON.stringify({ success: true, result: group }));
  if (url.includes("/access/groups/G") && init.method === "PUT") { group = { ...group, ...JSON.parse(init.body) }; return new Response(JSON.stringify({ success: true, result: group })); }
  if (url.includes("/revoke_user")) return new Response(JSON.stringify({ success: true, result: null }));
  if (url.includes("/access/users")) return new Response(JSON.stringify({ success: true, result: [{ email: "a@x.com", last_successful_login: "2026-11-01T10:00:00Z" }] }));
  throw new Error("beklenmeyen " + url);
};
const env = { ACCESS_AUD: "AUD", ACCESS_TEAM: "t.cloudflareaccess.com", CF_ACCOUNT_ID: "acc", ACCESS_GROUP_ID: "G", ADMIN_EMAILS: "Admin@x.com", CF_USERS_TOKEN: "tok" };
const req = async (email, method = "GET", body) => (await onRequest({ request: new Request("https://r/api/users", { method, body: body ? JSON.stringify(body) : undefined,
  headers: email ? { "Cf-Access-Jwt-Assertion": await jwt(email) } : {} }), env })).json().then(j => j);
const st = async (email, method, body) => (await onRequest({ request: new Request("https://r/api/users", { method, body: body ? JSON.stringify(body) : undefined, headers: email ? { "Cf-Access-Jwt-Assertion": await jwt(email) } : {} }), env })).status;

assert.equal(await st(null, "GET"), 403);
assert.deepEqual(await req("a@x.com"), { admin: false, me: "a@x.com" });
assert.equal(await st("a@x.com", "POST", { add: "b@x.com" }), 403);
let r = await req("admin@x.com");
assert.equal(r.admin, true); assert.deepEqual(r.users.map(u => u.email), ["admin@x.com", "a@x.com"]); assert.equal(r.users[1].last, "2026-11-01T10:00:00Z");
r = await req("admin@x.com", "POST", { add: " B@X.com " });
assert.deepEqual(r.users.map(u => u.email), ["admin@x.com", "a@x.com", "b@x.com"]);
assert.equal(await st("admin@x.com", "POST", { add: "b@x.com" }), 409);
assert.equal(await st("admin@x.com", "POST", { add: "kotu" }), 400);
assert.equal(await st("admin@x.com", "POST", { remove: "admin@x.com" }), 400);
r = await req("admin@x.com", "POST", { remove: "a@x.com" });
assert.deepEqual(r.users.map(u => u.email), ["admin@x.com", "b@x.com"]);
assert.ok(calls.some(([m, u]) => m === "POST" && u.includes("revoke_user")));
// sahte imza reddedilir
const bad = (await jwt("admin@x.com")).replace(/\.[^.]+$/, ".AAAA");
assert.equal((await onRequest({ request: new Request("https://r/api/users", { headers: { "Cf-Access-Jwt-Assertion": bad } }), env })).status, 403);
console.log("users.test: tamam");
