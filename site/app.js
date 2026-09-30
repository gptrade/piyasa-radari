/* Piyasa Radarı — Sinyal Takip sekmesi.
   Veri: data/feed.json, data/digest.json, data/macro.json, data/prices/<SYMBOL>.json */
(() => {
  "use strict";
  const sh = window.shell;
  const { $, $$, esc, fmt, store, glyph, dirCls } = sh;
  const NS = "http://www.w3.org/2000/svg";
  const MAT_W = { low: 1, medium: 2, high: 3 };
  const MAT_TR = { low: "düşük", medium: "orta", high: "yüksek" };
  const HOR = { intraday: "Gün içi", days: "Birkaç gün", weeks: "Haftalar", long_term: "Uzun vade" };
  const SENT_TR = { bullish: "Yükseliş", bearish: "Düşüş", neutral: "Nötr" };
  const EVENT = {
    measure: "Borsa tedbiri", buyback: "Geri alım", insider: "İçeriden işlem", earnings: "Finansal sonuç", analyst: "Analist",
    dividend: "Temettü / sermaye", deal: "Anlaşma / ihale", regulator: "Düzenleyici (SPK)", macro: "Makro", legal: "Hukuki",
    news: "Haber", social: "Sosyal medya", report: "Rapor",
  };
  const TYPE = { disclosure: "Bildirim", news: "Haber", social: "Sosyal", regulator: "SPK", macro: "Makro", report: "Rapor" };
  const TIER = { 1: "Resmi / birincil kaynak", 2: "Yerleşik finans medyası", 3: "Diğer / sosyal" };
  const PAGE = 10;                         // tablo 10'ar kayıtla açılır; sağ şerit / ısı haritası aşağıda kalmasın

  const state = {
    feed: null, digest: null, macro: null, prices: {}, loading: true, error: null,
    view: "feed", sort: { k: "time", d: -1 }, ticker: null, ids: null, idsLabel: "", focusText: "",
    types: new Set(), q: "", col: {}, hideNoise: store.get("hideNoise", true),
    open: new Set(), saved: new Set(store.get("saved", [])), limit: PAGE, sel: null, tkSort: { k: "n", d: -1 }, stripAll: false,
    seenBefore: null, reasons: new Map(),
  };
  const market = () => sh.market;

  // ─────────────────────────────── yardımcılar
  const ageMin = iso => (Date.now() - new Date(iso)) / 60000;
  const sign = s => s === "bullish" ? 1 : s === "bearish" ? -1 : 0;
  const watchSet = () => new Set((state.feed?.watchlist || []).map(w => w.symbol));
  const watchMarket = sym => (state.feed?.watchlist || []).find(w => w.symbol === sym)?.market;
  const relTickers = it => {
    const w = watchSet(), own = it.tickers || [];
    return [...own, ...(it.analysis?.affected_tickers || []).filter(t => w.has(t) && !own.includes(t))];
  };
  const isSignal = a => a && a.sentiment !== "neutral" && a.confidence >= 70 && a.materiality !== "low";
  const inMarket = it => market() === "ALL" || it.market === market();
  const impact = it => {
    const a = it.analysis;
    if (!a) return 0;
    const rec = Math.max(0.2, 1 - ageMin(it.published) / 2880);
    return MAT_W[a.materiality] * a.confidence * (it.tier === 1 ? 1.2 : 1) * rec * (1 + Math.min(it.dups || 0, 10) * 0.05);
  };
  const since = it => it.reaction && it.reaction.n_after !== 0 ? it.reaction.since : null;
  // Haber yönü ile fiyat tepkisi ters mi? (ısı haritasıyla aynı eşik: ±%0,5)
  const mismatch = it => { const s = since(it), d = sign(it.analysis?.sentiment); return s != null && ((d > 0 && s <= -0.5) || (d < 0 && s >= 0.5)); };

  // Soluk satır nedeni (açık etiketle gösterilir). "tekrar": aynı hisse + aynı olay etiketi 12 saat içinde tekrar geldiyse.
  function computeReasons(items) {
    const m = new Map(), groups = new Map();
    state.dupOf = new Map(); state.similar = new Map();
    for (const it of items) {
      const a = it.analysis, t = it.tickers?.[0];
      if (!a?.event_label || !t) continue;
      const k = t + "|" + a.event_label.toLocaleLowerCase("tr").trim();
      (groups.get(k) || groups.set(k, []).get(k)).push(it);
    }
    for (const g of groups.values()) {
      if (g.length < 2) continue;
      const kept = [];
      g.sort((a, b) => impact(b) - impact(a)).forEach(it => {
        const t = +new Date(it.published), p = kept.find(k => Math.abs(k.t - t) < 12 * 3600e3);
        if (!p) { kept.push({ t, it }); return; }
        m.set(it.id, "tekrar"); state.dupOf.set(it.id, p.it.id);
        (state.similar.get(p.it.id) || state.similar.set(p.it.id, []).get(p.it.id)).push(it);
      });
    }
    for (const it of items) {
      if (m.has(it.id)) continue;
      const a = it.analysis;
      const r = !a ? "AI yok" : a.confidence < 50 ? "düşük güven" : a.materiality === "low" ? "önemsiz"
        : it.tier === 3 && a.materiality !== "high" ? "zayıf kaynak" : ageMin(it.published) > 1440 ? "eski" : null;
      if (r) m.set(it.id, r);
    }
    return m;
  }
  const DIM_IC = r => `<span class="dim-ic" data-tip="<b>Soluk: ${esc(r)}</b><br>${esc(DIM_TIP[r])}"><svg viewBox="0 0 12 12" aria-hidden="true"><circle cx="6" cy="6" r="4.5" fill="none" stroke="currentColor" stroke-width="1.4" stroke-dasharray="2.2 1.6"/></svg><span class="sr-only">soluk: ${esc(r)}</span></span>`;
  const DIM_TIP = {
    "tekrar": "Aynı hisse için aynı olay 12 saat içinde daha güçlü bir kayıtla zaten var",
    "AI yok": "AI değerlendirmesi yapılmadı (izleme listesi dışı ya da tur sınırı)",
    "düşük güven": "AI güveni %50'nin altında",
    "önemsiz": "AI önemi düşük buldu",
    "zayıf kaynak": "Üçüncü sınıf kaynak (sosyal medya vb.) ve önem yüksek değil",
    "eski": "24 saatten eski",
  };

  // ─────────────────────────────── veri
  async function getJSON(path) {
    try { const r = await fetch(`${path}?t=${Date.now()}`); return r.ok ? await r.json() : null; } catch { return null; }
  }
  async function fetchAll() {
    const feed = await getJSON("data/feed.json");
    if (!feed) throw new Error("data/feed.json okunamadı");
    const [digest, macro] = await Promise.all([getJSON("data/digest.json"), getJSON("data/macro.json")]);
    const syms = new Set([...(feed.watchlist || []).map(w => w.symbol), ...feed.items.map(i => i.tickers?.[0]).filter(Boolean)]);
    const prices = {};
    await Promise.all([...syms].map(async s => { const p = await getJSON(`data/prices/${s}.json`); if (p) prices[s] = p; }));
    return { feed, digest, macro, prices };
  }
  async function load() { apply(await fetchAll()); }
  function apply({ feed, digest, macro, prices }) {
    state.pending = null; $("#newPill").hidden = true;
    Object.assign(state, { feed, digest, macro, prices, error: null, loading: false });
    state.reasons = computeReasons(feed.items);
    sh.setUpdated("sinyal", feed.generated, { label: "Son tarama", staleMin: 45 });
    sh.setHealth(feed);
    badge();
  }

  // Sekme rozeti: son ziyaretten bu yana gelen güçlü sinyaller
  function badge() {
    const seen = store.get("radar.sigSeen", null) || new Date(Date.now() - 2 * 3600e3).toISOString();
    const n = state.feed.items.filter(i => isSignal(i.analysis) && i.published > seen).length;
    if (sh.route === "sinyal") { markSeen(seen); sh.setBadge("sinyal", 0); return; }
    sh.setBadge("sinyal", n, `${n} yeni güçlü sinyal (son ziyaretinden bu yana)`);
  }
  function markSeen(prev) {
    if (state.seenBefore == null) state.seenBefore = prev || store.get("radar.sigSeen", null) || "";
    store.set("radar.sigSeen", state.feed.generated);
  }

  // ─────────────────────────────── filtre ve sıralama
  const SORTERS = {
    dir: it => it.analysis ? sign(it.analysis.sentiment) * it.analysis.confidence : null,
    tk: it => relTickers(it)[0] || null,
    imp: it => it.analysis ? impact(it) : null,
    rx: it => since(it),
    src: it => (4 - (it.tier || 3)) * 100 + (it.dups || 0),
    time: it => +new Date(it.published),
  };
  function colMatch(it) {
    const c = state.col, a = it.analysis;
    if (c.dir && (c.dir === "none" ? a : !a || a.sentiment !== c.dir)) return false;
    if (c.ev && it.event !== c.ev) return false;
    if (c.imp) { const w = a ? MAT_W[a.materiality] : 0; if (c.imp === "3" ? w !== 3 : c.imp === "2" ? w < 2 : c.imp === "1" ? w !== 1 : a) return false; }
    if (c.rx) {
      const s = since(it);
      if (c.rx === "mis" ? !mismatch(it) : c.rx === "none" ? s != null : s == null || (c.rx === "up" ? s <= 0 : s >= 0)) return false;
    }
    if (c.tier && (c.tier === "3" ? it.tier !== 3 : c.tier === "1" ? it.tier !== 1 : it.tier === 3)) return false;
    if (c.age && ageMin(it.published) > +c.age) return false;
    return true;
  }
  function filtered(grouped = true) {
    const q = state.q.toLocaleLowerCase("tr");
    let out = state.feed.items.filter(it => {
      if (!inMarket(it)) return false;
      if (state.ids && !state.ids.has(it.id)) return false;
      if (state.ticker && !relTickers(it).includes(state.ticker)) return false;
      if (state.view === "saved" && !state.saved.has(it.id)) return false;
      if (state.view === "signals" && !isSignal(it.analysis)) return false;
      if (state.types.size && !state.types.has(it.source_type)) return false;
      if (!colMatch(it)) return false;
      if (state.hideNoise && state.reasons.has(it.id) && !state.saved.has(it.id)) return false;
      if (q) {
        const a = it.analysis || {};
        if (!`${it.title} ${it.summary} ${it.source} ${relTickers(it).join(" ")} ${a.event_label || ""} ${a.what || ""} ${a.summary || ""}`.toLocaleLowerCase("tr").includes(q)) return false;
      }
      return true;
    });
    if (grouped) {                                   // benzer haber, ana kaydı listedeyse ayrı satır olmaz
      const ids = new Set(out.map(i => i.id));
      out = out.filter(it => !(state.dupOf?.has(it.id) && ids.has(state.dupOf.get(it.id))));
    }
    const f = SORTERS[state.sort.k], d = state.sort.d;
    return out.map(it => [it, f(it)]).sort(([a, va], [b, vb]) => {
      if (va == null && vb == null) return SORTERS.time(b) - SORTERS.time(a);
      if (va == null) return 1;
      if (vb == null) return -1;
      const c = typeof va === "string" ? va.localeCompare(vb, "tr") : va - vb;
      return c * d || SORTERS.time(b) - SORTERS.time(a);
    }).map(([it]) => it);
  }
  const activeFilters = () => state.types.size + Object.values(state.col).filter(Boolean).length + (state.q ? 1 : 0) + (state.ticker || state.ids ? 1 : 0);

  // ─────────────────────────────── tablo başlığı (sıralama + sütun filtresi)
  const FUNNEL = `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2.5 3h11l-4.2 5v4.5l-2.6 1.3V8L2.5 3z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>`;
  const COLS = [
    { k: "dir", cls: "c-dir", label: "Yön", sort: "dir", f: "dir", tip: "AI'ın haberi yorumlama yönü: ▲ yükseliş · ▼ düşüş · ● nötr",
      opts: [["", "Tümü"], ["bullish", "▲ Yükseliş"], ["bearish", "▼ Düşüş"], ["neutral", "● Nötr"], ["none", "N/A · AI yok"]] },
    { k: "tk", cls: "c-tk", label: "Hisse", sort: "tk", f: "tk", tip: "Haberde geçen ya da AI'ın etkileneceğini söylediği hisse; +1 = başka hisseler de var" },
    { k: "ol", cls: "c-ol", label: "Olay", f: "ev", tip: "AI'ın olay etiketi ve kısa özeti · kaynak adı. Soluk satırlarda neden etiketi başta yazar." },
    { k: "imp", cls: "c-imp", label: "Önem", sort: "imp", f: "imp", tip: "Fiyatı hareket ettirme potansiyeli (3 seviye). Sıralama önem × güven × kaynak × tazelik skoruna göre.",
      opts: [["", "Tümü"], ["3", "Yüksek"], ["2", "Orta ve üstü"], ["1", "Düşük"], ["na", "N/A · AI yok"]] },
    { k: "rx", cls: "c-rx num", label: "Tepki", sort: "rx", f: "rx", tip: "Haber anındaki fiyattan bu yana değişim · ≠ haber yönü ile fiyat ters",
      opts: [["", "Tümü"], ["up", "▲ Yükselen"], ["down", "▼ Düşen"], ["mis", "≠ Haberle ters"], ["none", "İşlem yok / N/A"]] },
    { k: "src", cls: "c-src", label: "Kaynak", sort: "src", f: "tier", tip: "Kaynak türü ve kaç kaynakta geçtiği (×N). Resmi kaynaklar vurgulu.",
      opts: [["", "Tümü"], ["1", "Yalnız resmi"], ["2", "Resmi + finans medyası"], ["3", "Diğer / sosyal"]] },
    { k: "time", cls: "c-age num", label: "Zaman", sort: "time", f: "age", tip: "Yayından bu yana geçen süre",
      opts: [["", "Tümü"], ["60", "Son 1 saat"], ["360", "Son 6 saat"], ["1440", "Son 24 saat"], ["4320", "Son 3 gün"]] },
  ];
  function head() {
    const items = state.feed ? state.feed.items.filter(inMarket) : [];
    const w = watchSet();
    const tks = [...new Set(items.flatMap(relTickers))].sort((a, b) => (w.has(b) - w.has(a)) || a.localeCompare(b));
    const evs = [...new Set(items.map(i => i.event).filter(Boolean))].sort((a, b) => (EVENT[a] || a).localeCompare(EVENT[b] || b, "tr"));
    const dyn = { tk: [["", "Tümü"], ...tks.map(t => [t, t + (w.has(t) ? " ●" : "")])], ev: [["", "Tümü"], ...evs.map(e => [e, EVENT[e] || e])] };
    const cur = { tk: state.ticker || "" };
    $("#sigHead").innerHTML = `<tr>${COLS.map(c => {
      const sorted = c.sort && state.sort.k === c.sort;
      const aria = c.sort ? `aria-sort="${sorted ? (state.sort.d > 0 ? "ascending" : "descending") : "none"}"` : "";
      const opts = c.opts || dyn[c.f];
      const val = cur[c.f] ?? state.col[c.f] ?? "";
      const lbl = c.sort
        ? `<button type="button" class="th-sort" data-sort="${c.sort}" data-tip="${esc(c.tip)}<br><i>Sıralamak için tıkla</i>">${c.label}<span class="arr" aria-hidden="true">${sorted ? (state.sort.d > 0 ? "▲" : "▼") : "▼"}</span></button>`
        : `<span data-tip="${esc(c.tip)}">${c.label}</span>`;
      const filt = opts ? `<span class="th-filter ${val ? "on" : ""}" data-tip="${c.label} filtresi${val ? ": " + esc(opts.find(o => o[0] === val)?.[1] || val) : ""}">${FUNNEL}
        <select data-f="${c.f}" aria-label="${c.label} filtresi">${opts.map(([v, l]) => `<option value="${esc(v)}" ${v === val ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></span>` : "";
      return `<th scope="col" class="${c.cls}" ${aria}><span class="th-in">${lbl}${filt}</span></th>`;
    }).join("")}</tr>`;
    $$("#sigHead .th-sort").forEach(b => b.onclick = () => {
      const k = b.dataset.sort;
      state.sort = state.sort.k === k ? { k, d: -state.sort.d } : { k, d: k === "tk" ? 1 : -1 };
      state.limit = PAGE; render();
      $(`#sigHead .th-sort[data-sort="${k}"]`)?.focus();
    });
    $$("#sigHead select").forEach(sel => sel.onchange = () => {
      const f = sel.dataset.f;
      if (f === "tk") { state.ticker = sel.value || null; state.ids = null; state.idsLabel = ""; state.focusText = ""; }
      else if (f === "imp" && sel.value === "na") state.col.imp = "na";
      else state.col[f] = sel.value;
      state.limit = PAGE; render();
      $(`#sigHead select[data-f="${f}"]`)?.focus();
    });
  }

  // ─────────────────────────────── satır
  const NA = tip => `<span class="tag na" data-tip="${esc(tip)}">N/A</span>`;
  function dirHTML(a) {
    if (!a) return NA("AI değerlendirmesi yok");
    const k = sign(a.sentiment);
    return `<span class="dir ${dirCls(k)}" data-tip="<b>${SENT_TR[a.sentiment]}</b> · %${a.confidence} güven">${glyph(k)}<span class="sr-only">${SENT_TR[a.sentiment]}, yüzde ${a.confidence} güven</span></span>`;
  }
  function rxHTML(it) {
    const r = it.reaction;
    if (r && r.n_after === 0) return `<span class="rx-wait" data-tip="Haberden sonra henüz işlem olmadı (seans kapalı)">…</span>`;
    const s = since(it);
    if (s == null) return NA(state.prices[relTickers(it)[0]] ? "Haber zamanı için fiyat yok" : "Fiyat verisi yok (izleme listesi dışı ya da piyasa geneli)");
    const k = Math.abs(s) < 0.05 ? 0 : s;
    const parts = [`Haberden bu yana <b>${fmt.pct(s, 2)}</b>`];
    if (r.vol_x) parts.push(`hacim ${fmt.num(r.vol_x, 1)}×`);
    if (r.index_since != null) parts.push(`endeks ${fmt.pct(r.index_since, 2)}`);
    const mis = mismatch(it) ? `<span class="mis" data-tip="<b>≠ Haber ile fiyat ters</b><br>AI ${SENT_TR[it.analysis.sentiment].toLocaleLowerCase("tr")} dedi, fiyat ${fmt.pct(s, 2)}">≠</span>` : "";
    return `${mis}<span class="rx ${dirCls(k)}" data-tip="${parts.join(" · ")}">${glyph(k)} ${fmt.pct(s)}</span>`;
  }
  const sims = it => (state.similar?.get(it.id) || []).filter(inMarket);
  const simBadge = it => { const n = sims(it).length; return n ? `<span class="sim" data-tip="Aynı olay için ${n} benzer haber daha (12 saat içinde).<br>Ayrıntıda listelenir.">+${n} benzer</span>` : ""; };
  function rowHTML(it) {
    const a = it.analysis, tks = relTickers(it), reason = state.reasons.get(it.id);
    const more = tks.length > 1 ? `<span class="tk-more" data-tip="Ayrıca: ${esc(tks.slice(1).join(", "))}">+${tks.length - 1}</span>` : "";
    const tk = tks.length ? `<span class="tk"><span class="tk-sym">${esc(tks[0])}</span>${more}</span>`
      : `<span class="tk-gen" data-tip="Belirli bir hisse yok: piyasa geneli">${it.market === "BIST" ? "BIST" : "ABD"} geneli</span>`;
    const isNew = state.seenBefore && it.published > state.seenBefore && isSignal(a);
    const text = a?.event_label ? `<b>${esc(a.event_label)}</b> · ${esc(a.what || a.headline_tr || it.title)}` : esc(a?.headline_tr || it.title);
    const full = `<b>${esc(it.title)}</b>${a?.what ? `<hr>${esc(a.what)}` : ""}<hr>${esc(it.source)} · ${fmt.dt(it.published)}`;
    const imp = a ? `<span class="imp-cell" data-tip="Önem: <b>${MAT_TR[a.materiality]}</b>"><span class="meter" data-l="${MAT_W[a.materiality]}" role="img" aria-label="Önem ${MAT_TR[a.materiality]}"><i></i><i></i><i></i></span></span>` : NA("AI değerlendirmesi yok");
    const t1 = it.tier === 1;
    const srcTip = `<b>${esc(it.source)}</b><br>${TIER[it.tier || 3]}${it.dups ? `<hr>Aynı haber ${it.dups + 1} kaynakta:<br>${esc([it.source, ...(it.dup_sources || [])].join(", "))}` : ""}`;
    return `<tr class="row${reason ? " dim" : ""}${state.open.has(it.id) ? " open" : ""}" data-id="${it.id}" tabindex="0" aria-expanded="${state.open.has(it.id)}">
      <td class="c-dir">${dirHTML(a)}</td>
      <td class="c-tk">${tk}</td>
      <td class="c-ol"><div class="ol-t" data-tip="${esc(full)}">${isNew ? `<span class="new-dot" aria-label="yeni"></span>` : ""}${reason ? DIM_IC(reason) : ""}${simBadge(it)}${text} <span class="ol-src">· ${esc(it.source.split(" · ")[0])}</span></div></td>
      <td class="c-imp">${imp}</td>
      <td class="c-rx num">${rxHTML(it)}</td>
      <td class="c-src"><span class="src-cell" data-tip="${esc(srcTip)}"><span class="${t1 ? "t1" : ""}">${TYPE[it.source_type] || "Haber"}</span>${it.dups ? ` <span class="x">×${it.dups + 1}</span>` : ""}</span></td>
      <td class="c-age num"><span class="age" data-tip="${esc(fmt.full(it.published))}">${fmt.ago(it.published)}</span></td>
    </tr>`;
  }

  // ─────────────────────────────── detay çekmecesi
  function drawer(it) {
    const tr = document.createElement("tr");
    tr.className = "drawer";
    const td = document.createElement("td");
    td.colSpan = 7;
    td.append(detailContent(it)); tr.append(td);
    tr.addEventListener("click", e => e.stopPropagation());
    return tr;
  }
  function detailContent(it) {
    const a = it.analysis, tks = relTickers(it), reason = state.reasons.get(it.id);
    const first = s => (s || "").split(/(?<=[.!?])\s/)[0];
    const left = document.createElement("div");
    const k = a ? sign(a.sentiment) : null;
    const saved = state.saved.has(it.id);
    left.innerHTML = `
      <h3 class="d-title">${it.url ? `<a href="${esc(it.url)}" target="_blank" rel="noopener">${esc(it.title)}</a>` : esc(it.title)}</h3>
      <p class="d-meta">
        ${a ? `<span class="tag ${dirCls(k)}">${glyph(k)} ${SENT_TR[a.sentiment]} · %${a.confidence} güven</span><span class="tag">Önem: ${MAT_TR[a.materiality]}</span>${a.horizon ? `<span class="tag">${HOR[a.horizon] || esc(a.horizon)}</span>` : ""}` : `<span class="tag na">AI yok</span>`}
        ${reason ? `<span class="tag warn">${reason}</span>` : ""}<span>${fmt.full(it.published)}</span>${a?.provider ? `<span>· ${esc(a.provider)}</span>` : ""}
      </p>
      ${a ? `<dl class="slots"><dt>Ne oldu</dt><dd>${esc(a.what || a.headline_tr || it.title)}</dd><dt>Neden önemli</dt><dd>${esc(a.why || first(a.summary) || "—")}</dd>
        <dt>Risk</dt><dd class="risk">${esc(a.risk || a.risks?.[0] || "—")}</dd></dl>${a.summary ? `<p class="d-sum">${esc(a.summary)}</p>` : ""}` : ""}
      ${it.summary && it.summary !== it.title ? `<p class="d-sub">Orijinal metin</p><p class="d-sum">${esc(it.summary)}</p>` : ""}
      <p class="d-sub">Kaynaklar</p>
      <ul class="d-sources">
        <li><span class="tag ${it.tier === 1 ? "accent" : ""}">${TYPE[it.source_type] || "Haber"}</span><span>${esc(it.source)} · ${TIER[it.tier || 3]}</span>${it.url ? `<a href="${esc(it.url)}" target="_blank" rel="noopener">Habere git ↗</a>` : ""}</li>
        ${sims(it).map(x => `<li><span class="tag">benzer</span><span>${esc(x.analysis?.what || x.title)} · ${esc(x.source.split(" · ")[0])}</span><span class="sim-time">${fmt.ago(x.published)}</span>${x.url ? `<a href="${esc(x.url)}" target="_blank" rel="noopener">Aç ↗</a>` : ""}</li>`).join("")}
        ${(it.dup_sources || []).map(s => `<li><span class="tag">aynı haber</span><span>${esc(s)}</span><a href="https://news.google.com/search?q=${encodeURIComponent(it.title)}&hl=tr" target="_blank" rel="noopener">Ara ↗</a></li>`).join("")}
      </ul>
      <div class="d-actions">
        <button type="button" class="btn" data-a="save" aria-pressed="${saved}">${saved ? "✓ Kaydedildi" : "Kaydedilenlere kaydet"}</button>
        ${tks[0] ? `<button type="button" class="btn" data-a="tk">Yalnız ${esc(tks[0])}</button>` : ""}
        ${it.url ? `<a class="btn" href="${esc(it.url)}" target="_blank" rel="noopener">Kaynağa git ↗</a>` : ""}
      </div>`;
    $$(".d-actions button", left).forEach(b => b.onclick = e => {
      e.stopPropagation();
      if (b.dataset.a === "tk") { state.ticker = tks[0]; state.ids = null; state.idsLabel = ""; state.focusText = ""; state.limit = PAGE; render(); return; }
      state.saved.has(it.id) ? state.saved.delete(it.id) : state.saved.add(it.id);
      store.set("saved", [...state.saved]);
      const on = state.saved.has(it.id);
      b.setAttribute("aria-pressed", on); b.textContent = on ? "✓ Kaydedildi" : "Kaydedilenlere kaydet";
      counts();
    });
    const inner = document.createElement("div");
    inner.className = "drawer-in";
    inner.append(left, pricePanel(it));
    return inner;
  }

  // ─────────────────────────────── fiyat paneli (grafik parçacığı + teknik görünüm)
  const EMA_KEYS = ["14", "34", "55", "200"];
  function seriesFor(p, range) {
    if (!p) return { bars: [], ema: null };
    const now = (p.intraday?.at(-1) || p.daily?.at(-1) || [0])[0];
    const daily = p.daily || [];
    const dailyRange = days => {
      const idx = daily.map((b, i) => [b, i]).filter(([b]) => b[0] >= now - days * 86400).map(([, i]) => i);
      const ema = p.ema ? Object.fromEntries(EMA_KEYS.filter(k => p.ema[k]).map(k => [k, idx.map(i => p.ema[k][i])])) : null;
      return { bars: idx.map(i => daily[i]), ema };
    };
    if (range === "1A") return dailyRange(31);
    if (range === "3A") return dailyRange(93);
    if (range === "6A") return dailyRange(190);
    if (range === "1H") return { bars: (p.intraday || []).filter(b => b[0] >= now - 7 * 86400), ema: null };
    const bars = p.intraday || [];
    if (!bars.length) return { bars: daily.slice(-2), ema: null };
    const day = t => fmt.dayKey(t * 1000);
    const last = day(bars.at(-1)[0]);
    return { bars: bars.filter(b => day(b[0]) === last), ema: null };
  }
  function drawSpark(svg, { bars, ema }, newsTs) {
    svg.innerHTML = "";
    if (bars.length < 2) return null;
    const W = 300, H = ema ? 116 : 80, pad = 6, padR = ema ? 26 : 0;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    const t0 = bars[0][0], t1 = bars.at(-1)[0];
    const vals = bars.map(b => b[1]);
    const all = vals.concat(...(ema ? Object.values(ema).map(a => a.filter(v => v != null)) : []));
    const lo = Math.min(...all), hi = Math.max(...all), span = hi - lo || 1;
    const x = t => ((t - t0) / (t1 - t0 || 1)) * (W - padR);
    const y = v => H - pad - ((v - lo) / span) * (H - pad * 2);
    const up = vals.at(-1) >= vals[0];
    const color = ema ? "var(--text)" : up ? "var(--up)" : "var(--down)";
    const path = pts => pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("");
    const d = path(bars.map(b => [x(b[0]), y(b[1])]));
    const mk = (tag, attrs) => { const e = document.createElementNS(NS, tag); Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, v)); return e; };
    if (!ema) svg.append(mk("path", { d: `${d}L${W},${H}L0,${H}Z`, class: "ar", fill: color }));
    if (ema) EMA_KEYS.forEach((k, n) => {
      const pts = (ema[k] || []).map((v, i) => v == null ? null : [x(bars[i][0]), y(v)]).filter(Boolean);
      if (pts.length < 2) return;
      svg.append(mk("path", { d: path(pts), class: `ln ema e${n + 1}` }));
      const l = mk("text", { x: W - padR + 3, y: pts.at(-1)[1] + 3, class: "ema-lbl" }); l.textContent = k; svg.append(l);
    });
    svg.append(mk("path", { d, class: "ln", stroke: color }));
    if (newsTs >= t0 && newsTs <= t1) {
      const mx = x(newsTs).toFixed(1);
      svg.append(mk("line", { x1: mx, x2: mx, y1: 9, y2: H, class: "mk" }));
      const l = mk("text", { x: Math.min(Math.max(+mx, 16), W - padR - 16), y: 7, class: "mk-lbl", "text-anchor": "middle" }); l.textContent = "haber"; svg.append(l);
    }
    return (vals.at(-1) / vals[0] - 1) * 100;
  }
  const tvSymbol = (sym, m) => (state.feed.watchlist || []).find(w => w.symbol === sym)?.tv || (m === "BIST" ? `BIST:${sym}` : sym);
  function extLinks(sym, m, p) {
    const links = [["TradingView", `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(tvSymbol(sym, m))}`],
      ["Investing", `https://tr.investing.com/search/?q=${encodeURIComponent(sym)}`], ["Yahoo", `https://finance.yahoo.com/quote/${encodeURIComponent(p?.yahoo || sym)}/`]];
    if (m === "US") links.push(["Barchart", `https://www.barchart.com/stocks/quotes/${encodeURIComponent(sym)}`], ["Earnings Hub", "https://earningshub.com/"]);
    links.push(["Godel", "https://app.godelterminal.com/"]);
    if (m === "BIST") links.push(["MarketVisuals", "https://marketvisuals.net/"]);
    return `<div class="ext-links">${links.map(([n, u]) => `<a href="${u}" target="_blank" rel="noopener">${n} ↗</a>`).join("")}</div>`;
  }
  function tvWidget(box, sym, m) {
    box.dataset.tv = JSON.stringify([sym, m]);
    box.innerHTML = `<div class="tradingview-widget-container"><div class="tradingview-widget-container__widget"></div></div>`;
    const sc = document.createElement("script");
    sc.src = "https://s3.tradingview.com/external-embedding/embed-widget-technical-analysis.js";
    sc.async = true;
    sc.textContent = JSON.stringify({ interval: "1D", width: "100%", height: 400, isTransparent: true, symbol: tvSymbol(sym, m),
      showIntervalTabs: true, displayMode: "single", locale: "tr", colorTheme: sh.isDark() ? "dark" : "light" });
    box.firstElementChild.append(sc);
  }
  addEventListener("themechange", () => $$("[data-tv]").forEach(b => tvWidget(b, ...JSON.parse(b.dataset.tv))));

  const VIEW_K = { "güçlü al": 1, "al": 1, "nötr": 0, "sat": -1, "güçlü sat": -1 };
  function taHTML(ta, p) {
    if (!ta) return "";
    const em = ta.ema || {};
    const emaRows = EMA_KEYS.filter(k => em[k]).map((k, n) => {
      const e = em[k];
      return `<tr><td><i class="ln-sw e${n + 1}"></i>EMA${k}</td><td class="num">${fmt.num(e.v)}</td>
        <td class="num ${dirCls(e.dist, 0.05)}">${e.dist == null ? "—" : glyph(Math.abs(e.dist) < 0.05 ? 0 : e.dist) + " " + fmt.pct(e.dist)}</td><td>${e.above == null ? "" : e.above ? "▲ üstünde" : "▼ altında"}</td></tr>`;
    }).join("");
    const tile = (l, v, t = "") => `<div data-tip="${esc(t)}"><small>${l}</small><b>${v}</b></div>`;
    const vk = VIEW_K[ta.view] ?? 0, ne = p?.next_earnings;
    return `
      <div class="ta-head"><span>Teknik görünüm</span>
        <span class="tag ${dirCls(vk)}" data-tip="Günlük/haftalık trend, EMA dizilimi, MACD ve RSI'dan kaba skor (${ta.score > 0 ? "+" : ""}${ta.score})">${glyph(vk)} ${esc((ta.view || "nötr").toLocaleUpperCase("tr"))}</span>
        <span class="tag" data-tip="Fiyat ve EMA14/34/55/200 sıralaması">dizilim: ${esc(ta.ema_align || "—")}</span></div>
      ${emaRows ? `<table class="ema-tbl"><thead><tr><th>Ortalama</th><th class="num">Değer</th><th class="num">Fiyata uzaklık</th><th></th></tr></thead><tbody>${emaRows}</tbody></table>` : ""}
      <div class="ta-grid">
        ${tile("Günlük trend", esc(ta.trend), "Fiyat, EMA55 ve EMA200 sıralaması")}
        ${tile("Haftalık trend", esc(ta.weekly_trend || "—"), "Haftalık kapanış, 10 ve 30 haftalık EMA")}
        ${tile("RSI 14", ta.rsi == null ? "—" : fmt.num(ta.rsi, 0))}
        ${tile("MACD hist.", ta.macd_hist == null ? "—" : fmt.num(ta.macd_hist, 2), "MACD − sinyal (12,26,9)")}
        ${tile("Oynaklık", ta.atr_pct == null ? "—" : fmt.pct(ta.atr_pct, 1, false), "Günlük ortalama hareket (ATR14 benzeri)")}
        ${tile("Bollinger %B", ta.bb_pct == null ? "—" : fmt.num(ta.bb_pct, 0), "0 = alt bant, 100 = üst bant (20, 2σ)")}
        ${tile("52h konum", ta.pos52 == null ? "—" : fmt.pct(ta.pos52, 0, false), `52 hafta: ${fmt.num(ta.lo52)} – ${fmt.num(ta.hi52)}`)}
        ${tile("Hacim / ort.", ta.vol_ratio ? fmt.num(ta.vol_ratio, 1) + "×" : "—", "Son tamamlanmış gün / 20 gün ortalaması")}
      </div>
      ${ta.signals?.length ? `<ul class="ta-sig">${ta.signals.map(s => `<li>${esc(s)}</li>`).join("")}</ul>` : ""}
      ${ne ? `<p class="ne">Sonraki bilanço: <b>${fmt.date(ne.date + "T12:00:00Z", { day: "numeric", month: "long", year: "numeric" })}</b>${ne.eps_est != null ? ` · EPS beklentisi ${fmt.num(ne.eps_est)}` : ""}</p>` : ""}
      <p class="ta-note">20 gün aralığı: ${fmt.num(ta.lo20)} – ${fmt.num(ta.hi20)} · EMA'lar 5 yıllık günlük kapanıştan TradingView yöntemiyle hesaplanır.</p>`;
  }
  function pricePanel(it) {
    const box = document.createElement("div");
    const sym = relTickers(it).find(t => state.prices[t]);
    if (!sym || it.source_type === "macro") {
      const ser = state.macro?.series || [];
      box.innerHTML = `<div class="px-head"><span class="px-sym">Makro göstergeler</span></div>` + (ser.length
        ? `<div class="macro-mini">${ser.map(s => `<div><span>${esc(s.name)}</span><b>${fmt.num(s.last)}${s.unit || ""} ${s.change == null ? "" : `<span class="${dirCls(s.change)}">${glyph(s.change)} ${fmt.num(s.change)}</span>`}</b></div>`).join("")}</div><p class="card-foot">TCMB EVDS · ${esc(ser[0].date)}</p>`
        : stateHTML({ kind: "info", title: "Fiyat verisi yok", msg: "Bu kayıt izleme listesindeki bir hisseye bağlı değil.", compact: true }));
      return box;
    }
    const p = state.prices[sym], m = p.market || it.market;
    const newsTs = Math.floor(new Date(it.published) / 1000);
    box.innerHTML = `
      <div class="px-head"><span class="px-sym">${esc(sym)} · ${esc(p.currency || "")}</span>
        <div class="px-rng" role="group" aria-label="Grafik aralığı">${["1G", "1H", "1A", "3A", "6A"].map(r => `<button type="button" data-r="${r}" aria-pressed="false" ${["1A", "3A", "6A"].includes(r) ? `data-tip="Günlük · EMA 14/34/55/200 ile"` : ""}>${r}</button>`).join("")}</div></div>
      <div class="px-row"><span class="px-last"></span><span class="rx chg"></span></div>
      <svg class="spark" viewBox="0 0 300 80" preserveAspectRatio="none" role="img" aria-label="${esc(sym)} fiyat grafiği, haber anı işaretli"></svg>
      <p class="ema-legend" hidden>${EMA_KEYS.map((k, n) => `<span><i class="ln-sw e${n + 1}"></i>EMA${k}</span>`).join("")}<span><i class="ln-sw"></i>Fiyat</span></p>
      <div class="react-slot"></div><div class="ta-slot"></div>
      <div class="tv-slot"><button type="button" class="btn">TradingView teknik özetini göster</button></div>
      ${extLinks(sym, m, p)}`;
    const paint = range => {
      $$(".px-rng button", box).forEach(b => b.setAttribute("aria-pressed", String(b.dataset.r === range)));
      const ser = seriesFor(p, range), svg = $(".spark", box);
      svg.classList.toggle("tall", !!ser.ema);
      const chg = drawSpark(svg, ser, newsTs);
      $(".ema-legend", box).hidden = !ser.ema;
      $(".px-last", box).textContent = fmt.money(p.last, p.currency);
      const shown = range === "1G" ? p.change_pct : chg, k = shown == null || Math.abs(shown) < 0.05 ? 0 : shown;
      const c = $(".chg", box); c.textContent = shown == null ? "—" : `${glyph(k)} ${fmt.pct(shown, 2)}`; c.className = "rx chg " + dirCls(k);
    };
    $$(".px-rng button", box).forEach(b => b.onclick = () => paint(b.dataset.r));
    const age = Date.now() / 1000 - newsTs;
    paint(age < 20 * 3600 ? "1G" : age < 6 * 86400 ? "1H" : age < 30 * 86400 ? "1A" : "3A");
    const r = it.reaction;
    if (r && r.n_after === 0) $(".react-slot", box).innerHTML = `<p class="react">Haberden sonra henüz işlem olmadı (seans kapalı)</p>`;
    else if (r && r.since != null) {
      const b = v => `<b class="${dirCls(v, 0.05)}">${glyph(Math.abs(v) < 0.05 ? 0 : v)} ${fmt.pct(v)}</b>`;
      const parts = [`${b(r.since)} haberden beri`];
      if (r.vol_x) parts.push(`<b>${fmt.num(r.vol_x, 1)}×</b> hacim`);
      if (r.index_since != null) parts.push(`endeks ${b(r.index_since)}`);
      if (r.excess != null) parts.push(`fark ${b(r.excess)}`);
      $(".react-slot", box).innerHTML = `<p class="react" data-tip="Haber anındaki fiyattan bu yana; hacim = haber günü / 20 gün ortalaması; fark = hisse − endeks">${parts.join(" · ")}</p>`;
    }
    $(".ta-slot", box).innerHTML = taHTML(p.ta, p);
    $(".tv-slot .btn", box).onclick = () => tvWidget($(".tv-slot", box), sym, m);
    return box;
  }
  const stateHTML = sh.stateHTML;

  // ─────────────────────────────── sağ şerit: AI özeti
  function renderDigest() {
    const el = $("#digest"), d = state.digest, ai = state.feed.ai || {};
    const headHTML = (h, mood) => `<div class="card-head"><h2 class="card-title">${h}</h2>${mood ? `<span class="mood ${esc(mood)}">${esc(mood)}</span>` : ""}</div>`;
    if (!d || d.empty || !d.headline) {
      el.innerHTML = headHTML("Dönem özeti") + stateHTML({ kind: "info", compact: true,
        title: !ai.enabled ? "AI kapalı" : d?.empty ? "Özetlenecek sinyal yok" : "Özet henüz hazır değil",
        msg: !ai.enabled ? "Özet için bir AI anahtarı (Claude ya da Gemini) gerekiyor." : d?.empty ? "Son 24 saatte değerlendirilmiş sinyal yok." : "Bir sonraki taramada (15 dakikada bir) oluşturulacak." });
      return;
    }
    const mk = watchMarket;
    const ideas = (d.ideas || []).map((i, k) => [i, k]).filter(([i]) => market() === "ALL" || !mk(i.ticker) || mk(i.ticker) === market());
    const hidden = (d.ideas || []).length - ideas.length;
    el.innerHTML = headHTML(`Son ${d.window_hours} saatin özeti`, d.mood) + `
      <p class="dg-head">${esc(d.headline)}</p>
      <p class="dg-sum" data-tip="${esc(d.summary)}">${esc(d.summary)}</p>
      ${market() !== "ALL" ? `<p class="dg-note">Özet metni tüm piyasaları kapsar${hidden ? `; ${hidden} fikir ${market() === "BIST" ? "ABD" : "BIST"} hissesi olduğu için gizlendi` : ""}.</p>` : ""}
      <details class="dg-more" ${matchMedia("(min-width: 768px)").matches || state.idsLabel ? "open" : ""}><summary class="link-btn">${ideas.length} fikir${d.conflicts?.length ? ` ve ${d.conflicts.length} çelişki` : ""} göster</summary>
      ${ideas.map(([i, k]) => { const s = i.stance === "AL" ? 1 : i.stance === "SAT" ? -1 : 0; return `
        <button type="button" class="idea" data-k="${k}" aria-pressed="${state.idsLabel === "idea" + k}"
          data-tip="${esc(`<b>${esc(i.title)}</b><br>${esc(i.rationale)}${i.risk ? `<hr>Risk: ${esc(i.risk)}` : ""}<hr><i>Tıkla: dayandığı sinyalleri tabloda göster</i>`)}">
          <span class="idea-top"><span class="stance ${esc(i.stance)}">${glyph(s)} ${esc(i.stance)}</span><span class="idea-tk">${esc(i.ticker)}</span><span class="idea-title">${esc(i.title)}</span><span class="idea-conv">%${i.conviction}</span></span>
          <span class="sr-only">${esc(i.rationale)}${i.risk ? ` Risk: ${esc(i.risk)}` : ""}</span>
        </button>`; }).join("")}
      ${d.conflicts?.length ? `<details class="dg-cx"><summary class="link-btn">≠ ${d.conflicts.length} çelişki</summary><ul class="dg-conf">${d.conflicts.map(c => `<li>${esc(c)}</li>`).join("")}</ul></details>` : ""}</details>
      <p class="card-foot">${d.count} sinyalden · ${esc(d.provider || "")} · ${fmt.dt(d.generated)} · İzleme notudur, yatırım tavsiyesi değildir.</p>`;
    $$(".idea", el).forEach(b => b.onclick = () => {
      const k = "idea" + b.dataset.k, i = d.ideas[+b.dataset.k];
      if (state.idsLabel === k) { clearFocus(); return; }
      if (i.item_ids?.length) { state.ids = new Set(i.item_ids); state.ticker = null; } else { state.ids = null; state.ticker = i.ticker; }
      state.idsLabel = k; state.focusText = `${i.stance} ${i.ticker}: ${i.title}`; state.limit = PAGE;
      render();
    });
  }
  function clearFocus() { state.ids = null; state.idsLabel = ""; state.focusText = ""; state.ticker = null; state.limit = PAGE; render(); }

  // ─────────────────────────────── sağ şerit: ısı haritası
  function newsNet(sym, hours = 24) {
    let s = 0, w = 0, n = 0;
    for (const it of state.feed.items) {
      const a = it.analysis;
      if (!a || ageMin(it.published) > hours * 60 || !relTickers(it).includes(sym)) continue;
      const k = MAT_W[a.materiality]; s += sign(a.sentiment) * a.confidence / 100 * k; w += k; n++;
    }
    return { net: w ? s / w : 0, n };
  }
  // Kutu zemini renk karışımından hesaplanır; yazı rengi gerçek kontrasta göre seçilir
  const hex = h => { h = h.replace("#", ""); return [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16)); };
  const lum = c => { const [r, g, b] = c.map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
  const contrast = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
  function renderHeatmap() {
    const box = $("#heatmap");
    const up = hex(sh.cssVar("--hm-up")), dn = hex(sh.cssVar("--hm-down")), mid = hex(sh.cssVar("--hm-mid"));
    const ink = hex(sh.cssVar("--text")), white = [255, 255, 255], dark = [20, 26, 25];
    const all = (state.feed.watchlist || []).filter(w => market() === "ALL" || w.market === market());
    if (!all.length) { box.innerHTML = stateHTML({ kind: "empty", compact: true, title: "Bu piyasada izlenen hisse yok" }); return; }
    // Liste iki satıra sığmıyorsa: seçili hisse, ters sinyaller, en çok hareket edenler ve haberi olanlar öne; kalanı "+N hisse"
    const fit = matchMedia("(max-width: 767px)").matches ? 99 : Math.max(4, Math.floor((box.clientWidth + 4) / 82));
    const cap = fit * 2;
    let list = all, hiddenN = 0;
    if (all.length > cap && !state.stripAll) {
      const score = w => {
        const chg = state.prices[w.symbol]?.change_pct, { net, n } = newsNet(w.symbol);
        const nk = !n ? null : net > 0.15 ? 1 : net < -0.15 ? -1 : 0;
        const dis = chg != null && ((nk === 1 && chg <= -0.5) || (nk === -1 && chg >= 0.5));
        return (state.ticker === w.symbol ? 1e6 : 0) + (dis ? 1e4 : 0) + Math.abs(chg || 0) * 100 + (n ? 50 + Math.log1p(n) * 10 : 0);
      };
      const keep = new Set(all.map(w => [w, score(w)]).sort((a, b) => b[1] - a[1]).slice(0, cap - 1).map(([w]) => w.symbol));
      list = all.filter(w => keep.has(w.symbol)); hiddenN = all.length - list.length;
    }
    box.innerHTML = "";
    for (const w of list) {
      const p = state.prices[w.symbol], chg = p?.change_pct;
      const { net, n } = newsNet(w.symbol);
      const nk = !n ? null : net > 0.15 ? 1 : net < -0.15 ? -1 : 0;
      const dis = chg != null && ((nk === 1 && chg <= -0.5) || (nk === -1 && chg >= 0.5));
      const b = document.createElement("button");
      b.type = "button";
      b.className = "hm" + (dis ? " dis" : "") + (state.ticker === w.symbol ? " on" : "");
      let bg = mid;
      if (chg != null && Math.abs(chg) >= 0.1) {
        const t = 0.35 + Math.min(Math.abs(chg) / 3, 1) * 0.65;        // ±%3 ve üstü tam doygun
        const c = chg > 0 ? up : dn;
        bg = c.map((v, i) => Math.round(v * t + mid[i] * (1 - t)));
      }
      const fg = bg === mid ? ink : contrast(white, bg) >= 4.5 ? white : contrast(dark, bg) >= contrast(white, bg) ? dark : white;
      b.style.background = `rgb(${bg.join(",")})`; b.style.color = `rgb(${fg.join(",")})`;
      const k = chg == null || Math.abs(chg) < 0.05 ? 0 : chg;
      b.innerHTML = `<b>${esc(w.symbol)}</b><span class="v">${chg == null ? "N/A" : `${glyph(k)} ${fmt.pct(chg, 2)}`}</span>${nk != null ? `<span class="nw" aria-hidden="true">${glyph(nk)}${n}</span>` : ""}`;
      b.setAttribute("aria-pressed", String(state.ticker === w.symbol));
      b.setAttribute("aria-label", `${w.symbol} bugün ${chg == null ? "fiyat yok" : fmt.pct(chg, 2)}, son 24 saatte ${n} haber${nk != null ? `, net ${nk > 0 ? "olumlu" : nk < 0 ? "olumsuz" : "nötr"}` : ""}${dis ? ", haber ile fiyat ters" : ""}`);
      b.dataset.tip = `<b>${esc(w.symbol)}</b> · ${esc(w.name)}<br>Bugün: ${chg == null ? "fiyat yok" : glyph(k) + " " + fmt.pct(chg, 2)}<br>Son 24 sa: ${n} sinyal${n ? `, net ${nk > 0 ? "▲ olumlu" : nk < 0 ? "▼ olumsuz" : "● nötr"}` : ""}` +
        (dis ? `<br><b>≠ Haber yönü ile fiyat ters</b>` : "") + (p?.ta ? `<br>Teknik: ${esc(p.ta.trend)}, RSI ${p.ta.rsi == null ? "—" : fmt.num(p.ta.rsi, 0)}` : "") + "<br><i>Tıkla: tabloyu bu hisseye süz</i>";
      b.onclick = () => { state.ticker = state.ticker === w.symbol ? null : w.symbol; state.ids = null; state.idsLabel = ""; state.focusText = ""; state.limit = PAGE; render(); };
      box.append(b);
    }
    if (hiddenN || (state.stripAll && all.length > cap)) {
      const m = document.createElement("button");
      m.type = "button"; m.className = "hm more";
      m.innerHTML = hiddenN ? `<b>+${hiddenN}</b><span class="v">hisse daha</span>` : `<b>Daralt</b><span class="v">öne çıkanlar</span>`;
      m.dataset.tip = hiddenN ? "Şeritte öne çıkanlar gösteriliyor (ters sinyal, en çok hareket eden, haberi olan). Tümünü göster." : "Yalnız öne çıkanları göster";
      m.setAttribute("aria-expanded", String(!hiddenN));
      m.onclick = () => { state.stripAll = !state.stripAll; renderHeatmap(); };
      box.append(m);
    }
    layoutStrip();
  }
  function layoutStrip() {
    const box = $("#heatmap"), n = box.children.length;
    if (!n || matchMedia("(max-width: 767px)").matches) { box.style.gridTemplateColumns = ""; return; }
    const fit = Math.max(1, Math.floor((box.clientWidth + 4) / 82));          // kutu en az ~78px
    const rows = Math.ceil(n / Math.min(n, fit));
    box.style.gridTemplateColumns = `repeat(${Math.ceil(n / rows)}, minmax(0, 1fr))`;
  }

  // ─────────────────────────────── sağ şerit: Sinyal Haritası (haber yönü × fiyat)
  // Yatay: son 24 saatin net haber yönü (−1 … +1) · Dikey: bugünkü fiyat değişimi (%) · boyut: haber sayısı.
  // Sağ alt ve sol üst "ters" bölgeler: haber yönü ile fiyat ters (ısı haritasındaki ≠ ile aynı eşik).
  function scatterData() {
    return (state.feed.watchlist || []).filter(w => market() === "ALL" || w.market === market()).map(w => {
      const p = state.prices[w.symbol], chg = p?.change_pct, { net, n } = newsNet(w.symbol);
      if (chg == null || !n) return null;
      const nk = net > 0.15 ? 1 : net < -0.15 ? -1 : 0;
      const items = state.feed.items.filter(it => it.analysis && ageMin(it.published) <= 1440 && relTickers(it).includes(w.symbol));
      return { t: w.symbol, name: w.name, chg, net, n, nk, mis: (nk === 1 && chg <= -0.5) || (nk === -1 && chg >= 0.5), items };
    }).filter(Boolean);
  }
  function renderBubbles() {
    const svg = $("#bubbles");
    const W = Math.max(280, Math.round(svg.getBoundingClientRect().width) || 320), H = 280;
    const L = 44, R = 12, T = 12, B = 34, pw = W - L - R, ph = H - T - B;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.innerHTML = "";
    const mk = (tag, attrs, parent = svg) => { const e = document.createElementNS(NS, tag); Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, v)); parent.append(e); return e; };
    const txt = (t, attrs, parent) => { const e = mk("text", attrs, parent); e.textContent = t; return e; };
    let nodes = scatterData();
    // Çok hisse varsa: en çok haber alan 24 hisse + tüm ters sinyaller gösterilir
    let capped = 0;
    if (nodes.length > 24) {
      const keep = new Set(nodes.slice().sort((a, b) => b.n - a.n).slice(0, 24).map(n => n.t));
      const kept = nodes.filter(n => keep.has(n.t) || n.mis || n.t === state.ticker);
      capped = nodes.length - kept.length; nodes = kept;
    }
    // 12'den fazla balonda etiket yalnız ters sinyallere, en çok haber alan 6 hisseye ve seçili hisseye yazılır
    const labelSet = nodes.length <= 12 ? null : new Set([...nodes.filter(n => n.mis).map(n => n.t),
      ...nodes.slice().sort((a, b) => b.n - a.n).slice(0, 6).map(n => n.t), state.ticker].filter(Boolean));
    const others = (state.feed.watchlist || []).filter(w => market() === "ALL" || w.market === market()).length - nodes.length;
    const yMax = [1, 2, 3, 5, 8, 10, 15, 20, 30, 50].find(v => v >= Math.max(1, ...nodes.map(n => Math.abs(n.chg))) * 1.1) || 50;
    const cx = v => L + (v + 1) / 2 * pw, cy = v => T + ph / 2 - v / yMax * ph / 2;
    // ters bölgeler (taralı zemin)
    mk("rect", { x: cx(0), y: cy(0), width: pw / 2, height: ph / 2, class: "sc-zone" });
    mk("rect", { x: L, y: T, width: pw / 2, height: ph / 2, class: "sc-zone" });
    txt("≠ haber +, fiyat −", { x: W - R - 4, y: T + ph - 6, "text-anchor": "end", class: "zone-lbl" });
    txt("≠ haber −, fiyat +", { x: L + 4, y: T + 12, class: "zone-lbl" });
    // ızgara ve eksenler
    [-yMax, -yMax / 2, 0, yMax / 2, yMax].forEach(v => {
      mk("line", { x1: L, x2: W - R, y1: cy(v), y2: cy(v), class: v ? "grid" : "axis" });
      txt(v ? fmt.pct(v, v % 1 ? 1 : 0) : "%0", { x: L - 6, y: cy(v) + 3.5, class: "tick", "text-anchor": "end" });
    });
    mk("line", { x1: cx(0), x2: cx(0), y1: T, y2: T + ph, class: "axis" });
    [[-1, "▼ olumsuz", "start"], [0, "● nötr", "middle"], [1, "olumlu ▲", "end"]].forEach(([v, t, a]) => txt(t, { x: cx(v), y: T + ph + 14, class: "tick", "text-anchor": a }));
    txt("Net haber yönü (24 sa)", { x: L + pw / 2, y: H - 3, class: "axis-title", "text-anchor": "middle" });
    txt("Bugün fiyat", { x: 0, y: 0, class: "axis-title", "text-anchor": "middle", transform: `translate(10 ${T + ph / 2}) rotate(-90)` });
    $("#scNote").textContent = "";
    if (!nodes.length) {
      txt("Son 24 saatte haberi olan izlenen hisse yok", { x: L + pw / 2, y: T + 24, "text-anchor": "middle", class: "tick" });
      return;
    }
    // konum + hafif çarpışma çözümü (balonlar gerçek konumlarından en fazla birkaç piksel kayar)
    const maxN = Math.max(...nodes.map(n => n.n));
    nodes.forEach(n => { n.r = 6 + 9 * Math.sqrt(n.n / maxN); n.x = n.tx = cx(Math.max(-1, Math.min(1, n.net))); n.y = n.ty = cy(n.chg); });
    for (let it = 0; it < 120; it++) {
      for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j];
        let dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy); const min = a.r + b.r + 2;
        if (d >= min) continue;
        if (d < 0.01) { dx = j % 2 ? 1 : -1; dy = 0.5; d = Math.hypot(dx, dy); }
        const p = (min - d) / 2; a.x -= dx / d * p; a.y -= dy / d * p; b.x += dx / d * p; b.y += dy / d * p;
      }
      nodes.forEach(n => { n.x += (n.tx - n.x) * 0.1; n.y += (n.ty - n.y) * 0.1;
        n.x = Math.max(L + n.r, Math.min(W - R - n.r, n.x)); n.y = Math.max(T + n.r, Math.min(T + ph - n.r, n.y)); });
    }
    // etiketler: sağ, sol, üst, alt adaylarından diğer etiketlere ve balonlara çarpmayan ilki seçilir
    const CW = 6.3, placed = [];
    const hitsCircle = (x, y, w, h) => nodes.some(o => { const nx = Math.max(x, Math.min(o.x, x + w)), ny = Math.max(y, Math.min(o.y, y + h)); return Math.hypot(o.x - nx, o.y - ny) < o.r; });
    const hitsLabel = (x, y, w, h) => placed.some(([px, py, pw2, ph2]) => x < px + pw2 && px < x + w && y < py + ph2 && py < y + h);
    nodes.slice().sort((a, b) => b.r - a.r).forEach(n => {
      if (labelSet && !labelSet.has(n.t)) { n.nolbl = true; return; }
      const w = n.t.length * CW, h = 11;
      const cands = [[n.x + n.r + 3, n.y - 5, "start"], [n.x - n.r - 3 - w, n.y - 5, "end"], [n.x - w / 2, n.y - n.r - 13, "middle"], [n.x - w / 2, n.y + n.r + 2, "middle"],
        [n.x + n.r + 3, n.y - 16, "start"], [n.x + n.r + 3, n.y + 6, "start"], [n.x - n.r - 3 - w, n.y - 16, "end"], [n.x - n.r - 3 - w, n.y + 6, "end"]];
      const inside = ([x, y]) => x >= L && x + w <= W - R && y >= T && y + h <= T + ph + 2;
      const best = cands.find(c => inside(c) && !hitsLabel(c[0], c[1], w, h) && !hitsCircle(c[0], c[1], w, h)) || cands.find(c => inside(c) && !hitsLabel(c[0], c[1], w, h)) || cands[0];
      n.la = best[2]; n.lx = best[2] === "start" ? best[0] : best[2] === "end" ? best[0] + w : best[0] + w / 2; n.ly = best[1] + 9;
      placed.push([best[0], best[1], w, h]);
    });
    for (const n of nodes) {
      const g = mk("g", { class: "node" + (state.ticker === n.t ? " on" : "") + (n.mis ? " mis" : ""), tabindex: 0, role: "button",
        "aria-label": `${n.t}: bugün ${fmt.pct(n.chg, 2)}, son 24 saatte ${n.n} haber, net ${n.nk > 0 ? "olumlu" : n.nk < 0 ? "olumsuz" : "nötr"}${n.mis ? ", haber ile fiyat ters" : ""}` });
      mk("circle", { cx: n.x, cy: n.y, r: n.r, class: "b" }, g);
      if (n.mis) txt("≠", { x: n.x, y: n.y + 3.5, "text-anchor": "middle", class: "mis-g" }, g);
      if (!n.nolbl) txt(n.t, { x: n.lx, y: n.ly, "text-anchor": n.la, class: "lbl" }, g);
      const k = Math.abs(n.chg) < 0.05 ? 0 : n.chg;
      const heads = n.items.slice().sort((a, b) => impact(b) - impact(a)).slice(0, 4).map(it =>
        `<li>${glyph(sign(it.analysis.sentiment))} ${esc(it.analysis.event_label || "")} ${esc((it.analysis.what || it.analysis.headline_tr || it.title).slice(0, 80))}</li>`).join("");
      g.dataset.tip = `<b>${esc(n.t)}</b> · ${esc(n.name)}<br>Bugün: ${glyph(k)} ${fmt.pct(n.chg, 2)}<br>Son 24 sa: ${n.n} haber, net ${glyph(n.nk)} ${n.nk > 0 ? "olumlu" : n.nk < 0 ? "olumsuz" : "nötr"} (${fmt.num(n.net, 2)})` +
        (n.mis ? `<br><b>≠ Haber yönü ile fiyat ters</b>` : "") + `<ul>${heads}</ul><i>Tıkla: tabloyu bu hisseye süz</i>`;
      const ids = n.items.map(i => i.id);
      const pick = () => { state.ticker = state.ticker === n.t ? null : n.t; state.ids = null; state.idsLabel = ""; state.focusText = ""; state.limit = PAGE; render(); };
      g.addEventListener("click", pick);
      g.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
      g.addEventListener("mouseenter", () => highlight(ids)); g.addEventListener("mouseleave", () => highlight([]));
      g.addEventListener("focus", () => highlight(ids)); g.addEventListener("blur", () => highlight([]));
    }
    $("#scNote").textContent = [others > 0 ? `${others} hissede son 24 saatte haber yok` : "", capped ? `${capped} az haberli hisse gizlendi` : "",
      labelSet ? "etiketsiz balonlar: üzerine gel" : ""].filter(Boolean).join(" · ");
  }
  function highlight(ids) { const s = new Set(ids); $$("#sigBody tr.row").forEach(r => r.classList.toggle("hl", s.has(r.dataset.id))); }

  // ─────────────────────────────── araç çubuğu, açıklama, afiş
  function counts() {
    const items = state.feed.items.filter(inMarket);
    $("#cntFeed").textContent = fmt.int(items.length);
    $("#cntSig").textContent = fmt.int(items.filter(i => isSignal(i.analysis)).length);
    $("#cntSaved").textContent = fmt.int(items.filter(i => state.saved.has(i.id)).length);
    $("#cntTk").textContent = fmt.int(new Set(items.flatMap(relTickers)).size);
    const ms = $("#mSort"), v = `${state.sort.k}:${state.sort.d}`;
    if ([...ms.options].some(o => o.value === v)) ms.value = v;
  }
  const CK = `<svg class="ck" viewBox="0 0 12 12" aria-hidden="true"><path d="M2.5 6.2l2.3 2.3 4.7-5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
  function chips() {
    const box = $("#typeChips");
    const items = state.feed.items.filter(inMarket);
    const n = t => items.filter(i => i.source_type === t).length;
    box.innerHTML = Object.entries(TYPE).filter(([k]) => n(k) || state.types.has(k)).map(([k, l]) =>
      `<button type="button" class="chip" data-type="${k}" aria-pressed="${state.types.has(k)}">${CK}${l} <span class="n">${fmt.int(n(k))}</span></button>`).join("");
    $$(".chip", box).forEach(b => b.onclick = () => {
      const t = b.dataset.type; state.types.has(t) ? state.types.delete(t) : state.types.add(t);
      state.limit = PAGE; render(); $(`#typeChips .chip[data-type="${t}"]`)?.focus();
    });
    const act = activeFilters(), c = $("#clearAll");
    c.disabled = !act; c.textContent = act ? `Temizle (${act})` : "Temizle";
    c.dataset.tip = act ? "Tüm filtreleri, aramayı ve hisse odağını temizle" : "";
    $("#hideNoise").setAttribute("aria-pressed", String(state.hideNoise));
  }
  function clearAll() {
    state.types.clear(); state.col = {}; state.q = ""; $("#q").value = "";
    state.ticker = null; state.ids = null; state.idsLabel = ""; state.focusText = ""; state.limit = PAGE;
    render(); $("#q").focus();
  }
  function legend() {
    const L = (t, rows) => `<div><h3>${t}</h3><dl>${rows.map(([a, b]) => `<dt>${a}</dt><dd>${b}</dd>`).join("")}</dl></div>`;
    $("#legend").innerHTML = [
      L("Yön (AI)", [[`<span class="dir up">▲</span>`, "Yükseliş beklentisi"], [`<span class="dir down">▼</span>`, "Düşüş beklentisi"], [`<span class="dir flat">●</span>`, "Nötr"], [`<span class="tag na">N/A</span>`, "AI değerlendirmesi yok"]]),
      L("Hisse ve önem", [[`<span class="tk"><span class="tk-sym">NVDA</span><span class="tk-more">+1</span></span>`, "+N: haberde başka hisseler de geçiyor (üzerine gel)"],
        [`<span class="meter" data-l="1"><i></i><i></i><i></i></span>`, "Düşük önem"], [`<span class="meter" data-l="2"><i></i><i></i><i></i></span>`, "Orta önem"], [`<span class="meter" data-l="3"><i></i><i></i><i></i></span>`, "Yüksek önem"]]),
      L("Tepki (haberden bu yana fiyat)", [[`<span class="rx up">▲ +%1,2</span>`, "Yükseldi"], [`<span class="rx down">▼ −%0,8</span>`, "Düştü"], [`<span class="rx-wait">…</span>`, "Haberden sonra işlem yok (seans kapalı)"],
        [`<span class="mis">≠</span>`, "Haber yönü ile fiyat ters (±%0,5 üstü)"], [`<span class="tag na">N/A</span>`, "Fiyat verisi yok"]]),
      L("Soluk satırlar", [[DIM_IC("tekrar").replace("dim-ic", "dim-ic lg"), "Soluk satır simgesi. Üzerine gelince nedeni yazar:"], ...Object.entries(DIM_TIP).map(([k, v]) => [`<span class="tag">${k}</span>`, v]),
        [`<span class="chip" aria-pressed="true" style="height:22px;padding:0 8px">Solukları gizle</span>`, "Varsayılan olarak açık; kapatınca soluk satırlar da listelenir"]]),
      L("Kaynak ve diğer", [[`<span class="src-cell"><span class="t1">Bildirim</span></span>`, "Resmi kaynak (KAP, SEC, SPK, TCMB, şirket bülteni)"], [`<span class="src-cell">Haber <span class="x">×3</span></span>`, "Aynı haber 3 kaynakta"],
        [`<span class="new-dot"></span>`, "Son ziyaretinden sonra gelen güçlü sinyal"]]),
    ].join("");
  }
  function banner() {
    const ban = $("#banner"), f = state.feed, sec = f.secrets || {};
    ban.className = "banner";
    if (state.focusText) ban.innerHTML = `<span>Özet fikri: <b>${esc(state.focusText)}</b> · dayandığı sinyaller gösteriliyor</span><button type="button" class="link-btn" id="banClear">Temizle ✕</button>`;
    else if (state.ticker) ban.innerHTML = `<span><b>${esc(state.ticker)}</b> filtresi açık (doğrudan ya da etkilenen olarak geçen kayıtlar)</span><button type="button" class="link-btn" id="banClear">Temizle ✕</button>`;
    else if (f.demo) ban.textContent = "Örnek veri gösteriliyor.";
    else if (Object.keys(sec).length && !(sec.ANTHROPIC_API_KEY || sec.GEMINI_API_KEY)) { ban.classList.add("warn"); ban.textContent = "AI değerlendirmesi kapalı: ne ANTHROPIC_API_KEY ne de Gemini anahtarı tanımlı."; }
    else { ban.hidden = true; return; }
    ban.hidden = false;
    $("#banClear")?.addEventListener("click", clearFocus);
  }

  // ─────────────────────────────── çizim
  // ─────────────────────────────── geniş ekranda yan panel detayı
  const wide = () => matchMedia("(min-width: 1400px)").matches;
  function selectRow(tr, { focus = false } = {}) {
    const it = tr && state.feed.items.find(i => i.id === tr.dataset.id);
    if (!it) return;
    state.sel = it.id;
    $$("#sigBody tr.row.sel").forEach(r => { r.classList.remove("sel"); r.setAttribute("aria-expanded", "false"); });
    tr.classList.add("sel"); tr.setAttribute("aria-expanded", "true");
    const tks = relTickers(it);
    $("#spTitle").textContent = [tks[0], it.analysis?.event_label].filter(Boolean).join(" · ") || "Ayrıntı";
    const body = $("#spBody"); body.innerHTML = ""; body.append(detailContent(it)); body.scrollTop = 0;
    $("#sidePanel").hidden = false;
    if (focus) tr.focus();
  }
  function closePanel(refocus = true) {
    if ($("#sidePanel").hidden) return;
    $("#sidePanel").hidden = true;
    const tr = state.sel && $(`#sigBody tr.row[data-id="${state.sel}"]`);
    $$("#sigBody tr.row.sel").forEach(r => { r.classList.remove("sel"); r.setAttribute("aria-expanded", "false"); });
    state.sel = null;
    if (refocus && tr) tr.focus();
  }

  // ─────────────────────────────── hisse bazında görünüm
  function tickerRows() {
    const m = new Map();
    for (const it of filtered(false)) {
      for (const t of relTickers(it)) {
        const o = m.get(t) || { t, n: 0, s: 0, w: 0, top: null, last: null, items: [] };
        o.n++; o.items.push(it);
        const a = it.analysis;
        if (a) { const k = MAT_W[a.materiality]; o.s += sign(a.sentiment) * a.confidence / 100 * k; o.w += k; }
        if (!o.top || impact(it) > impact(o.top)) o.top = it;
        if (!o.last || it.published > o.last) o.last = it.published;
        m.set(t, o);
      }
    }
    return [...m.values()].map(o => {
      o.net = o.w ? o.s / o.w : null;
      o.nk = o.net == null ? null : o.net > 0.15 ? 1 : o.net < -0.15 ? -1 : 0;
      o.chg = state.prices[o.t]?.change_pct ?? null;
      o.mis = o.chg != null && ((o.nk === 1 && o.chg <= -0.5) || (o.nk === -1 && o.chg >= 0.5));
      o.name = (state.feed.watchlist || []).find(w => w.symbol === o.t)?.name || "";
      return o;
    });
  }
  const TK_COLS = [["t", "Hisse", "k-tk"], ["net", "Net haber yönü", "k-dir"], ["n", "Haber", "k-n num"], ["top", "En önemli olay", "k-top", true], ["chg", "Bugün", "k-px num"], ["last", "Son haber", "k-age num"]];
  function renderTickers() {
    const rows = tickerRows(), k = state.tkSort.k, d = state.tkSort.d;
    rows.sort((a, b) => {
      const va = a[k], vb = b[k];
      if (va == null && vb == null) return b.n - a.n;
      if (va == null) return 1; if (vb == null) return -1;
      return (typeof va === "string" ? va.localeCompare(vb, "tr") : va - vb) * d || b.n - a.n;
    });
    $("#tkHead").innerHTML = `<tr>${TK_COLS.map(([c, l, cls, nosort]) => nosort ? `<th scope="col" class="${cls}">${l}</th>` :
      `<th scope="col" class="${cls}" aria-sort="${c === k ? (d > 0 ? "ascending" : "descending") : "none"}"><button type="button" class="th-sort" data-k="${c}">${l}<span class="arr" aria-hidden="true">${c === k ? (d > 0 ? "▲" : "▼") : "▼"}</span></button></th>`).join("")}</tr>`;
    $$("#tkHead .th-sort").forEach(b => b.onclick = () => {
      const c = b.dataset.k; state.tkSort = state.tkSort.k === c ? { k: c, d: -state.tkSort.d } : { k: c, d: c === "t" ? 1 : -1 };
      renderTickers(); $(`#tkHead .th-sort[data-k="${c}"]`)?.focus();
    });
    $("#tkBody").innerHTML = rows.map(o => {
      const a = o.top?.analysis, ck = o.chg == null || Math.abs(o.chg) < 0.05 ? 0 : o.chg;
      const top = o.top ? (a?.event_label ? `<b>${esc(a.event_label)}</b> · ${esc(a.what || a.headline_tr || o.top.title)}` : esc(a?.headline_tr || o.top.title)) : "—";
      return `<tr class="row" data-t="${esc(o.t)}" tabindex="0" aria-label="${esc(o.t)}: ${o.n} haber; tıkla, akışı bu hisseye süz">
        <td><span class="tk"><span class="tk-sym">${esc(o.t)}</span></span>${o.name ? `<span class="tk-name">${esc(o.name)}</span>` : ""}</td>
        <td>${o.nk == null ? `<span class="tag na" data-tip="Bu hissenin haberlerinde AI değerlendirmesi yok">N/A</span>` : `<span class="dir ${dirCls(o.nk)}" style="display:inline">${glyph(o.nk)}</span><span class="netlbl">${o.nk > 0 ? "olumlu" : o.nk < 0 ? "olumsuz" : "nötr"} · ${fmt.num(o.net, 2)}</span>`}</td>
        <td class="num">${fmt.int(o.n)}</td>
        <td><span class="k-top-t" data-tip="${esc(o.top?.title || "")}">${top}</span></td>
        <td class="num">${o.mis ? `<span class="mis" data-tip="Haber yönü ile fiyat ters">≠</span> ` : ""}${o.chg == null ? `<span class="tag na" data-tip="Fiyat verisi yok (izleme listesi dışı)">N/A</span>` : `<span class="rx ${dirCls(ck)}">${glyph(ck)} ${fmt.pct(o.chg, 2)}</span>`}</td>
        <td class="num"><span class="age" data-tip="${esc(fmt.full(o.last))}">${fmt.ago(o.last)}</span></td></tr>`;
    }).join("");
    $("#sigCount").textContent = rows.length ? `${fmt.int(rows.length)} hisse · satıra tıkla: akışı o hisseye süz` : "";
    $("#sigState").innerHTML = rows.length ? "" : stateHTML({ kind: "empty", title: "Bu filtrelerle hisse yok", msg: "Filtreleri gevşet ya da temizle." });
  }
  function pickTicker(t) {
    state.ticker = t; state.ids = null; state.idsLabel = ""; state.focusText = ""; state.view = "feed"; state.limit = PAGE;
    $$("#viewSeg button").forEach(x => x.setAttribute("aria-checked", String(x.dataset.view === "feed")));
    render();
    $(".sig-table").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // Zaman sıralamasında gün / saat ayraçları: Son 1 saat · Bugün · Dün · tarih
  function timeGroup(iso) {
    if (ageMin(iso) < 60) return "Son 1 saat";
    const k = fmt.dayKey(iso), today = fmt.dayKey(Date.now()), yest = fmt.dayKey(Date.now() - 86400e3);
    return k === today ? "Bugün" : k === yest ? "Dün" : fmt.date(iso, { day: "numeric", month: "long", weekday: "long" });
  }
  function withSeparators(shown, all) {
    if (state.sort.k !== "time") return shown.map(rowHTML).join("");
    const counts = new Map();
    all.forEach(it => { const g = timeGroup(it.published); counts.set(g, (counts.get(g) || 0) + 1); });
    let prev = null, html = "";
    for (const it of shown) {
      const g = timeGroup(it.published);
      if (g !== prev) { html += `<tr class="sep"><th colspan="7" scope="colgroup">${esc(g)} <span>${fmt.int(counts.get(g))} kayıt</span></th></tr>`; prev = g; }
      html += rowHTML(it);
    }
    return html;
  }

  function renderTable() {
    const tkMode = state.view === "tickers";
    $(".sig-scroll").hidden = tkMode; $("#tkWrap").hidden = !tkMode;
    if (tkMode) { $("#moreBtn").hidden = true; closePanel(false); renderTickers(); return; }
    const body = $("#sigBody"), st = $("#sigState");
    const items = filtered(), shown = items.slice(0, state.limit);
    body.innerHTML = withSeparators(shown, items);
    $$("tr.row", body).forEach(tr => {
      if (state.sel === tr.dataset.id && wide()) { tr.classList.add("sel"); tr.setAttribute("aria-expanded", "true"); return; }
      const it = !wide() && state.open.has(tr.dataset.id) && state.feed.items.find(i => i.id === tr.dataset.id);
      if (it) tr.after(drawer(it));
    });
    const total = state.feed.items.filter(inMarket).length;
    $("#sigCount").textContent = items.length ? `${fmt.int(shown.length)} / ${fmt.int(items.length)} kayıt gösteriliyor${items.length < total ? ` · toplam ${fmt.int(total)}` : ""}` : "";
    $("#moreBtn").hidden = shown.length >= items.length;
    $("#moreBtn").textContent = `${Math.min(PAGE, items.length - shown.length)} kayıt daha göster`;
    $("#moreBtn").dataset.tip = `Kalan ${fmt.int(items.length - shown.length)} kayıt`;
    if (items.length) { st.innerHTML = ""; return; }
    const reason = state.view === "saved" && !state.saved.size ? ["Henüz kaydedilen sinyal yok", "Bir satırı açıp “Kaydedilenlere kaydet” düğmesine bas; kayıtlar bu tarayıcıda saklanır."]
      : state.view === "signals" && !activeFilters() ? ["Bu piyasada güçlü sinyal yok", "Güçlü sinyal: yön belirgin, güven ≥ %70 ve önem orta ya da yüksek."]
      : activeFilters() ? ["Bu filtrelere uyan kayıt yok", `${activeFilters()} filtre açık${state.hideNoise ? " ve soluk satırlar gizli" : ""}. Filtreleri gevşet ya da temizle.`]
      : state.hideNoise ? ["Gösterilecek kayıt yok", "Tüm kayıtlar soluk (düşük önem, eski vb.). “Solukları gizle” seçeneğini kapat."]
      : ["Bu piyasada kayıt yok", "Seçili piyasa için son taramalarda kayıt toplanmadı."];
    st.innerHTML = stateHTML({ kind: "empty", title: reason[0], msg: esc(reason[1]), action: activeFilters() ? "Filtreleri temizle" : null, actionId: "emptyClear" });
    $("#emptyClear")?.addEventListener("click", clearAll);
  }
  function render() {
    if (!state.feed) return;
    counts(); chips(); banner(); head(); renderTable();
    if (sh.route === "sinyal") { renderDigest(); renderHeatmap(); renderBubbles(); sh.syncActions(); }
  }
  function renderLoading() {
    $("#sigBody").innerHTML = sh.skeletonRows(7, 8);
    $("#sigState").innerHTML = "";
    $("#digest").innerHTML = `<div class="skeleton sk-line w40"></div><div class="skeleton sk-line lg w80"></div><div class="skeleton sk-line"></div><div class="skeleton sk-line w80"></div><div class="skeleton sk-block" style="margin-top:12px;height:80px"></div>`;
    $("#heatmap").innerHTML = Array.from({ length: 10 }, () => `<div class="hm skeleton"></div>`).join("");
    $("#bubbles").innerHTML = "";
  }
  function renderError(e) {
    $("#sigBody").innerHTML = "";
    $("#sigState").innerHTML = stateHTML({ kind: "error", title: "Sinyal verisi yüklenemedi", msg: esc(e.message) + ". Bağlantını kontrol et ya da biraz sonra tekrar dene.", action: "Tekrar dene", actionId: "sigRetry" });
    $("#sigRetry").onclick = boot;
    $("#digest").innerHTML = stateHTML({ kind: "error", compact: true, title: "Özet yüklenemedi" });
    $("#heatmap").innerHTML = ""; $("#bubbles").innerHTML = "";
  }

  // ─────────────────────────────── etkileşim
  function bind() {
    head(); legend();
    $$("#viewSeg button").forEach(b => b.onclick = () => {
      state.view = b.dataset.view; state.limit = PAGE;
      $$("#viewSeg button").forEach(x => x.setAttribute("aria-checked", String(x === b)));
      render();
    });
    sh.radioKeys($("#viewSeg"));
    $("#hideNoise").onclick = () => { state.hideNoise = !state.hideNoise; store.set("hideNoise", state.hideNoise); state.limit = PAGE; render(); };
    $("#clearAll").onclick = clearAll;
    // Simge açıklamaları: tablonun üzerinde açılan pencere (içerik kaymaz)
    const lb = $("#legendBtn"), lg = $("#legend");
    const setLegend = open => { lg.hidden = !open; lb.setAttribute("aria-expanded", String(open)); };
    lb.onclick = e => { e.stopPropagation(); setLegend(lg.hidden); };
    document.addEventListener("click", e => { if (!lg.hidden && !e.target.closest(".pop-wrap")) setLegend(false); });
    document.addEventListener("keydown", e => { if (e.key === "Escape" && !lg.hidden) { setLegend(false); lb.focus(); } });
    let t; $("#q").oninput = e => { clearTimeout(t); t = setTimeout(() => { state.q = e.target.value.trim(); state.limit = PAGE; render(); }, 150); };
    $("#newPill").onclick = () => {
      if (!state.pending) return;
      const prevTop = state.feed.generated;
      apply(state.pending); state.seenBefore = state.seenBefore || prevTop; state.limit = PAGE; render();
      $(".sig-table").scrollIntoView({ behavior: "smooth", block: "start" });
      $("#sigBody tr.row")?.focus({ preventScroll: true });
    };
    addEventListener("marketchange", () => { if (state.pending) showPill(); });
    $("#moreBtn").onclick = () => {
      const n = $$("#sigBody tr.row").length;
      state.limit += PAGE; renderTable();
      $$("#sigBody tr.row")[n]?.focus({ preventScroll: true });        // klavye kullanıcısı yeni gelen ilk satırda kalsın
    };

    // Satırlar: tıkla / Enter / Boşluk ile aç-kapa; ↑ ↓ ile satırlar arasında gezin
    const toggle = tr => {
      if (wide()) { state.sel === tr.dataset.id && !$("#sidePanel").hidden ? closePanel() : selectRow(tr); return; }
      const id = tr.dataset.id, it = state.feed.items.find(i => i.id === id);
      const open = !state.open.has(id);
      open ? state.open.add(id) : state.open.delete(id);
      tr.classList.toggle("open", open); tr.setAttribute("aria-expanded", String(open));
      const next = tr.nextElementSibling;
      if (open) tr.after(drawer(it)); else if (next?.classList.contains("drawer")) next.remove();
    };
    $("#sigBody").addEventListener("click", e => {
      const tr = e.target.closest("tr.row");
      if (tr && !e.target.closest("a, button, select")) toggle(tr);
    });
    $("#sigBody").addEventListener("keydown", e => {
      const tr = e.target.closest("tr.row");
      if (!tr || e.target !== tr) return;
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(tr); }
      else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const rows = $$("#sigBody tr.row"), i = rows.indexOf(tr), next = rows[i + (e.key === "ArrowDown" ? 1 : -1)];
        if (!next) return;
        next.focus();
        if (wide() && !$("#sidePanel").hidden) selectRow(next);      // panel açıksa içerik satırla birlikte değişir
      }
    });
    $("#spClose").onclick = () => closePanel();
    document.addEventListener("keydown", e => { if (e.key === "Escape" && !$("#sidePanel").hidden && $("#legend").hidden) closePanel(); });
    addEventListener("resize", () => { if (!wide()) closePanel(false); });
    // hisse görünümü: satır → akışı o hisseye süz
    $("#tkBody").addEventListener("click", e => { const tr = e.target.closest("tr.row"); if (tr) pickTicker(tr.dataset.t); });
    $("#tkBody").addEventListener("keydown", e => {
      const tr = e.target.closest("tr.row");
      if (!tr || e.target !== tr) return;
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pickTicker(tr.dataset.t); }
      else if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); const r = $$("#tkBody tr.row"), i = r.indexOf(tr); r[i + (e.key === "ArrowDown" ? 1 : -1)]?.focus(); }
    });
    $("#mSort").onchange = e => { const [k, d] = e.target.value.split(":"); state.sort = { k, d: +d }; state.limit = PAGE; render(); };
    let rt; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => { if (sh.route === "sinyal" && state.feed) { layoutStrip(); renderBubbles(); } }, 150); });
    addEventListener("themechange", () => { if (sh.route === "sinyal" && state.feed) { renderHeatmap(); renderBubbles(); } });
    addEventListener("marketchange", () => { state.ticker = null; state.ids = null; state.idsLabel = ""; state.focusText = ""; state.limit = PAGE; render(); });
  }

  // ─────────────────────────────── dışa aktarma
  function exportRows() {
    return filtered(false).map(it => {
      const a = it.analysis || {}, r = it.reaction || {};
      return {
        id: it.id, yayin_utc: it.published, piyasa: it.market, hisseler: relTickers(it).join(" "),
        kaynak: it.source, kaynak_turu: TYPE[it.source_type] || it.source_type, kaynak_sinifi: it.tier ?? "", olay_turu: EVENT[it.event] || it.event || "",
        olay: a.event_label || "", baslik: it.title, ne_oldu: a.what || a.headline_tr || "", neden_onemli: a.why || "", risk: a.risk || "",
        yon: a.sentiment ? SENT_TR[a.sentiment] : "", guven: a.confidence ?? "", onem: a.materiality ? MAT_TR[a.materiality] : "", ufuk: a.horizon ? HOR[a.horizon] || a.horizon : "",
        tepki_pct: r.n_after === 0 ? "" : r.since ?? "", haberle_ters: mismatch(it) ? "evet" : "", hacim_kat: r.vol_x ?? "", endeks_pct: r.index_since ?? "", endekse_gore_pct: r.excess ?? "",
        tekrar_sayisi: it.dups ? it.dups + 1 : 1, soluk_nedeni: state.reasons.get(it.id) || "", url: it.url,
      };
    });
  }
  function download(name, text, type) {
    const url = URL.createObjectURL(new Blob([text], { type }));
    const a = Object.assign(document.createElement("a"), { href: url, download: name });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const stamp = () => { const d = new Date(), z = n => String(n).padStart(2, "0"); return `${d.getFullYear()}${z(d.getMonth() + 1)}${z(d.getDate())}_${z(d.getHours())}${z(d.getMinutes())}`; };
  // CSV: noktalı virgül ayraç, ondalık nokta (pandas: sep=";"), BOM ile Excel'de Türkçe karakterler doğru açılır
  function toCSV(rows) {
    const cols = Object.keys(rows[0] || { id: "" });
    const cell = v => { const t = String(v ?? ""); return /[";\n\r]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t; };
    return "﻿" + [cols.join(";"), ...rows.map(r => cols.map(c => cell(r[c])).join(";"))].join("\r\n");
  }
  function exportCSV() { download(`sinyal-takip_${market().toLowerCase()}_${stamp()}.csv`, toCSV(exportRows()), "text/csv;charset=utf-8"); }
  function exportJSON() {
    const items = filtered(false);
    const meta = { olusturma: new Date().toISOString(), veri: state.feed.generated, piyasa: market(), gorunum: state.view, arama: state.q, hisse: state.ticker,
      kolon_filtreleri: state.col, kaynak_turleri: [...state.types], soluklar_gizli: state.hideNoise, siralama: state.sort, adet: items.length };
    download(`sinyal-takip_${market().toLowerCase()}_${stamp()}.json`, JSON.stringify({ filtre: meta, kayitlar: items }, null, 2), "application/json");
  }
  window.radarExport = { toCSV, download, stamp };

  // ─────────────────────────────── kabuğa kayıt ve açılış
  sh.register("sinyal", {
    onHide() { closePanel(false); },
    onShow() {
      if (!state.feed) return;
      markSeen(); sh.setBadge("sinyal", 0);
      render();
    },
    async refresh() { try { await load(); render(); } catch (e) { renderError(e); } },
    exports() { const n = state.feed ? filtered().length : 0; return [
      { label: "CSV", hint: "Excel · noktalı virgül", run: exportCSV, disabled: !n },
      { label: "JSON", hint: "tam kayıt + filtreler", run: exportJSON, disabled: !n }]; },
    exportInfo: () => state.feed ? `Filtrelenmiş görünüm: ${fmt.int(filtered().length)} kayıt` : "",
  });
  window.radar = { get state() { return state; }, ready: null, poll: () => poll() };

  async function boot() {
    let done; window.radar.ready = window.radar.ready || new Promise(r => (done = r));
    state.loading = true; renderLoading();
    try { await load(); render(); done?.(); }
    catch (e) { state.loading = false; renderError(e); done?.(); }
  }
  bind();
  boot();
  // Otomatik yenileme (5 dk): Sinyal Takip açıksa tablo yerinden oynamaz; yeni kayıt varsa "N yeni kayıt" hapı çıkar
  function newCount(next) {
    const known = new Set(state.feed.items.map(i => i.id));
    return next.feed.items.filter(i => !known.has(i.id) && inMarket(i)).length;
  }
  function showPill() {
    const n = state.pending ? newCount(state.pending) : 0, b = $("#newPill");
    b.hidden = !n;
    b.textContent = `↑ ${n} yeni kayıt · göster`;
    b.setAttribute("aria-label", `${n} yeni kayıt geldi; tabloyu güncellemek için tıkla`);
  }
  async function poll() {
    try {
      const next = await fetchAll();
      if (next.feed.generated === state.feed?.generated) return;
      if (sh.route === "sinyal" && state.feed && newCount(next) > 0) {
        state.pending = next; showPill();
        sh.setUpdated("sinyal", state.feed.generated, { label: "Son tarama (yeni tarama bekliyor)", staleMin: 45 });
        return;
      }
      apply(next);
      if (sh.route === "sinyal") render();                    // yeni kayıt yok: yalnız fiyat/özet tazelenir
    } catch { /* sonraki turda */ }
  }
  setInterval(poll, 5 * 60 * 1000);
})();
