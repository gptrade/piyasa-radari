/* Lyra Radar — izleme listesini web'den düzenleme. Sunucu: functions/api/watchlist.js (Cloudflare Pages + Access).
   GitHub Pages kopyasında sunucu yoktur: düğme "yalnız radar.lyracube.com'da" uyarısı verir. Değişiklik config/watchlist.yml'e
   kaydedilir; radar iş akışı birkaç dakikada fiyat, haber ve sinyalleri getirir. */
(() => {
  "use strict";
  const sh = window.shell;
  const { $, esc } = sh;
  const API = "api/watchlist";
  const S = { list: null, editable: false, busy: false, msg: "", err: "", uni: null, market: "BIST" };

  function dialog() {
    let d = $("#wlDlg");
    if (d) return d;
    d = document.createElement("dialog");
    d.className = "cal-dlg wl-dlg"; d.id = "wlDlg"; d.setAttribute("aria-labelledby", "wlDlgT");
    d.innerHTML = `<button type="button" class="btn btn-icon cal-dlg-x" id="wlDlgClose" aria-label="Kapat"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg></button><div id="wlBody"></div>`;
    document.body.append(d);
    $("#wlDlgClose").onclick = () => d.close();
    d.addEventListener("click", e => { if (e.target === d) d.close(); });
    return d;
  }

  async function load() {
    S.err = ""; S.msg = "";
    try {
      const r = await fetch(API, { cache: "no-store", credentials: "same-origin" });
      const ct = r.headers.get("content-type") || "";
      if (!ct.includes("json")) throw new Error("nosrv");
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`);
      S.list = j; S.editable = !!j.editable;
    } catch (e) {
      S.list = null;
      S.err = e.message === "nosrv" ? "Düzenleme yalnız radar.lyracube.com adresinde (giriş yapmış olarak) çalışır." : `Liste alınamadı: ${e.message}`;
    }
    if (!S.uni) fetch("data/fin/_universe.json").then(r => r.ok ? r.json() : null).then(u => { S.uni = u?.members || []; render(); }).catch(() => {});
    render();
  }

  async function send(body) {
    S.busy = true; S.err = ""; S.msg = ""; render();
    try {
      const r = await fetch(API, { method: "POST", credentials: "same-origin", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`);
      S.list = j;
      S.msg = body.add ? `${body.add.symbol} eklendi. Fiyat, haber ve sinyaller birkaç dakika içinde gelir.` : `${body.remove.symbol} çıkarıldı. Panel birkaç dakika içinde güncellenir.`;
    } catch (e) { S.err = e.message; }
    S.busy = false; render();
  }

  function render() {
    const b = $("#wlBody");
    if (!b) return;
    const L = S.list, dis = S.busy || !S.editable ? "disabled" : "";
    const row = (w, m) => `<li><span class="mono"><b>${esc(w.symbol)}</b></span> <span class="t3">${esc(w.name || "")}</span>
      <button type="button" class="link-btn wl-rm" data-sym="${esc(w.symbol)}" ${dis} aria-label="${esc(w.symbol)} çıkar">Çıkar</button></li>`;
    const opts = (S.uni || []).map(m => `<option value="${esc(m.code)}">${esc(m.title)}</option>`).join("");
    b.innerHTML = `<h2 class="cal-dlg-t" id="wlDlgT">İzleme listesini düzenle</h2>
      <p class="cal-dlg-when">Sinyal Takip, fiyat, AI özetleri ve bildirimler bu listeye göre çalışır. Değişiklik ortak listeye kaydedilir (gruptaki herkes görür).</p>
      ${S.err ? `<p class="down" role="alert">${esc(S.err)}</p>` : ""}${S.msg ? `<p class="up" role="status">${esc(S.msg)}</p>` : ""}
      ${L ? `<form id="wlAdd" class="wl-add">
          <div class="seg" role="radiogroup" aria-label="Pazar" id="wlMkt">${["BIST", "US"].map(m => `<button type="button" role="radio" data-v="${m}" aria-checked="${S.market === m}">${m === "US" ? "ABD" : m}</button>`).join("")}</div>
          <input id="wlSym" class="fa-select" placeholder="${S.market === "US" ? "Sembol (ör. AMD)" : "Kod (ör. ASELS)"}" list="${S.market === "BIST" ? "wlUni" : ""}" autocomplete="off" required maxlength="8" ${dis}>
          ${S.market === "US" ? `<input id="wlTv" class="fa-select" placeholder="TradingView (ör. NASDAQ:AMD)" maxlength="20" ${dis}><input id="wlName" class="fa-select" placeholder="Şirket adı" maxlength="80" ${dis}>` : ""}
          <input id="wlAli" class="fa-select" placeholder="Haberde geçen diğer adlar (virgülle, isteğe bağlı)" maxlength="200" ${dis}>
          <button type="submit" class="btn btn-primary" ${dis}>${S.busy ? "Kaydediliyor…" : "Ekle"}</button>
          <datalist id="wlUni">${opts}</datalist></form>
        <div class="res-cols wl-cols"><div><p class="d-sub">BIST (${L.bist.length})</p><ul class="wl-list">${L.bist.map(w => row(w, "BIST")).join("")}</ul></div>
          <div><p class="d-sub">ABD (${L.us.length})</p><ul class="wl-list">${L.us.map(w => row(w, "US")).join("")}</ul></div></div>
        ${S.editable ? "" : `<p class="t3">Giriş doğrulanamadığı için yalnız görüntüleniyor.</p>`}` : (S.err ? "" : `<p class="t3">Yükleniyor…</p>`)}`;
    b.querySelectorAll("#wlMkt button").forEach(x => x.onclick = () => { S.market = x.dataset.v; render(); });
    b.querySelectorAll(".wl-rm").forEach(x => x.onclick = () => { if (confirm(`${x.dataset.sym} izleme listesinden çıkarılsın mı?`)) send({ remove: { symbol: x.dataset.sym } }); });
    const f = $("#wlAdd");
    if (f) f.onsubmit = e => {
      e.preventDefault();
      const sym = $("#wlSym").value.trim().toUpperCase().split(/\s/)[0];
      if (!sym) return;
      const aliases = ($("#wlAli").value || "").split(",").map(s => s.trim()).filter(Boolean);
      send({ add: { market: S.market, symbol: sym, tv: $("#wlTv")?.value.trim() || undefined, name: $("#wlName")?.value.trim() || (S.uni || []).find(m => m.code === sym)?.title, aliases } });
    };
  }

  function open() { dialog().showModal(); render(); load(); }

  // İzleme listesi kartına "Düzenle" düğmesi
  const head = document.querySelector("#heatCard .strip-head");
  if (head && !$("#wlEdit")) {
    const btn = document.createElement("button");
    btn.type = "button"; btn.className = "btn wl-edit"; btn.id = "wlEdit"; btn.textContent = "Düzenle";
    btn.setAttribute("data-tip", "Hisse ekle / çıkar");
    btn.onclick = open;
    head.append(btn);
  }
  window.radarWatchEdit = { open };
})();
