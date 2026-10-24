/* Lyra Radar — hisse ve sayfa paleti (Ctrl/⌘ K ya da /).
   Hangi sekmede olursan ol: hisse ara → hisse paneli, temel analiz kartı, sinyal akışında süz, sektör emsalleriyle karşılaştır,
   portföye ekle; ya da sayfa adına göre sekmeye git. Hisse evreni: temel analiz evreni (BIST Tüm) + izleme listesi (ABD dahil).
   Sayfa içindeki .tk-open[data-sym] öğeleri de evrensel hisse panelini açar. */
(() => {
  "use strict";
  const sh = window.shell;
  const { $, $$, esc, fmt, fold } = sh;
  const PAGES = [["bugun", "Bugün"], ["sinyal", "Sinyal Takip"], ["olay-karnesi", "Olay Karnesi"], ["takvim", "Takvim"], ["arastirma", "Araştırma"], ["geri-alim", "Şirket Geri Alım"],
    ["temel", "Temel Analiz · Genel Bakış"], ["tarama", "Tarama"], ["karsilastir", "Karşılaştır"], ["bankalar", "Türk Bankaları"], ["banka-faiz", "Banka Faiz Duyarlılığı · NIM"],
    ["enerji", "Enerji Kurulu Güç"], ["enerji/harita", "Enerji · Harita"], ["enerji/degerleme", "Enerji · Değerleme"], ["makro", "Makro Veri"],
    ["regulasyon", "Uluslararası Regülasyon Takip"], ["portfoy", "Portföy"], ["metodoloji", "Metodoloji"]];
  const P = { el: null, items: [], i: 0, open: false, from: null };

  function universe() {
    const out = new Map();
    for (const r of window.radarFundamentals?.all || []) out.set(r.code, { sym: r.code, name: r.title, sector: r.sector, market: "BIST", price: r.price, grade: r.grade });
    for (const w of window.radar?.state?.feed?.watchlist || []) {
      const o = out.get(w.symbol) || { sym: w.symbol, market: w.market };
      o.name = o.name || w.name; o.watch = true; out.set(w.symbol, o);
    }
    const held = window.radarPortfolio?.held?.() || new Set();
    held.forEach(t => { const o = out.get(t) || { sym: t, market: "BIST" }; o.held = true; out.set(t, o); });
    return [...out.values()];
  }
  function actions(t) {
    const fin = window.radarFundamentals?.row(t.sym);
    const peers = fin ? window.radarFundamentals.peers(t.sym, 2) : [];
    return [
      { k: "panel", l: "Hisse paneli", d: "haberler, teknik, değerleme, aracı kurum hedefleri, geri alım", run: () => window.radar?.openTicker(t.sym, P.from) },
      fin && { k: "fa", l: "Temel analiz kartı", d: `not ${fin.grade || "—"} · ${esc(fin.sector || "")}`, run: () => sh.go("hisse", { param: t.sym }) },
      { k: "sig", l: "Sinyal akışında süz", d: "bu hissenin tüm haber ve bildirimleri", run: () => { sh.go("sinyal"); setTimeout(() => window.radar?.focusTicker?.(t.sym), 60); } },
      peers.length && { k: "cmp", l: `Emsalleriyle karşılaştır (${peers.join(", ")})`, d: "aynı sektör, piyasa değeri en yakın", run: () => sh.go("karsilastir", { param: [t.sym, ...peers].join(",") }) },
      { k: "pf", l: t.held ? "Portföyde · pozisyonu aç" : "Portföye ekle", d: "yalnız bu tarayıcıda", run: () => { sh.go("portfoy"); setTimeout(() => window.radarPortfolio?.startAdd?.(t.sym, t.market), 60); } },
    ].filter(Boolean);
  }
  function search(q) {
    const f = fold(q), F = f.toUpperCase();
    if (!f) {
      const mine = universe().filter(t => t.watch || t.held).slice(0, 8);
      return [...mine.map(t => ({ type: "tk", t })), ...PAGES.slice(0, 6).map(([r, l]) => ({ type: "pg", r, l }))];
    }
    const cf = sh.compact(q);
    const score = t => { const s = t.sym.toUpperCase(), n = fold(t.name || ""), c = sh.compact(t.name || "");
      return s === F ? 100 : s.startsWith(F) ? 80 - s.length : n.startsWith(f) ? 60 : n.split(" ").some(w => w.startsWith(f)) ? 45
        : c.startsWith(cf) && cf.length > 2 ? 44 : n.includes(f) || s.includes(F) ? 30 : cf.length > 2 && c.includes(cf) ? 25 : 0; };
    const tks = universe().map(t => [t, score(t) + (t.held ? 6 : t.watch ? 4 : 0)]).filter(([, s]) => s > 4).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([t]) => t);
    const out = [];
    tks.forEach((t, j) => { out.push({ type: "tk", t }); if (j === 0) actions(t).forEach(a => out.push({ type: "act", t, a })); });
    PAGES.filter(([r, l]) => fold(l).includes(f) || r.includes(f)).slice(0, 4).forEach(([r, l]) => out.push({ type: "pg", r, l }));
    return out;
  }
  function row(x, i) {
    const on = i === P.i ? " on" : "";
    if (x.type === "tk") { const t = x.t;
      return `<li role="option" id="cmd${i}" class="cmd-i cmd-tk${on}" data-i="${i}" aria-selected="${!!on}"><b class="cmd-sym">${esc(t.sym)}</b><span class="cmd-n">${esc(t.name || "")}</span>
        <span class="cmd-m">${t.held ? `<span class="tag up">portföyde</span>` : t.watch ? `<span class="tag">izleme</span>` : ""}${t.grade ? ` <span class="tag na" data-tip="Temel analiz notu">not ${esc(t.grade)}</span>` : ""}${t.price ? ` <span class="mono">${fmt.num(t.price, 2)}</span>` : ""}${t.market === "US" ? ` <span class="tag">ABD</span>` : ""}</span></li>`; }
    if (x.type === "act") return `<li role="option" id="cmd${i}" class="cmd-i cmd-act${on}" data-i="${i}" aria-selected="${!!on}"><span class="cmd-arr" aria-hidden="true">→</span><span>${esc(x.a.l)}</span><span class="cmd-d">${x.a.d}</span></li>`;
    return `<li role="option" id="cmd${i}" class="cmd-i cmd-pg${on}" data-i="${i}" aria-selected="${!!on}"><span class="cmd-arr" aria-hidden="true">#</span><span>${esc(x.l)}</span><span class="cmd-d">sayfa</span></li>`;
  }
  function draw() {
    const list = $("#cmdList"), q = $("#cmdQ").value.trim();
    P.items = search(q);
    if (P.i >= P.items.length) P.i = Math.max(0, P.items.length - 1);
    const head = (label, idx) => idx >= 0 ? `<li class="cmd-h" role="presentation">${label}</li>` : "";
    let html = "", last = null;
    P.items.forEach((x, i) => { const g = x.type === "pg" ? "Sayfalar" : !q ? "Benimkiler" : "Hisseler"; if (g !== last) { html += head(g, i); last = g; } html += row(x, i); });
    list.innerHTML = html || `<li class="cmd-empty">“${esc(q)}” için hisse ya da sayfa yok</li>`;
    $("#cmdQ").setAttribute("aria-activedescendant", P.items.length ? `cmd${P.i}` : "");
    $(`#cmd${P.i}`)?.scrollIntoView({ block: "nearest" });
  }
  function pick(i) {
    const x = P.items[i]; if (!x) return;
    close(false);
    if (x.type === "pg") { const [r, p] = x.r.split("/"); sh.go(r, { param: p || "" }); }
    else if (x.type === "act") x.a.run();
    else window.radar?.openTicker(x.t.sym, P.from);
  }
  function build() {
    const el = document.createElement("div");
    el.className = "cmd-wrap"; el.hidden = true;
    el.innerHTML = `<div class="cmd-scrim" data-close></div>
      <div class="cmd" role="dialog" aria-modal="true" aria-label="Hisse ve sayfa ara">
        <div class="cmd-top"><svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="9" cy="9" r="5.5" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="m13.2 13.2 3.3 3.3" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>
          <input id="cmdQ" type="text" placeholder="Hisse kodu ya da şirket adı (THYAO, aselsan…) · sayfa adı" autocomplete="off" spellcheck="false"
            role="combobox" aria-expanded="true" aria-controls="cmdList" aria-autocomplete="list"><kbd>Esc</kbd></div>
        <ul id="cmdList" class="cmd-list" role="listbox" aria-label="Sonuçlar"></ul>
        <div class="cmd-foot"><span><kbd>↑</kbd><kbd>↓</kbd> seç</span><span><kbd>Enter</kbd> aç</span><span><kbd>Tab</kbd> eylemler</span><span>ilk hissenin eylemleri altında</span></div>
      </div>`;
    document.body.append(el);
    el.addEventListener("click", e => { if (e.target.closest("[data-close]")) close(); const li = e.target.closest(".cmd-i"); if (li) pick(+li.dataset.i); });
    el.addEventListener("mousemove", e => { const li = e.target.closest(".cmd-i"); if (li && +li.dataset.i !== P.i) { P.i = +li.dataset.i; $$(".cmd-i", el).forEach(x => { x.classList.toggle("on", +x.dataset.i === P.i); x.setAttribute("aria-selected", String(+x.dataset.i === P.i)); }); } });
    $("#cmdQ", el).addEventListener("input", () => { P.i = 0; draw(); });
    $("#cmdQ", el).addEventListener("keydown", e => {
      if (e.key === "ArrowDown" || (e.key === "Tab" && !e.shiftKey)) { e.preventDefault(); P.i = Math.min(P.items.length - 1, P.i + 1); draw(); }
      else if (e.key === "ArrowUp" || (e.key === "Tab" && e.shiftKey)) { e.preventDefault(); P.i = Math.max(0, P.i - 1); draw(); }
      else if (e.key === "Enter") { e.preventDefault(); pick(P.i); }
      else if (e.key === "Escape") { e.preventDefault(); close(); }
    });
    P.el = el;
  }
  async function open() {
    if (!P.el) build();
    P.from = document.activeElement; P.open = true; P.i = 0;
    P.el.hidden = false; document.documentElement.classList.add("cmd-open");
    const q = $("#cmdQ"); q.value = ""; draw(); q.focus();
    if (!(window.radarFundamentals?.all || []).length) { await window.radarFundamentals?.ready?.(); if (P.open) draw(); }
  }
  function close(restore = true) {
    if (!P.el || P.el.hidden) return;
    P.el.hidden = true; P.open = false; document.documentElement.classList.remove("cmd-open");
    if (restore) P.from?.focus?.();
  }
  document.addEventListener("keydown", e => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.target.isContentEditable;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); P.open ? close() : open(); }
    else if (e.key === "/" && !typing && !P.open) { e.preventDefault(); open(); }
  });
  $("#cmdBtn")?.addEventListener("click", open);
  const kbd = $(".cmd-kbd"); if (kbd && !/Mac|iPhone|iPad/.test(navigator.platform)) kbd.textContent = "Ctrl K";
  // Her sekmede hisse adından evrensel panel: <button class="tk-open" data-sym="THYAO">
  document.addEventListener("click", e => { const b = e.target.closest(".tk-open[data-sym]"); if (b) { e.preventDefault(); e.stopPropagation(); window.radar?.openTicker(b.dataset.sym, b); } }, true);
  window.radarPalette = { open, close };
})();
