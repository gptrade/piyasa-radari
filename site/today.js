/* Lyra Radar — Bugün: her sekmeden günün en önemli birkaç şeyi tek ekranda.
   Kaynaklar sitenin kendi veri dosyaları: feed/digest/macro/research (Sinyal), calendar (Takvim), portföy (bu tarayıcı). Her kart ilgili sekmeye götürür. */
(() => {
  "use strict";
  const sh = window.shell;
  const { $, $$, esc, fmt, glyph, dirCls } = sh;
  const DAY = 864e5;
  const MAT_W = { low: 1, medium: 2, high: 3 };
  const S = { cal: null, sur: null, loaded: false, tmPer: "d1", tmSrc: null };

  async function getJSON(p) {
    try { const r = await fetch(`${p}?t=${Date.now()}`, { cache: "no-store" }); return r.ok ? await r.json() : null; } catch { return null; }
  }
  async function load() {
    const [cal, sur] = await Promise.all([getJSON("data/calendar.json"), getJSON("data/surprise.json")]);
    Object.assign(S, { cal, sur, loaded: true });
    await Promise.race([window.radar?.ready, new Promise(r => setTimeout(r, 8000))]);
    const st = window.radar?.state;
    sh.setUpdated("bugun", st?.feed?.generated || new Date(), { label: "Son tarama", staleMin: 45 });
    render();
  }

  // ─────────────────────────────── parçalar
  const todayKey = () => fmt.dayKey(Date.now());
  const ageH = t => (Date.now() - new Date(t)) / 36e5;
  const card = (id, title, href, body, meta = "") => `<section class="card td-card" aria-labelledby="${id}">
    <div class="card-head"><h2 class="card-title" id="${id}">${title}</h2>${href ? `<a class="link-btn" href="#${href}">Tümü →</a>` : meta ? `<span class="card-meta">${meta}</span>` : ""}</div>${body}</section>`;
  const empty = msg => `<p class="td-empty">${msg}</p>`;

  function digest() {
    const d = window.radar?.state?.digest;
    if (!d?.headline) return "";
    const mood = { olumlu: "up", olumsuz: "down", "karışık": "flat" }[d.mood] || "flat";
    return `<section class="card td-digest" aria-labelledby="tdDg">
      <div class="td-dg-top"><span class="tag ${mood}">${esc(d.mood || "")}</span><span class="card-meta">son ${d.window_hours || 2} saatin özeti · ${fmt.ago(d.generated, true)}</span></div>
      <h2 class="td-dg-h" id="tdDg">${esc(d.headline)}</h2><p class="td-dg-s">${esc(d.summary || "")}</p>
      ${(d.ideas || []).length ? `<div class="td-ideas">${d.ideas.slice(0, 4).map(i => `<button type="button" class="td-idea" data-tk="${esc(i.ticker)}" data-tip="${esc(i.rationale || "")}${i.risk ? `<br><b>Risk:</b> ${esc(i.risk)}` : ""}">
        <b>${esc(i.ticker)}</b><span class="tag">${esc(i.stance || "")}</span><span class="td-idea-t">${esc(i.title || "")}</span>${i.conviction ? `<span class="meta">%${i.conviction}</span>` : ""}</button>`).join("")}</div>` : ""}</section>`;
  }
  function sectorLine(g) {
    const s = g?.sectors || [], q = k => s.filter(x => x.quad === k).slice(0, 4).map(x => `<a href="#piyasa-gucu/sektor">${esc(window.radarMarket.short(x.name))}</a>`).join(", ");
    return [q("lider") && `lider sektörler: ${q("lider")}`, q("iyilesen") && `iyileşen: ${q("iyilesen")}`].filter(Boolean).join(" · ") || "";
  }
  function signals(hours) {
    const items = window.radar?.state?.feed?.items || [];
    return items.filter(i => { const a = i.analysis; return a && a.sentiment !== "neutral" && a.confidence >= 70 && a.materiality !== "low" && ageH(i.published) <= hours; })
      .sort((x, y) => score(y) - score(x));
  }
  const score = it => { const a = it.analysis; return MAT_W[a.materiality] * a.confidence * Math.max(0.2, 1 - ageH(it.published) / 48) * (1 + Math.min(it.dups || 0, 10) * 0.05); };
  // Aynı hisse listeyi doldurmasın: hisse başına en fazla 2 haber
  function diverse(rows, n, per = 2) {
    const c = new Map(), out = [];
    for (const it of rows) { const k = (it.tickers || [])[0] || it.market; if ((c.get(k) || 0) >= per) continue; c.set(k, (c.get(k) || 0) + 1); out.push(it); if (out.length >= n) break; }
    return out;
  }
  function signalCard() {
    const held = window.radarPortfolio?.held?.() || new Set();
    const all = signals(24), rows = diverse(all, 7);
    const up = all.filter(i => i.analysis.sentiment === "bullish").length, dn = all.length - up;
    const body = rows.length ? `<div class="ts-bal" aria-label="Son 24 saatte ${up} olumlu, ${dn} olumsuz sinyal"><span class="ts-bar"><i class="up" style="flex:${up || 0.001}"></i><i class="down" style="flex:${dn || 0.001}"></i></span>
        <span class="t3"><b class="up">${up}</b> olumlu · <b class="down">${dn}</b> olumsuz · son 24 saat</span></div>
      <ul class="ts-list">${rows.map(it => { const a = it.analysis, d = a.sentiment === "bullish" ? 1 : -1, tk = (it.tickers || [])[0];
      return `<li><button type="button" class="ts-row" data-item="${esc(it.id)}">
        <span class="ts-dir ${dirCls(d)}" aria-label="${d > 0 ? "olumlu" : "olumsuz"}">${d > 0 ? "▲" : "▼"}</span>
        <span class="ts-main"><span class="ts-top"><b class="ts-tk">${esc(tk || it.market)}</b>${held.has(tk) ? `<span class="mine-dot" data-tip="Portföyünde">●</span>` : ""}
          ${a.materiality === "high" ? `<span class="tag warn">önemli</span>` : ""}${a.event_label || a.category ? `<span class="ts-cat">${esc(a.event_label || a.category)}</span>` : ""}
          <span class="ts-meta">${esc(it.source || "")} · ${fmt.ago(it.published)}</span></span>
          <span class="ts-title">${esc(a.headline_tr || it.title)}</span></span></button></li>`; }).join("")}</ul>
      ${all.length > rows.length ? `<p class="ts-more t3">${all.length - rows.length} sinyal daha · <a href="#sinyal">Sinyal Takip →</a></p>` : ""}`
      : empty("Son 24 saatte güçlü sinyal yok.");
    return card("tdSig", "Öne çıkan sinyaller", "sinyal", body);
  }

  // ── takvim: bugün ve yarın; az önemli bilançolar bölge başına tek satır
  const SESS = { bmo: "açılış önc.", amc: "kapanış snr." };
  const RG = { TR: "TR", US: "ABD", EU: "AB", UK: "UK", JP: "JP" };
  const regionOf = e => e.region || ({ BIST: "TR", US: "US", EU: "EU" })[e.market] || "TR";
  function calEvents(dayOffset) {
    const evs = S.cal?.events || [];
    const key = fmt.dayKey(Date.now() + dayOffset * DAY);
    return evs.filter(e => e.date === key && (e.importance || 0) >= 2).sort((a, b) => (b.importance - a.importance) || (a.when || "").localeCompare(b.when || ""));
  }
  function cpi(e) {
    const d = S.sur; if (e.key !== "tufe" || !d || !e.period) return "";
    const lab = m => `${["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"][+m.slice(5, 7) - 1]} ${m.slice(0, 4)}`;
    const r = (d.rows || []).find(x => lab(x.m) === e.period);
    if (r) return `<span class="tc-x ${r.sur >= d.band ? "down" : r.sur <= -d.band ? "up" : ""}">%${fmt.num(r.act, 2)} · bkl. %${fmt.num(r.exp, 2)}</span>`;
    return d.pending?.label === e.period ? `<span class="tc-x">bkl. %${fmt.num(d.pending.exp, 2)}</span>` : "";
  }
  function calRows(list) {
    const keep = [], grp = new Map();
    for (const e of list) {
      if (e.kind === "earnings" && e.importance < 3 && !(window.radar?.state?.feed?.watchlist || []).some(w => w.symbol === e.ticker)) {
        const k = regionOf(e); (grp.get(k) || grp.set(k, []).get(k)).push(e);
      } else keep.push(e);
    }
    const now = Date.now();
    const row = e => { const past = e.timed && e.when && new Date(e.when) < now;
      const tm = e.timed && e.when ? fmt.clock(e.when) : SESS[e.session] || (e.kind === "earnings" ? "gün içi" : "gün boyu");
      const lbl = e.kind === "earnings" && e.ticker ? `${e.name && regionOf(e) !== "TR" ? e.name : e.ticker} bilanço` : e.title.split(" · ")[0];
      return `<li class="tc-row k-${e.kind} i${e.importance}${past ? " past" : ""}"><span class="tc-t">${esc(tm)}</span><span class="tc-dot" aria-hidden="true"></span>
        <span class="tc-n">${esc(lbl)}${e.period && e.kind !== "earnings" ? ` <span class="t3">${esc(e.period)}</span>` : ""}${cpi(e)}</span><span class="tc-r">${RG[regionOf(e)] || ""}</span></li>`; };
    const g = [...grp].map(([r, xs]) => `<li class="tc-row k-earnings i2"><span class="tc-t">—</span><span class="tc-dot" aria-hidden="true"></span>
      <span class="tc-n">${xs.length} bilanço <span class="t3">${esc(xs.slice(0, 4).map(e => e.name && r !== "TR" ? e.name : e.ticker).join(", "))}${xs.length > 4 ? "…" : ""}</span></span><span class="tc-r">${RG[r] || ""}</span></li>`);
    const timed = keep.sort((a, b) => (a.when || "~").localeCompare(b.when || "~"));
    return timed.map(row).concat(g).join("");
  }
  function calCard() {
    const t = calEvents(0), y = calEvents(1);
    const hi = t.filter(e => e.importance >= 3).length;
    const body = (t.length ? `<h3 class="td-h3">Bugün <span class="t3">· ${hi} yüksek önemli</span></h3><ul class="tc-list">${calRows(t)}</ul>` : empty("Bugün önemli olay yok.")) +
      (y.length ? `<h3 class="td-h3">Yarın</h3><ul class="tc-list">${calRows(y)}</ul>` : "");
    return card("tdCal", "Takvim", "takvim", body);
  }
  function pfCard() {
    const pf = window.radarPortfolio?.summary?.();
    if (!pf?.n) return "";
    const al = pf.alerts.map(a => `<li><span class="td-tk">${esc(a.sym)}</span><span class="tag ${a.c}">${esc(a.t)}</span><span class="td-t">${fmt.num(a.last, 2)}</span></li>`).join("");
    const mv = pf.movers.map(m => `<li><button type="button" class="td-row" data-tk="${esc(m.sym)}"><span class="td-tk">${esc(m.sym)}</span><span class="td-t ${dirCls(m.chg)}">${glyph(m.chg)} ${fmt.pct(m.chg, 2)}</span>
      <span class="td-age">${m.w != null ? "%" + fmt.num(m.w, 1) + " ağırlık" : ""}</span></button></li>`).join("");
    const head = `<div class="tp-sum"><b>${pf.value != null ? fmt.num(pf.value, 0) + " ₺" : "—"}</b>${pf.dayPct != null ? ` <span class="${dirCls(pf.dayPct)}">${glyph(pf.dayPct)} ${fmt.pct(pf.dayPct, 2)} bugün</span>` : ""}</div>`;
    return card("tdPf", "Portföy", "portfoy", head + (al ? `<h3 class="td-h3">Uyarılar</h3><ul class="td-list">${al}</ul>` : "") +
      `<h3 class="td-h3">Günün en çok hareket edenleri</h3>${mv ? `<ul class="td-list">${mv}</ul>` : empty("Fiyatlar henüz yüklenmedi.")}`);
  }
  // ── geri alım: son bildirim gününün en büyük alımları
  function bbCard() {
    const bb = window.radarBB?.latest?.(6);
    if (!bb) { window.radarBB?.ensure?.(); return ""; }
    const mx = Math.max(...bb.rows.map(r => r.amount), 1), tl = v => v >= 1e9 ? `${fmt.num(v / 1e9, 2)} mr ₺` : `${fmt.num(v / 1e6, 1)} mn ₺`;
    const day = fmt.date(bb.day + "T12:00:00Z", { day: "numeric", month: "long", weekday: "long" });
    return card("tdBb", "Şirket geri alımları", "geri-alim", `<p class="t3 tb-sub">${esc(day)} · ${bb.n} şirket · toplam ${tl(bb.total)}</p>
      <ul class="tb-list">${bb.rows.map(r => `<li><button type="button" class="tb-row" data-tk="${esc(r.t)}"><span class="td-tk">${esc(r.t)}</span>
        <span class="tb-bar"><i style="width:${Math.max(3, r.amount / mx * 100).toFixed(1)}%"></i></span><span class="tb-v">${tl(r.amount)}${r.pct != null ? ` <small class="t3">%${fmt.num(r.pct, 2)} sermaye</small>` : ""}</span></button></li>`).join("")}</ul>`);
  }
  // ── aracı kurum notları: aynı kurumun aynı gün toplu notları tek satır; tavsiye renkli, hedef ve potansiyel
  const RAT = { AL: "up", "ENDEKSİN ÜZERİNDE": "up", TUT: "flat", "ENDEKSE PARALEL": "flat", SAT: "down", "ENDEKSİN ALTINDA": "down" };
  function researchCard() {
    const all = (window.radar?.state?.research?.notes || []).filter(n => ageH(n.ts) <= 48 && (n.t || n.name) && inMk(n));
    if (!all.length) return "";
    const act = { up: "hedef ↑", down: "hedef ↓", init: "kapsama başladı", upgrade: "tavsiye ↑", downgrade: "tavsiye ↓", keep: "korundu", reiterate: "korundu", maintain: "korundu", set: "" };
    const key = n => `${n.broker}|${fmt.dayKey(n.ts)}|${n.rating || ""}|${n.action || ""}`;
    const by = new Map(); all.forEach(n => (by.get(key(n)) || by.set(key(n), []).get(key(n))).push(n));
    const rows = [];
    for (const xs of by.values()) {
      if (xs.length >= 3) rows.push({ grp: true, n: xs[0], xs });
      else xs.forEach(n => rows.push({ n }));
    }
    rows.sort((a, b) => new Date(b.n.ts) - new Date(a.n.ts));
    const rat = r => r ? `<span class="tag ${RAT[r] || "na"}">${esc(r)}</span>` : "";
    const pot = n => { const p = n.t && window.radar?.state?.prices?.[n.t]?.last || n.px; return n.tp && p ? n.tp / p - 1 : null; };
    const li = r => r.grp
      ? `<li class="tn-row"><span class="tn-b">${esc(r.n.broker)}</span>${rat(r.n.rating)}<span class="tn-chips">${r.xs.slice(0, 8).map(n => `<button type="button" class="tn-chip" data-tk="${esc(n.t || "")}">${esc(n.t || n.name)}</button>`).join("")}${r.xs.length > 8 ? `<span class="t3">+${r.xs.length - 8}</span>` : ""}</span><span class="td-age">${fmt.ago(r.n.ts)}</span></li>`
      : `<li class="tn-row"><a class="tn-a" href="${esc(r.n.url)}" target="_blank" rel="noopener"><span class="td-tk">${esc(r.n.t || r.n.name)}</span><span class="tn-b">${esc(r.n.broker)}</span>${rat(r.n.rating)}
          <span class="tn-x">${act[r.n.action] ? esc(act[r.n.action]) : ""}${r.n.tp ? ` · hedef ${fmt.num(r.n.tp, 2)}${r.n.cur === "USD" ? " $" : ""}` : ""}${pot(r.n) != null ? ` <b class="${pot(r.n) > 0 ? "up" : "down"}">${fmt.pct(pot(r.n) * 100, 0)}</b>` : ""}</span>
          <span class="td-age">${fmt.ago(r.n.ts)}</span></a></li>`;
    return card("tdRs", "Aracı kurum notları", "arastirma", `<p class="t3 tb-sub">son 48 saat · ${all.length} not</p><ul class="tn-list">${rows.slice(0, 8).map(li).join("")}</ul>`);
  }
  const inMk = n => sh.market === "ALL" || (sh.market === "US") === (n.m === "US");

  function render() {
    if (sh.route !== "bugun") return;
    const body = $("#tdBody");
    if (!S.loaded) { body.innerHTML = `<div class="view" aria-busy="true"><div class="kpi-grid">${Array.from({ length: 6 }, () => `<div class="kpi"><div class="skeleton sk-line w60"></div><div class="skeleton sk-line lg w40"></div></div>`).join("")}</div></div>`; return; }
    const d = new Date().toLocaleDateString("tr-TR", { timeZone: sh.TZ, weekday: "long", day: "numeric", month: "long", year: "numeric" });
    $("#tdDate").textContent = d;
    const MK = window.radarMarket;
    const src = S.tmSrc || (sh.market === "US" ? "sp" : "bist"), us = src !== "bist", ndx = src === "ndx";
    queueMicrotask(() => {
      $$("#tdTmP button").forEach(b => b.onclick = () => { S.tmPer = b.dataset.v; render(); });
      $$("#tdTmS button").forEach(b => b.onclick = () => { S.tmSrc = b.dataset.v; render(); });
      $$("#tdTmZ button").forEach(b => b.onclick = () => { S.tmSize = b.dataset.v; render(); });
      MK?.treemap($("#tdTm"), { per: S.tmPer, size: S.tmSize || "mcap", height: innerWidth < 640 ? 360 : 420, maxStocks: ndx ? 101 : us ? 250 : 150, src });
    });
    const keys = MK?.GROUPS?.flatMap(g => g[1]);
    const tmFoot = us ? `${ndx ? "Nasdaq-100'ün tamamı" : "S&P 500'ün en büyük 250 şirketi"} · kutu = piyasa değeri ($), renk = getiri · hisseye tıkla: Yahoo Finance${MK?.data.us?.asof ? ` · ${fmt.date(MK.data.us.asof + "T12:00:00Z")}` : ""}`
      : `En büyük 150 şirket · kutu = ${(S.tmSize || "mcap") === "tv" ? "günlük işlem hacmi" : "piyasa değeri"}, renk = getiri · ${sectorLine(MK?.data.guc)}`;
    const lower = [signalCard(), calCard(), researchCard(), bbCard(), pfCard()].filter(Boolean);
    body.innerHTML = `<div class="view" style="gap:var(--s-4)">${MK?.stripHTML(keys, { groups: true }) || ""}
      <div class="td-regimes">${window.radarGuc?.card() || ""}${MK?.crossCard(true) || ""}</div>
      ${MK?.data.guc || MK?.data.us ? `<section class="card" aria-labelledby="tdTmT"><div class="card-head td-tm-head"><h2 class="card-title" id="tdTmT">Isı haritası</h2>
        <div class="seg seg-sm" role="radiogroup" aria-label="Piyasa" id="tdTmS">${[["bist", "BIST"], ["sp", "S&P 500"], ["ndx", "Nasdaq-100"]].map(([k, l]) => `<button type="button" role="radio" data-v="${k}" aria-checked="${src === k}">${l}</button>`).join("")}</div>
        ${us ? "" : `<div class="seg seg-sm" role="radiogroup" aria-label="Kutu boyutu" id="tdTmZ">${[["mcap", "Piyasa değeri"], ["tv", "İşlem hacmi"]].map(([k, l]) => `<button type="button" role="radio" data-v="${k}" aria-checked="${(S.tmSize || "mcap") === k}">${l}</button>`).join("")}</div>`}
        <div class="seg seg-sm" role="radiogroup" aria-label="Dönem" id="tdTmP">${Object.entries(MK.PERK).map(([k, v]) => `<button type="button" role="radio" data-v="${k}" aria-checked="${S.tmPer === k}">${v[0]}</button>`).join("")}</div>
        ${us ? "" : `<a class="link-btn" href="#piyasa-gucu/harita">Tam ekran →</a>`}</div><div id="tdTm" class="tm-box"></div>
        <p class="t3 gc-foot">${tmFoot}</p></section>` : ""}
      ${digest()}
      <div class="td-grid2">${lower.join("")}</div></div>`;
  }

  $("#tdBody").addEventListener("click", e => {
    const it = e.target.closest("[data-item]"), tk = e.target.closest("[data-tk]");
    if (it) window.radar?.openItem?.(it.dataset.item, it);
    else if (tk) window.radar?.openTicker?.(tk.dataset.tk, tk);
  });
  addEventListener("radar:pf", () => render());
  addEventListener("radar:bb", () => render());
  addEventListener("radar:guc", () => render());
  addEventListener("radar:market", () => render());
  addEventListener("themechange", render);

  sh.register("bugun", {
    onShow() { S.loaded ? render() : (render(), load()); },
    async refresh() { await window.radar?.poll?.(); await load(); },
    exports: () => [],
    exportNote: "Bugün sayfası özet; dışa aktarma ilgili sekmelerden yapılır",
  });
})();
