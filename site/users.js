/* Lyra Radar — Kullanıcılar (yalnız yöneticiler): radar.lyracube.com'a kimlerin girebileceği.
   Sunucu: functions/api/users.js (Cloudflare Access grubu). Menüdeki bağlantı yalnız yöneticiye görünür;
   GitHub Pages kopyasında sunucu olmadığı için hiç görünmez. Liste bu sayfada saklanmaz, her açılışta Cloudflare'den okunur. */
(() => {
  "use strict";
  const sh = window.shell;
  const { $, esc, fmt } = sh;
  const API = "api/users";
  const S = { d: null, err: "", msg: "", busy: false, q: "" };

  async function call(method = "GET", body) {
    const r = await fetch(API, { method, cache: "no-store", credentials: "same-origin", headers: body ? { "content-type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
    if (!(r.headers.get("content-type") || "").includes("json")) throw new Error("nosrv");
    const j = await r.json();
    if (!r.ok) throw Object.assign(new Error(j.error || `HTTP ${r.status}`), { data: j });
    return j;
  }
  // Menü bağlantısı: yalnız yönetici için göster
  async function probe() {
    try { const j = await call(); if (j.admin) { $("#navUsers").hidden = false; S.d = j; } } catch { /* sunucu yok ya da yönetici değil */ }
  }
  async function load() {
    S.err = "";
    try { S.d = await call(); if (!S.d.admin) S.err = "Bu sayfa yalnız yöneticiler içindir."; }
    catch (e) { S.err = e.message === "nosrv" ? "Kullanıcı yönetimi yalnız radar.lyracube.com adresinde çalışır." : e.message; if (e.data?.admin) S.d = e.data; }
    render();
  }
  async function act(body, okMsg) {
    if (S.busy) return;
    S.busy = true; S.err = ""; S.msg = ""; render();
    try { S.d = await call("POST", body); S.msg = okMsg; }
    catch (e) { S.err = e.message; }
    S.busy = false; render();
  }
  function render() {
    const box = $("#usBody");
    if (!box || sh.route !== "kullanicilar") return;
    const d = S.d, users = d?.users || [];
    const q = S.q.trim().toLowerCase(), shown = q ? users.filter(u => u.email.includes(q)) : users;
    const last = u => u.last ? `<span data-tip="${esc(fmt.dt(u.last))}">${fmt.ago(u.last)}</span>` : `<span class="t3">—</span>`;
    box.innerHTML = `<div class="view" style="gap:var(--s-4)">
      <section class="card us-card" aria-labelledby="usAddT"><div class="card-head"><h2 class="card-title" id="usAddT">Kişi ekle</h2>
        <span class="card-meta">${d?.users ? `${users.length} / ${d.limit} kişi` : ""}</span></div>
        <form class="us-add" id="usForm" autocomplete="off">
          <label class="sr-only" for="usEmail">E-posta</label>
          <input type="email" id="usEmail" class="input" placeholder="ad@ornek.com" required ${S.busy || !d?.users ? "disabled" : ""}>
          <button type="submit" class="btn btn-primary" ${S.busy || !d?.users ? "disabled" : ""}>${S.busy ? "Kaydediliyor…" : "Ekle"}</button>
        </form>
        <p class="t3 us-help">Eklenen kişi radar.lyracube.com'a girerken e-postasına gelen tek kullanımlık kodla giriş yapar; değişiklik birkaç saniyede geçerli olur.
          Çıkarılan kişinin açık oturumu da hemen kapatılır.</p>
        ${S.msg ? `<p class="us-msg up" role="status">${esc(S.msg)}</p>` : ""}${S.err ? `<p class="us-msg down" role="alert">${esc(S.err)}</p>` : ""}
      </section>
      ${d?.users ? `<section class="card card-flush" aria-labelledby="usListT"><div class="card-head"><h2 class="card-title" id="usListT">İzinli kişiler</h2>
          ${users.length > 8 ? `<input type="search" class="input input-sm us-q" id="usQ" placeholder="Ara" value="${esc(S.q)}" aria-label="Kişi ara">` : ""}</div>
        <div class="tbl-scroll"><table class="tbl us-tbl"><thead><tr><th>E-posta</th><th>Son giriş</th><th class="num"></th></tr></thead><tbody>
        ${shown.map(u => `<tr><td class="mono">${esc(u.email)}${u.admin ? ` <span class="tag">yönetici</span>` : ""}${u.email === d.me ? ` <span class="tag na">sen</span>` : ""}</td><td>${last(u)}</td>
          <td class="num">${u.admin ? "" : `<button type="button" class="btn btn-sm us-rm" data-e="${esc(u.email)}" ${S.busy ? "disabled" : ""}>Çıkar</button>`}</td></tr>`).join("")}
        </tbody></table></div>
        <p class="t3 us-help" style="padding:0 var(--s-4) var(--s-3)">Son giriş Cloudflare kayıtlarından; anahtarda okuma yetkisi yoksa boş görünür. Liste Cloudflare Access'te tutulur, bu sitede ya da GitHub'da saklanmaz.</p></section>` : ""}
    </div>`;
    $("#usForm")?.addEventListener("submit", e => { e.preventDefault(); const v = $("#usEmail").value.trim(); if (v) act({ add: v }, `${v} eklendi`); });
    $("#usQ")?.addEventListener("input", e => { S.q = e.target.value; render(); $("#usQ")?.focus(); });
    box.querySelectorAll(".us-rm").forEach(b => b.onclick = () => { if (confirm(`${b.dataset.e} çıkarılsın mı? Açık oturumu da kapatılacak.`)) act({ remove: b.dataset.e }, `${b.dataset.e} çıkarıldı`); });
  }
  sh.register("kullanicilar", {
    onShow() { render(); load(); },
    async refresh() { await load(); },
    exports: () => [],
    exportNote: "Kullanıcı listesi dışa aktarılmaz",
  });
  probe();
})();
