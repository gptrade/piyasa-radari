/* Piyasa Radarı — statik panel.
   Veri: data/feed.json, data/digest.json, data/macro.json, data/prices/<SYMBOL>.json */
(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const TZ = "Europe/Istanbul";
  const NS = "http://www.w3.org/2000/svg";
  const MAT_W = { low: 1, medium: 2, high: 3 };
  const MAT_TR = { low: "düşük", medium: "orta", high: "yüksek" };
  const HOR = { intraday: "Gün içi", days: "Birkaç gün", weeks: "Haftalar", long_term: "Uzun vade" };
  const SENT_TR = { bullish: "Yükseliş", bearish: "Düşüş", neutral: "Nötr" };
  const EVENT = {   // simge, ad
    measure: ["!", "Borsa tedbiri"], buyback: ["↺", "Geri alım"], insider: ["İ", "İçeriden işlem"],
    earnings: ["Σ", "Finansal sonuç"], analyst: ["A", "Analist"], dividend: ["%", "Temettü / sermaye"],
    deal: ["⇄", "Anlaşma / ihale"], regulator: ["S", "Düzenleyici (SPK)"], macro: ["M", "Makro"],
    legal: ["§", "Hukuki"], news: ["N", "Haber"], social: ["@", "Sosyal medya"], report: ["R", "Rapor"],
  };
  const TIER = { 1: ["①", "Birincil / resmi kaynak"], 2: ["②", "Yerleşik finans medyası"], 3: ["③", "Diğer / sosyal"] };

  const store = {
    get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* özel pencere */ } },
  };
  const state = {
    feed: null, digest: null, macro: null, prices: {},
    market: "ALL", view: "feed", sort: "time", ticker: null, ids: null, idsLabel: "", focusText: "",
    types: new Set(), sents: new Set(), q: "", hideNoise: store.get("hideNoise", false),
    open: new Set(), saved: new Set(store.get("saved", [])),
  };

  // ─────────────────────────────── yardımcılar
  const esc = t => String(t ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmtNum = (v, cur) => v == null ? "—" :
    new Intl.NumberFormat("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v) +
    (cur === "TRY" ? " ₺" : cur === "USD" ? " $" : "");
  const fmtPct = (v, d = 1) => v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(d)}%`;
  const cls = v => v == null ? "" : v > 0 ? "pos" : v < 0 ? "neg" : "";
  const fmtTime = iso => new Date(iso).toLocaleString("tr-TR", { timeZone: TZ, day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  const ageMin = iso => (Date.now() - new Date(iso)) / 60000;
  function ago(iso) {
    const m = Math.round(ageMin(iso));
    if (m < 1) return "şimdi";
    if (m < 60) return `${m}dk`;
    if (m < 1440) return `${Math.round(m / 60)}sa`;
    return `${Math.round(m / 1440)}g`;
  }
  const sign = s => s === "bullish" ? 1 : s === "bearish" ? -1 : 0;
  const watchSet = () => new Set((state.feed.watchlist || []).map(w => w.symbol));
  const relTickers = it => {
    const w = watchSet();
    const own = it.tickers || [];
    const aff = (it.analysis?.affected_tickers || []).filter(t => w.has(t) && !own.includes(t));
    return [...own, ...aff];
  };
  const isSignal = a => a && a.sentiment !== "neutral" && a.confidence >= 70 && a.materiality !== "low";
  const isNoise = it => !it.analysis || it.analysis.materiality === "low"
    || (it.tier === 3 && it.analysis.materiality !== "high") || ageMin(it.published) > 1440;
  const impact = it => {
    const a = it.analysis;
    if (!a) return 0;
    const rec = Math.max(0.2, 1 - ageMin(it.published) / 2880);
    return MAT_W[a.materiality] * a.confidence * (it.tier === 1 ? 1.2 : 1) * rec * (1 + Math.min(it.dups || 0, 10) * 0.05);
  };

  // ─────────────────────────────── veri
  async function getJSON(path) {
    try { const r = await fetch(`${path}?t=${Date.now()}`); return r.ok ? await r.json() : null; } catch { return null; }
  }
  async function load() {
    const feed = await getJSON("data/feed.json");
    if (!feed) throw new Error("feed.json bulunamadı");
    state.feed = feed;
    [state.digest, state.macro] = await Promise.all([getJSON("data/digest.json"), getJSON("data/macro.json")]);
    const all = new Set([...(feed.watchlist || []).map(w => w.symbol), ...feed.items.map(i => i.tickers?.[0]).filter(Boolean)]);
    await Promise.all([...all].map(async s => { const p = await getJSON(`data/prices/${s}.json`); if (p) state.prices[s] = p; }));
  }

  // ─────────────────────────────── filtre
  function filtered() {
    const q = state.q.toLocaleLowerCase("tr");
    let out = state.feed.items.filter(it => {
      if (state.market !== "ALL" && it.market !== state.market) return false;
      if (state.ids && !state.ids.has(it.id)) return false;
      if (state.ticker && !relTickers(it).includes(state.ticker)) return false;
      if (state.view === "saved" && !state.saved.has(it.id)) return false;
      if (state.view === "signals" && !isSignal(it.analysis)) return false;
      if (state.types.size && !state.types.has(it.source_type)) return false;
      if (state.sents.size && !(it.analysis && state.sents.has(it.analysis.sentiment))) return false;
      if (state.hideNoise && isNoise(it) && !state.saved.has(it.id)) return false;
      if (q) {
        const a = it.analysis || {};
        const hay = `${it.title} ${it.summary} ${it.source} ${relTickers(it).join(" ")} ${a.event_label || ""} ${a.what || ""} ${a.summary || ""}`.toLocaleLowerCase("tr");
        if (!hay.includes(q)) return false;
      }
      return true;
    });
    if (state.sort === "impact") out = out.slice().sort((a, b) => impact(b) - impact(a));
    return out;
  }

  // ─────────────────────────────── satır
  function dirHTML(a) {
    if (!a) return `<span class="dir none" title="AI değerlendirmesi yok">·</span>`;
    const n = a.confidence >= 80 ? 3 : a.confidence >= 60 ? 2 : 1;
    if (a.sentiment === "neutral") return `<span class="dir flat" title="Nötr · %${a.confidence} güven">●</span>`;
    const up = a.sentiment === "bullish";
    return `<span class="dir ${up ? "up" : "down"}" title="${SENT_TR[a.sentiment]} · %${a.confidence} güven">${(up ? "▲" : "▼").repeat(n)}</span>`;
  }
  const dotsHTML = a => a ? `<span class="dots" title="Önem: ${MAT_TR[a.materiality]}">${"●".repeat(MAT_W[a.materiality])}${"○".repeat(3 - MAT_W[a.materiality])}</span>` : `<span class="dots"></span>`;

  function rowHTML(it) {
    const a = it.analysis;
    const tks = relTickers(it);
    const tkTxt = tks.length ? tks[0] + (tks.length > 1 ? `+${tks.length - 1}` : "") : (it.market === "BIST" ? "Genel" : "Market");
    const [evG, evN] = EVENT[it.event] || EVENT.news;
    const [tG, tN] = TIER[it.tier] || TIER[3];
    const label = a?.event_label
      ? `<b>${esc(a.event_label)}</b> <span>· ${esc(a.what || a.headline_tr || it.title)}</span>`
      : esc(a?.headline_tr || it.title);
    const noTrade = it.reaction?.n_after === 0;
    const since = noTrade ? null : it.reaction?.since;
    const dups = it.dups ? `<span class="dup" title="Aynı haber: ${esc((it.dup_sources || []).join(", "))}">×${it.dups + 1}</span>` : `<span class="dup"></span>`;
    return `<button class="row-line" aria-expanded="${state.open.has(it.id)}">
      ${dirHTML(a)}
      <span class="tk ${tks.length ? "" : "gen"}" title="${esc(tks.join(", "))}">${esc(tkTxt)}</span>
      <span class="ev ${it.event || "news"}" title="${evN}">${evG}</span>
      <span class="lbl" title="${esc(it.title)}">${label}</span>
      ${dotsHTML(a)}
      <span class="px ${cls(since)}" title="${noTrade ? "Haberden sonra henüz işlem olmadı" : "Haberden bu yana fiyat"}">${since == null ? (noTrade ? "…" : "") : fmtPct(since)}</span>
      <span class="tier t${it.tier || 3}" title="${tN}">${tG}</span>
      ${dups}
      <span class="age" title="${fmtTime(it.published)}">${ago(it.published)}</span>
    </button>`;
  }

  function row(it) {
    const el = document.createElement("article");
    el.className = "row" + (isNoise(it) ? " dim" : "") + (state.open.has(it.id) ? " open" : "");
    el.dataset.id = it.id;
    el.innerHTML = rowHTML(it);
    $(".row-line", el).onclick = () => {
      state.open.has(it.id) ? state.open.delete(it.id) : state.open.add(it.id);
      const open = state.open.has(it.id);
      el.classList.toggle("open", open);
      $(".row-line", el).setAttribute("aria-expanded", open);
      const d = $(".detail", el);
      if (open && !d) el.append(detail(it)); else if (!open && d) d.remove();
    };
    if (state.open.has(it.id)) el.append(detail(it));
    return el;
  }

  // ─────────────────────────────── açılan detay
  function detail(it) {
    const a = it.analysis;
    const el = document.createElement("div");
    el.className = "detail";
    const firstSentence = s => (s || "").split(/(?<=[.!?])\s/)[0];
    const what = a?.what || a?.headline_tr || it.title;
    const why = a?.why || firstSentence(a?.summary);
    const risk = a?.risk || a?.risks?.[0];
    const dupNote = it.dups ? ` · ${it.dups + 1} kaynakta: ${esc((it.dup_sources || []).join(", "))}` : "";
    const tks = relTickers(it);
    const left = document.createElement("div");
    left.innerHTML = `
      <h2 class="d-title">${it.url ? `<a href="${esc(it.url)}" target="_blank" rel="noopener">${esc(it.title)}</a>` : esc(it.title)}</h2>
      <p class="d-src">${esc(it.source)}${it.extra?.form ? " · " + esc(it.extra.form) : ""} · ${fmtTime(it.published)} · ${TIER[it.tier || 3][1]}${dupNote}</p>
      ${a ? `<dl class="slots">
        <dt>Ne oldu</dt><dd>${esc(what)}</dd>
        <dt>Neden önemli</dt><dd>${esc(why || "—")}</dd>
        <dt>Risk</dt><dd class="risk">${esc(risk || "—")}</dd>
      </dl>
      ${a.summary ? `<p class="d-sum">${esc(a.summary)}</p>` : ""}` :
      `<p class="d-sum">${esc(it.summary || "")}</p><p class="d-sum">${tks.some(t => watchSet().has(t)) ? "Bu kayıt için AI değerlendirmesi yok (tur sınırı ya da sağlayıcı hatası)." : "İzleme listesi dışında; sadece listelendi."}</p>`}
      <div class="d-foot">
        ${a ? `<span class="pill ${a.sentiment}">${SENT_TR[a.sentiment]} · %${a.confidence}</span><span>${MAT_TR[a.materiality]} önem</span><span>${HOR[a.horizon] || ""}</span><span>${esc(a.provider || "")}</span>` : ""}
        <span class="act">
          ${tks[0] ? `<button data-a="tk">${esc(tks[0])} filtrele</button>` : ""}
          <button data-a="save">${state.saved.has(it.id) ? "Kaydedildi ✓" : "Kaydet"}</button>
        </span>
      </div>`;
    $$(".act button", left).forEach(b => b.onclick = e => {
      e.stopPropagation();
      if (b.dataset.a === "tk") { state.ticker = tks[0]; state.ids = null; state.idsLabel = ""; state.focusText = ""; render(); }
      else {
        state.saved.has(it.id) ? state.saved.delete(it.id) : state.saved.add(it.id);
        store.set("saved", [...state.saved]);
        b.textContent = state.saved.has(it.id) ? "Kaydedildi ✓" : "Kaydet";
        counts();
      }
    });
    el.append(left, pricePanel(it));
    return el;
  }

  function seriesFor(p, range) {
    if (!p) return [];
    const now = (p.intraday?.at(-1) || p.daily?.at(-1) || [0])[0];
    if (range === "1A") return (p.daily || []).filter(b => b[0] >= now - 31 * 86400);
    if (range === "3A") return (p.daily || []).filter(b => b[0] >= now - 93 * 86400);
    if (range === "1H") return (p.intraday || []).filter(b => b[0] >= now - 7 * 86400);
    const bars = p.intraday || [];
    if (!bars.length) return (p.daily || []).slice(-2);
    const day = t => new Date(t * 1000).toLocaleDateString("tr-TR", { timeZone: TZ });
    const last = day(bars.at(-1)[0]);
    return bars.filter(b => day(b[0]) === last);
  }

  function drawSpark(svg, bars, newsTs) {
    svg.innerHTML = "";
    if (bars.length < 2) return null;
    const W = 300, H = 76, pad = 5;
    const t0 = bars[0][0], t1 = bars.at(-1)[0];
    const vals = bars.map(b => b[1]);
    const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
    const x = t => ((t - t0) / (t1 - t0 || 1)) * W;
    const y = v => H - pad - ((v - lo) / span) * (H - pad * 2);
    const color = vals.at(-1) >= vals[0] ? "var(--up)" : "var(--down)";
    const d = bars.map((b, i) => `${i ? "L" : "M"}${x(b[0]).toFixed(1)},${y(b[1]).toFixed(1)}`).join("");
    const mk = (tag, attrs) => { const e = document.createElementNS(NS, tag); Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, v)); return e; };
    svg.append(mk("path", { d: `${d}L${W},${H}L0,${H}Z`, class: "ar", fill: color }), mk("path", { d, class: "ln", stroke: color }));
    if (newsTs >= t0 && newsTs <= t1) {
      const mx = x(newsTs).toFixed(1);
      svg.append(mk("line", { x1: mx, x2: mx, y1: 9, y2: H, class: "mk" }));
      const lbl = mk("text", { x: Math.min(Math.max(+mx, 16), W - 16), y: 7, class: "mk-lbl", "text-anchor": "middle" });
      lbl.textContent = "haber";
      svg.append(lbl);
    }
    return (vals.at(-1) / vals[0] - 1) * 100;
  }

  function pricePanel(it) {
    const box = document.createElement("div");
    const sym = relTickers(it).find(t => state.prices[t]);
    if (!sym || it.source_type === "macro") {
      const ser = state.macro?.series || [];
      box.innerHTML = `<div class="px-head"><span class="px-sym">Makro göstergeler</span></div>` + (ser.length
        ? `<div class="macro-mini">${ser.map(s => `<div><span>${esc(s.name)}</span><b>${fmtNum(s.last)}${s.unit || ""} <span class="${cls(s.change)}">${s.change == null ? "" : (s.change > 0 ? "+" : "") + s.change.toFixed(2)}</span></b></div>`).join("")}</div><p class="d-src">EVDS · ${esc(ser[0].date)}</p>`
        : `<p class="px-none">Bu kayıt için fiyat verisi yok.</p>`);
      return box;
    }
    const p = state.prices[sym];
    const newsTs = Math.floor(new Date(it.published) / 1000);
    box.innerHTML = `
      <div class="px-head"><span class="px-sym">${esc(sym)} <small>/ ${esc(p.currency || "")}</small></span>
        <div class="px-rng">${["1G", "1H", "1A", "3A"].map(r => `<button data-r="${r}">${r}</button>`).join("")}</div></div>
      <div class="px-row"><span class="px-last"></span><span class="px chg"></span></div>
      <svg class="spark" viewBox="0 0 300 76" preserveAspectRatio="none" role="img" aria-label="${esc(sym)} fiyat grafiği, haber anı işaretli"></svg>
      <div class="react-slot"></div><div class="ta-slot"></div>`;
    const paint = range => {
      $$(".px-rng button", box).forEach(b => b.classList.toggle("on", b.dataset.r === range));
      const chg = drawSpark($(".spark", box), seriesFor(p, range), newsTs);
      $(".px-last", box).textContent = fmtNum(p.last, p.currency);
      const shown = range === "1G" ? p.change_pct : chg;
      const c = $(".chg", box); c.textContent = fmtPct(shown, 2); c.className = "px chg " + cls(shown);
    };
    $$(".px-rng button", box).forEach(b => b.onclick = e => { e.stopPropagation(); paint(b.dataset.r); });
    // Haber anı grafikte görünsün: haberi kapsayan en kısa aralıkla aç
    const age = Date.now() / 1000 - newsTs;
    paint(age < 20 * 3600 ? "1G" : age < 6 * 86400 ? "1H" : age < 30 * 86400 ? "1A" : "3A");

    const r = it.reaction;
    if (r && r.n_after === 0) {
      $(".react-slot", box).innerHTML = `<span class="chip">Haberden sonra henüz işlem olmadı (seans kapalı)</span>`;
    } else if (r && r.since != null) {
      const parts = [`<b class="${cls(r.since)}">${fmtPct(r.since)}</b> haberden beri`];
      if (r.vol_x) parts.push(`<b>${r.vol_x}×</b> hacim`);
      if (r.index_since != null) parts.push(`endeks <b class="${cls(r.index_since)}">${fmtPct(r.index_since)}</b>`);
      if (r.excess != null) parts.push(`fark <b class="${cls(r.excess)}">${fmtPct(r.excess)}</b>`);
      $(".react-slot", box).innerHTML = `<span class="chip" title="Haber anındaki fiyattan bu yana; hacim = haber günü / 20 gün ortalaması; fark = hisse − endeks">${parts.join(" · ")}</span>`;
    }
    const ta = p.ta;
    if (ta) {
      $(".ta-slot", box).innerHTML = `
        <div class="ta">
          <div><small>Trend</small><b>${esc(ta.trend)}</b></div>
          <div><small>RSI 14</small><b>${ta.rsi ?? "—"}</b></div>
          <div><small>52h konum</small><b>${ta.pos52 == null ? "—" : "%" + ta.pos52}</b></div>
          <div><small>Hacim/ort.</small><b>${ta.vol_ratio ? ta.vol_ratio + "×" : "—"}</b></div>
        </div>
        ${ta.signals?.length ? `<ul class="ta-sig">${ta.signals.map(s => `<li>${esc(s)}</li>`).join("")}</ul>` : ""}`;
    }
    return box;
  }

  // ─────────────────────────────── sağ kolon: özet
  function renderDigest() {
    const el = $("#digest");
    const d = state.digest;
    const ai = state.feed.ai || {};
    if (!d || d.empty || !d.headline) {
      el.innerHTML = `<div class="dg-top"><h3>Son saatlerin özeti</h3></div>
        <p class="dg-sum">${!ai.enabled ? "AI kapalı: özet için bir AI anahtarı gerekiyor." : d?.empty ? "Son 24 saatte değerlendirilmiş sinyal yok." : "Özet henüz oluşturulmadı; bir sonraki turda gelecek."}</p>`;
      return;
    }
    const ideas = (d.ideas || []).map((i, k) => `
      <button class="idea ${state.idsLabel === "idea" + k ? "on" : ""}" data-k="${k}" title="Bu fikrin dayandığı sinyalleri göster">
        <div class="idea-top"><span class="stance ${esc(i.stance)}">${esc(i.stance)}</span><span class="idea-tk">${esc(i.ticker)}</span>
          <span>${esc(i.title)}</span><span class="idea-conv">%${i.conviction}</span></div>
        <p>${esc(i.rationale)}</p>
        ${i.risk ? `<p class="risk">⚠ ${esc(i.risk)}</p>` : ""}
      </button>`).join("");
    el.innerHTML = `
      <div class="dg-top"><h3>Son ${d.window_hours} saatin özeti</h3><span class="mood ${esc(d.mood)}">${esc(d.mood)}</span></div>
      <p class="dg-head">${esc(d.headline)}</p>
      <p class="dg-sum">${esc(d.summary)}</p>
      ${ideas}
      ${d.conflicts?.length ? `<ul class="dg-conf">${d.conflicts.map(c => `<li>${esc(c)}</li>`).join("")}</ul>` : ""}
      <p class="dg-meta">${d.count} sinyalden · ${esc(d.provider || "")} · ${fmtTime(d.generated)} · izleme notudur, yatırım tavsiyesi değildir</p>`;
    $$(".idea", el).forEach(b => b.onclick = () => {
      const k = "idea" + b.dataset.k;
      const i = d.ideas[+b.dataset.k];
      if (state.idsLabel === k) { clearFocus(); return; }
      if (i.item_ids?.length) { state.ids = new Set(i.item_ids); state.ticker = null; }
      else { state.ids = null; state.ticker = i.ticker; }
      state.idsLabel = k;
      state.focusText = `${i.stance} ${i.ticker}: ${i.title}`;
      render();
    });
  }
  function clearFocus() { state.ids = null; state.idsLabel = ""; state.focusText = ""; state.ticker = null; render(); }

  // ─────────────────────────────── sağ kolon: ısı haritası
  function newsNet(sym, hours = 24) {
    let s = 0, w = 0, n = 0;
    for (const it of state.feed.items) {
      const a = it.analysis;
      if (!a || ageMin(it.published) > hours * 60 || !relTickers(it).includes(sym)) continue;
      const k = MAT_W[a.materiality];
      s += sign(a.sentiment) * a.confidence / 100 * k; w += k; n++;
    }
    return { net: w ? s / w : 0, n };
  }
  function renderHeatmap() {
    const box = $("#heatmap");
    box.innerHTML = "";
    for (const w of state.feed.watchlist || []) {
      if (state.market !== "ALL" && w.market !== state.market) continue;
      const p = state.prices[w.symbol];
      const chg = p?.change_pct;
      const { net, n } = newsNet(w.symbol);
      const arrow = !n ? "" : net > 0.15 ? "▲" : net < -0.15 ? "▼" : "●";
      const dis = chg != null && ((arrow === "▲" && chg <= -0.5) || (arrow === "▼" && chg >= 0.5));
      const b = document.createElement("button");
      b.className = "hm" + (dis ? " dis" : "") + (state.ticker === w.symbol ? " on" : "");
      if (chg != null && Math.abs(chg) >= 0.1) {
        const pct = Math.round(8 + Math.min(Math.abs(chg) / 4, 1) * 32);   // en fazla %40 karışım: metin okunur kalsın
        b.style.background = `color-mix(in srgb, var(${chg > 0 ? "--up" : "--down"}) ${pct}%, var(--mid))`;
      }
      b.innerHTML = `<b>${esc(w.symbol)}</b><span>${fmtPct(chg, 2)}</span>${arrow ? `<i>${arrow}</i>` : ""}`;
      b.setAttribute("aria-label", `${w.symbol} bugün ${fmtPct(chg, 2)}, ${n} haber sinyali${dis ? ", haber ile fiyat ters" : ""}`);
      b.dataset.tip = `<b>${esc(w.symbol)}</b> · ${esc(w.name)}<br>Bugün: ${fmtPct(chg, 2)}<br>Son 24 sa: ${n} sinyal${n ? `, net ${net > 0.15 ? "olumlu ▲" : net < -0.15 ? "olumsuz ▼" : "nötr ●"}` : ""}` +
        (dis ? `<br><b>≠ Haber yönü ile fiyat ters</b>` : "") + (p?.ta ? `<br>Teknik: ${esc(p.ta.trend)}, RSI ${p.ta.rsi ?? "—"}` : "");
      b.onclick = () => { state.ticker = state.ticker === w.symbol ? null : w.symbol; state.ids = null; state.idsLabel = ""; state.focusText = ""; render(); };
      box.append(b);
    }
  }

  // ─────────────────────────────── sağ kolon: sinyal haritası (balonlar)
  function bubbleData() {
    const w = watchSet(), m = new Map(), edges = new Map();
    for (const it of state.feed.items) {
      const a = it.analysis;
      if (!a || ageMin(it.published) > 1440) continue;
      if (state.market !== "ALL" && it.market !== state.market) continue;
      const tks = relTickers(it).filter(t => w.has(t) || (it.tickers || []).includes(t));
      tks.forEach(t => {
        const o = m.get(t) || { t, s: 0, w: 0, n: 0, imp: 0, items: [] };
        const k = MAT_W[a.materiality];
        o.s += sign(a.sentiment) * a.confidence / 100 * k; o.w += k; o.n++; o.imp = Math.max(o.imp, k); o.items.push(it);
        m.set(t, o);
      });
      for (let i = 0; i < tks.length; i++) for (let j = i + 1; j < tks.length; j++) {
        const key = [tks[i], tks[j]].sort().join("|");
        edges.set(key, (edges.get(key) || 0) + 1);
      }
    }
    const nodes = [...m.values()].map(o => {
      o.net = o.w ? o.s / o.w : 0;
      o.stance = o.net >= 0.2 ? "AL" : o.net <= -0.2 ? "SAT" : "İZLE";
      return o;
    }).sort((a, b) => b.n - a.n).slice(0, 18);
    return { nodes, edges };
  }

  function renderBubbles() {
    const svg = $("#bubbles");
    const W = Math.max(280, Math.round(svg.getBoundingClientRect().width) || 340), H = 260, pad = 26;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.innerHTML = "";
    const { nodes, edges } = bubbleData();
    const mk = (tag, attrs, parent = svg) => { const e = document.createElementNS(NS, tag); Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, v)); parent.append(e); return e; };
    const cx = v => pad + (v + 1) / 2 * (W - 2 * pad);
    mk("line", { x1: cx(0), x2: cx(0), y1: 6, y2: H - 18, class: "axis" });
    [["◀ SAT", 4, "start"], ["İZLE", cx(0), "middle"], ["AL ▶", W - 4, "end"]].forEach(([t, x, a]) => {
      const e = mk("text", { x, y: H - 4, class: "axis-lbl", "text-anchor": a }); e.textContent = t;
    });
    if (!nodes.length) {
      const e = mk("text", { x: W / 2, y: H / 2, "text-anchor": "middle", class: "axis-lbl" }); e.textContent = "Son 24 saatte değerlendirilmiş sinyal yok";
      return;
    }
    const maxN = Math.max(...nodes.map(n => n.n));
    const midY = (H - 20) / 2;
    nodes.forEach((n, i) => {
      n.r = 12 + 18 * Math.sqrt(n.n / maxN);
      n.x = cx(Math.max(-1, Math.min(1, n.net)));
      n.y = midY + (i % 2 ? 1 : -1) * Math.ceil(i / 2) * 6;
    });
    for (let k = 0; k < 240; k++) {          // basit çarpışma çözümü; yatay konum (yön) büyük ölçüde korunur
      for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j];
        const dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy) || 0.01, min = a.r + b.r + 3;
        if (d < min) {
          const push = (min - d) / 2, ux = dx / d, uy = dy / d || (i % 2 ? 1 : -1);
          a.x -= ux * push * 0.25; b.x += ux * push * 0.25; a.y -= uy * push; b.y += uy * push;
        }
      }
      nodes.forEach(n => {
        n.y += (midY - n.y) * 0.01;
        n.y = Math.max(n.r + 4, Math.min(H - 22 - n.r, n.y));
        n.x = Math.max(n.r + 2, Math.min(W - n.r - 2, n.x));
      });
    }
    const byT = new Map(nodes.map(n => [n.t, n]));
    for (const [key, c] of edges) {
      const [a, b] = key.split("|").map(t => byT.get(t));
      if (a && b) mk("line", { x1: a.x, y1: a.y, x2: b.x, y2: b.y, class: "edge", "stroke-width": Math.min(1 + c, 4) });
    }
    for (const n of nodes) {
      const g = mk("g", { tabindex: 0, role: "button", "aria-label": `${n.t} ${n.stance}, ${n.n} sinyal` });
      if (state.ticker === n.t) g.classList.add("on");
      mk("circle", { cx: n.x, cy: n.y, r: n.r, class: `b i${n.imp}` }, g);
      const arrow = n.stance === "AL" ? "▲ " : n.stance === "SAT" ? "▼ " : "";
      const big = n.r >= 18;
      const t1 = mk("text", { x: n.x, y: big ? n.y - 1 : n.y + 3.5, "text-anchor": "middle", class: `bl on-i${n.imp}` }, g);
      t1.textContent = big ? n.t : n.t.slice(0, 5);
      if (big) { const t2 = mk("text", { x: n.x, y: n.y + 10, "text-anchor": "middle", class: `bl2 on-i${n.imp}` }, g); t2.textContent = arrow + n.stance; }
      const heads = n.items.slice().sort((a, b) => impact(b) - impact(a)).slice(0, 5).map(it => {
        const s = it.analysis.sentiment;
        return `<li><span class="${s === "bullish" ? "u" : s === "bearish" ? "d" : ""}">${s === "bullish" ? "▲" : s === "bearish" ? "▼" : "●"}</span> ${esc(it.analysis.event_label || "")} ${esc((it.analysis.what || it.analysis.headline_tr || it.title).slice(0, 90))}</li>`;
      }).join("");
      g.dataset.tip = `<b>${arrow}${esc(n.t)} ${n.stance}</b> · ${n.n} sinyal · en yüksek önem: ${["", "düşük", "orta", "yüksek"][n.imp]}<ul>${heads}</ul>`;
      g.dataset.ids = n.items.map(i => i.id).join(",");
      const pick = () => { state.ticker = state.ticker === n.t ? null : n.t; state.ids = null; state.idsLabel = ""; state.focusText = ""; render(); };
      g.addEventListener("click", pick);
      g.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
      g.addEventListener("mouseenter", () => highlight(g.dataset.ids.split(",")));
      g.addEventListener("mouseleave", () => highlight([]));
    }
  }
  function highlight(ids) {
    const s = new Set(ids);
    $$("#list .row").forEach(r => r.classList.toggle("hl", s.has(r.dataset.id)));
  }

  // ─────────────────────────────── ipucu (tooltip)
  const tip = $("#tip");
  document.addEventListener("mouseover", e => {
    const t = e.target.closest?.("[data-tip]");
    if (!t) { tip.hidden = true; return; }
    tip.innerHTML = t.dataset.tip; tip.hidden = false;
  });
  document.addEventListener("mousemove", e => {
    if (tip.hidden) return;
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = Math.max(8, Math.min(e.clientX + 14, innerWidth - w - 8)) + "px";
    tip.style.top = (e.clientY + 16 + h > innerHeight ? e.clientY - h - 12 : e.clientY + 16) + "px";
  });

  // ─────────────────────────────── kenar çubuğu, sayaçlar
  function counts() {
    const items = state.feed.items.filter(i => state.market === "ALL" || i.market === state.market);
    $("#cntFeed").textContent = items.length;
    $("#cntSig").textContent = items.filter(i => isSignal(i.analysis)).length;
    $("#cntSaved").textContent = items.filter(i => state.saved.has(i.id)).length;
  }
  function sidebar() {
    const f = state.feed;
    const ser = state.macro?.series || [];
    $("#macroBox").hidden = !ser.length;
    $("#macroList").innerHTML = ser.map(s => `<div title="${esc(s.date)}"><span>${esc(s.name)}</span><b>${fmtNum(s.last)}${s.unit || ""}</b></div>`).join("");
    $("#sources").innerHTML = (f.sources || []).map(s => {
      const warn = (s.warnings || []).length;
      const k = !s.ok ? "bad" : warn && !s.count ? "warn" : s.count ? "" : "idle";
      const tipTxt = s.error || (s.warnings || []).join("\n");
      return `<div class="${k}" title="${esc(tipTxt)}"><span>${esc(s.name)}</span><span>${s.ok ? s.count : "hata"}${warn ? " ⚠" : ""}</span></div>`;
    }).join("");
    const by = Object.entries(f.ai?.by_provider || {}).map(([k, v]) => `${k} ${v}`).join(", ");
    $("#gen").textContent = `Son güncelleme: ${fmtTime(f.generated)} · AI: ${f.ai?.enabled ? (f.ai.providers || []).join(" → ") + (by ? ` (${by})` : "") : "kapalı"}`;
    const sec = f.secrets || {};
    const hasAI = sec.ANTHROPIC_API_KEY || sec.GEMINI_API_KEY;
    const missing = Object.entries(sec).filter(([k, v]) => !v && k !== "X_BEARER_TOKEN" && !((k === "ANTHROPIC_API_KEY" || k === "GEMINI_API_KEY") && hasAI)).map(([k]) => k);
    const msgs = [missing.length ? `Tanımlı olmayan secret: ${missing.join(", ")}` : "", (f.ai?.errors || [])[0] ? `AI: ${f.ai.errors[0]}` : ""].filter(Boolean);
    $("#cfgWarn").textContent = msgs.join(" · ");
    $("#cfgWarn").hidden = !msgs.length;

    const ban = $("#banner");
    if (state.focusText) {
      ban.hidden = false;
      ban.innerHTML = `Özet fikri: <b>${esc(state.focusText)}</b> — dayandığı sinyaller gösteriliyor. <button class="clear">Temizle ✕</button>`;
    } else if (state.ticker) {
      ban.hidden = false;
      ban.innerHTML = `<b>${esc(state.ticker)}</b> filtresi açık (doğrudan ya da etkilenen olarak geçen kayıtlar). <button class="clear">Temizle ✕</button>`;
    } else if (f.demo) {
      ban.hidden = false; ban.textContent = "Örnek veri gösteriliyor.";
    } else if (Object.keys(sec).length && !hasAI) {
      ban.hidden = false; ban.textContent = "AI değerlendirmesi kapalı: ne ANTHROPIC_API_KEY ne de Gemini anahtarı bulunamadı.";
    } else ban.hidden = true;
    const c = $(".clear", ban); if (c) c.onclick = clearFocus;
  }

  function render() {
    sidebar(); counts(); renderDigest(); renderHeatmap(); renderBubbles();
    const list = $("#list"); list.innerHTML = "";
    const items = filtered();
    const frag = document.createDocumentFragment();
    items.slice(0, 250).forEach(it => frag.append(row(it)));
    list.append(frag);
    $("#empty").hidden = items.length > 0;
  }

  // ─────────────────────────────── etkileşim
  function bind() {
    const seg = (sel, key, attr) => $$(sel + " button").forEach(b => b.onclick = () => {
      state[key] = b.dataset[attr];
      if (key === "market") { state.ticker = null; state.ids = null; state.idsLabel = ""; state.focusText = ""; }
      $$(sel + " button").forEach(x => x.classList.toggle("on", x === b)); render();
    });
    seg("#marketSeg", "market", "market");
    seg("#views", "view", "view");
    seg("#sortSeg", "sort", "sort");
    const toggle = (sel, key, set) => $$(sel).forEach(b => b.onclick = () => {
      const v = b.dataset[key]; set.has(v) ? set.delete(v) : set.add(v); b.classList.toggle("on"); render();
    });
    toggle("#typeChips button", "type", state.types);
    toggle("#sentChips button", "sent", state.sents);
    const hn = $("#hideNoise"); hn.checked = state.hideNoise;
    hn.onchange = () => { state.hideNoise = hn.checked; store.set("hideNoise", hn.checked); render(); };
    let t; $("#q").oninput = e => { clearTimeout(t); t = setTimeout(() => { state.q = e.target.value.trim(); render(); }, 150); };
    let rt; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(renderBubbles, 200); });
  }

  // Diğer modüller (geri alım sekmesi) için salt okunur erişim
  window.radar = { get state() { return state; }, fmtNum, fmtPct, fmtTime, esc, cls, ready: null };

  async function boot() {
    bind();
    let done; window.radar.ready = new Promise(r => (done = r));
    try { await load(); render(); done(); }
    catch (e) { $("#list").innerHTML = `<p class="empty">Veri yüklenemedi: ${esc(e.message)}</p>`; }
    setInterval(async () => { try { await load(); render(); } catch { /* sonraki turda */ } }, 5 * 60 * 1000);
  }
  boot();
})();
