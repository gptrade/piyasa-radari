/* Piyasa Radarı — Araştırma sekmesi.
   Veri: data/research.json (pipeline: radar/research.py)
   - synthesis: günlük AI sentezi (aracı kurum notları + kurum görünümleri + makro gelişmeler)
   - outlooks: J.P. Morgan Guide to the Markets, BlackRock haftalık yorum özetleri
   - notes: aracı kurum notları (kamuya duyurulan başlıklardan: kurum, hisse, tavsiye, hedef fiyat)
   - consensus: izleme listesi için kurum başına son not üzerinden medyan hedef ve tavsiye dağılımı */
(() => {
  "use strict";
  const sh = window.shell;
  const { $, $$, esc, fmt, store } = sh;
  const S = { data: null, loaded: false, error: null, scope: store.get("radar.resScope", "watch"), q: "", limit: 30 };
  const RAT = { AL: "up", SAT: "down", TUT: "flat" };
  const ACT = { up: "▲ yükseltti", down: "▼ düşürdü", init: "kapsama başladı", keep: "korudu", set: "belirledi", add: "model portföye ekledi", remove: "model portföyden çıkardı" };
  const STANCE = { olumlu: "up", olumsuz: "down", "nötr": "flat", "karışık": "" };

  async function load() {
    try {
      const r = await fetch(`data/research.json?t=${Date.now()}`);
      if (!r.ok) throw new Error(`data/research.json okunamadı (HTTP ${r.status})`);
      S.data = await r.json(); S.error = null;
    } catch (e) { S.error = e; }
    S.loaded = true;
    if (S.data) sh.setUpdated("arastirma", S.data.generated, { label: "Araştırma güncellendi", staleMin: 120 });
    if (sh.route === "arastirma") render();
  }
  const watch = () => { const wl = window.radar?.state?.feed?.watchlist; return new Set(wl ? wl.map(w => w.symbol) : Object.keys(S.data?.consensus || {})); };
  const inMarket = n => sh.market === "ALL" || n.m === sh.market;
  const CUR = { USD: " $", TRY: " ₺", EUR: " €" };
  const price = t => window.radarResearch?.prices?.[t]?.last;

  function synthesisCard(s) {
    if (!s) return `<section class="card"><h2 class="card-title">Sentez</h2><p class="tp-empty">Henüz sentez yok. Yeterli not ve görünüm biriktiğinde günde bir üretilir.</p></section>`;
    const list = (title, xs) => xs?.length ? `<p class="d-sub">${title}</p><ul class="res-list">${xs.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
    return `<section class="card res-syn" aria-labelledby="resSynT">
      <div class="card-head"><h2 class="card-title" id="resSynT">Sentez · son 7 gün</h2>
        <span class="card-meta">${fmt.ago(s.generated, true)} · ${s.inputs ? `${s.inputs.notes} kurum notu, ${s.inputs.outlooks} görünüm, ${s.inputs.macro} makro gelişme` : ""}</span></div>
      <p class="res-head">${esc(s.headline)}</p>
      <p class="d-sum">${esc(s.summary)}</p>
      <div class="res-cols">
        <div>${list("Kurumların hemfikir olduğu", s.consensus)}</div>
        <div>${list("Ayrıştıkları", s.divergences)}</div>
      </div>
      ${s.watchlist?.length ? `<p class="d-sub">İzleme listesi için</p><table class="tx res-wl"><tbody>${s.watchlist.map(w => `
        <tr><td><button type="button" class="tk-link" data-sym="${esc(w.ticker)}">${esc(w.ticker)}</button></td>
        <td><span class="${STANCE[w.stance] ?? ""}">${esc(w.stance)}</span></td><td>${esc(w.why)}</td></tr>`).join("")}</tbody></table>` : ""}
      <div class="res-cols">
        <div>${list("Riskler", s.risks)}</div>
        <div>${list("İzlenecekler", s.watch_next)}</div>
      </div>
      <p class="card-foot">AI sentezi; kurumların görüşlerini özetler, yatırım tavsiyesi değildir. Dayandığı notlar ve görünümler aşağıda.</p>
    </section>`;
  }

  function outlookCard(os) {
    return `<section class="card" aria-labelledby="resOutT">
      <div class="card-head"><h2 class="card-title" id="resOutT">Kurum görünümleri</h2><span class="card-meta">J.P. Morgan Guide to the Markets (çeyreklik) · BlackRock haftalık yorum</span></div>
      ${os?.length ? os.slice(0, 4).map(o => `<article class="res-out">
        <p class="res-out-h"><b>${esc(o.house)}</b> · ${esc(o.title)} <span class="t3">· ${fmt.date(o.ts)}</span>
          ${o.url ? `<a href="${esc(o.url)}" target="_blank" rel="noopener">Belge ↗</a>` : ""}</p>
        ${o.summary ? `<p class="d-sum">${esc(o.summary)}</p>` : ""}
        ${o.key_points?.length ? `<ul class="res-list">${o.key_points.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
        ${o.risks?.length ? `<p class="doc-risks"><b>Riskler:</b> ${o.risks.map(esc).join(" · ")}</p>` : ""}
      </article>`).join("") : `<p class="tp-empty">Henüz görünüm özeti yok; yeni sayı yayımlandığında eklenir.</p>`}
    </section>`;
  }

  function consensusCard(c) {
    const rows = Object.entries(c || {}).filter(([t]) => sh.market === "ALL" || (window.radarResearch?.prices?.[t]?.market || "BIST") === sh.market);
    if (!rows.length) return "";
    return `<section class="card" aria-labelledby="resConT">
      <div class="card-head"><h2 class="card-title" id="resConT">İzleme listesi · kurum konsensüsü</h2><span class="card-meta">her kurumun son notu · 120 gün</span></div>
      <table class="tx"><thead><tr><th>Hisse</th><th class="num">Kurum</th><th>Dağılım</th><th class="num">Medyan hedef</th><th class="num">Potansiyel</th></tr></thead><tbody>${rows.map(([t, x]) => {
        const p = price(t), up = x.median_tp && p ? (x.median_tp / p - 1) * 100 : null;
        return `<tr><td><button type="button" class="tk-link" data-sym="${esc(t)}">${esc(t)}</button></td><td class="num">${fmt.int(x.n)}</td>
          <td><span class="up">${x.dist.AL} AL</span> · ${x.dist.TUT} TUT · <span class="down">${x.dist.SAT} SAT</span></td>
          <td class="num">${x.median_tp ? fmt.num(x.median_tp, 2) : "—"}</td><td class="num">${up == null ? "—" : `<span class="${up > 0 ? "up" : "down"}">${fmt.pct(up)}</span>`}</td></tr>`;
      }).join("")}</tbody></table>
    </section>`;
  }

  function notesCard(notes) {
    const w = watch();
    let xs = (notes || []).filter(inMarket);
    if (S.scope === "watch") xs = xs.filter(n => w.has(n.t));
    if (S.q) { const q = S.q.toLocaleLowerCase("tr"); xs = xs.filter(n => `${n.t || ""} ${n.name || ""} ${n.broker} ${n.title}`.toLocaleLowerCase("tr").includes(q)); }
    const shown = xs.slice(0, S.limit);
    return `<section class="card card-flush" aria-labelledby="resNotT">
      <div class="card-head"><h2 class="card-title" id="resNotT">Aracı kurum notları</h2>
        <span class="card-meta">${fmt.int(xs.length)} not · kamuya duyurulan başlıklardan (AA, Bloomberg HT, Foreks, Yahoo…) çıkarılır, raporların kendisi okunmaz</span></div>
      ${shown.length ? `<div class="res-tw"><table class="tx res-notes"><thead><tr><th>Tarih</th><th>Hisse</th><th>Kurum</th><th>Tavsiye</th><th>Değişim</th><th class="num">Hedef</th><th class="num">Önceki</th><th>Kaynak</th></tr></thead><tbody>${shown.map(n => `
        <tr><td>${fmt.date(n.ts)}</td><td>${n.t && w.has(n.t) ? `<button type="button" class="tk-link" data-sym="${esc(n.t)}">${esc(n.t)}</button>` : esc(n.t || n.name || "—")}</td>
        <td>${esc(n.broker)}</td><td><span class="${RAT[n.rating] || ""}">${esc(n.rating || "—")}</span></td><td>${esc(ACT[n.action] || "")}</td>
        <td class="num">${n.tp ? fmt.num(n.tp, 2) + (CUR[n.cur] || "") : "—"}</td><td class="num">${n.prev ? fmt.num(n.prev, 2) : ""}</td>
        <td>${n.url ? `<a href="${esc(n.url)}" target="_blank" rel="noopener" data-tip="${esc(n.title)}">${esc(n.src)} ↗</a>` : esc(n.src)}</td></tr>`).join("")}</tbody></table></div>
        ${xs.length > shown.length ? `<p class="res-more"><button type="button" class="link-btn" id="resMore">${Math.min(30, xs.length - shown.length)} not daha göster</button></p>` : ""}`
        : `<p class="tp-empty res-pad">Bu filtrede not yok.</p>`}
    </section>`;
  }

  function render() {
    const box = $("#resBody");
    if (!box) return;
    if (!S.loaded) { box.innerHTML = sh.stateHTML ? sh.stateHTML({ kind: "loading", title: "Yükleniyor…" }) : "<p>Yükleniyor…</p>"; return; }
    if (S.error || !S.data) { box.innerHTML = `<section class="card"><p class="tp-empty">Araştırma verisi henüz yok. İlk tarama turundan sonra oluşur.</p></section>`; return; }
    const d = S.data;
    box.innerHTML = `<div class="res-grid"><div class="res-main">${synthesisCard(d.synthesis)}${notesCard(d.notes)}</div>
      <div class="res-side">${consensusCard(d.consensus)}${outlookCard(d.outlooks)}</div></div>`;
    $$(".tk-link", box).forEach(b => b.onclick = () => { location.hash = "#sinyal"; setTimeout(() => window.radar?.openTicker(b.dataset.sym, b), 80); });
    const more = $("#resMore"); if (more) more.onclick = () => { S.limit += 30; render(); };
  }

  function bindTools() {
    $$("#resScope button").forEach(b => {
      b.setAttribute("aria-checked", String(b.dataset.s === S.scope));
      b.onclick = () => { S.scope = b.dataset.s; store.set("radar.resScope", S.scope); S.limit = 30; bindTools(); render(); };
    });
    const q = $("#resQ"); if (q) q.oninput = () => { S.q = q.value.trim(); S.limit = 30; render(); };
  }
  function exportCSV() {
    const rows = [["tarih", "hisse", "kurum", "tavsiye", "degisim", "hedef", "onceki", "para", "kaynak", "baglanti"],
      ...(S.data?.notes || []).map(n => [n.ts, n.t || n.name || "", n.broker, n.rating || "", n.action || "", n.tp ?? "", n.prev ?? "", n.cur || "", n.src, n.url])];
    const csv = rows.map(r => r.map(v => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\n");
    const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv" })); a.download = "araci-kurum-notlari.csv"; a.click();
  }
  bindTools();
  sh.register("arastirma", {
    onShow() { S.loaded ? render() : (render(), load()); },
    onMarket() { render(); },
    async refresh() { S.loaded = false; render(); await load(); },
    exports: () => [{ label: "Aracı kurum notları (CSV)", hint: "tüm notlar, 120 gün", run: exportCSV, disabled: !S.data }],
    exportInfo: () => S.data ? `${(S.data.notes || []).length} not` : "",
    exportNote: "Araştırma verisi henüz yüklenmedi",
  });
})();
