/* Piyasa Radarı — statik panel. Veri: data/feed.json + data/prices/<SYMBOL>.json */
(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const TZ = "Europe/Istanbul";
  const SENT = { bullish: "↗ Yükseliş", bearish: "↘ Düşüş", neutral: "→ Nötr" };
  const MAT = { low: "düşük önem", medium: "orta önem", high: "yüksek önem" };
  const HOR = { intraday: "Gün içi", days: "Birkaç gün", weeks: "Haftalar", long_term: "Uzun vade" };
  const TYPE = { disclosure: "Bildirim", news: "Haber", social: "Sosyal", report: "Rapor", macro: "Makro", regulator: "SPK" };

  const store = {
    get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* özel pencere */ } },
  };

  const state = {
    feed: null, prices: {}, macro: null, market: "ALL", view: "feed", ticker: null,
    types: new Set(), sents: new Set(), conf: 0, q: "",
    saved: new Set(store.get("saved", [])),
  };

  // ------------------------------------------------------------ yardımcılar
  const fmtNum = (v, cur) => v == null ? "—" :
    new Intl.NumberFormat("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v) +
    (cur === "TRY" ? " ₺" : cur === "USD" ? " $" : "");
  const fmtPct = v => v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
  const cls = v => v == null ? "" : v >= 0 ? "pos" : "neg";
  const fmtTime = iso => new Date(iso).toLocaleString("tr-TR", { timeZone: TZ, day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  function ago(iso) {
    const m = Math.round((Date.now() - new Date(iso)) / 60000);
    if (m < 1) return "şimdi";
    if (m < 60) return `${m} dk önce`;
    if (m < 1440) return `${Math.round(m / 60)} sa önce`;
    return `${Math.round(m / 1440)} gün önce`;
  }

  // ------------------------------------------------------------ veri
  async function load() {
    const r = await fetch(`data/feed.json?t=${Date.now()}`);
    if (!r.ok) throw new Error("feed.json bulunamadı");
    state.feed = await r.json();
    const all = new Set([...(state.feed.watchlist || []).map(w => w.symbol),
      ...state.feed.items.map(i => i.tickers[0]).filter(Boolean)]);
    try {
      const m = await fetch(`data/macro.json?t=${Date.now()}`);
      state.macro = m.ok ? await m.json() : null;
    } catch { state.macro = null; }
    await Promise.all([...all].map(async s => {
      try {
        const p = await fetch(`data/prices/${s}.json?t=${Date.now()}`);
        if (p.ok) state.prices[s] = await p.json();
      } catch { /* fiyat yoksa kart yine görünür */ }
    }));
  }

  // ------------------------------------------------------------ filtre
  function filtered() {
    const q = state.q.toLocaleLowerCase("tr");
    return state.feed.items.filter(it => {
      if (state.market !== "ALL" && it.market !== state.market) return false;
      if (state.ticker && !(it.tickers.includes(state.ticker) || it.analysis?.affected_tickers?.includes(state.ticker))) return false;
      if (state.view === "saved" && !state.saved.has(it.id)) return false;
      const a = it.analysis;
      if (state.view === "signals" && !(a && a.sentiment !== "neutral" && a.confidence >= 70 && a.materiality !== "low")) return false;
      if (state.types.size && !state.types.has(it.source_type)) return false;
      if (state.sents.size && !(a && state.sents.has(a.sentiment))) return false;
      if (state.conf && !(a && a.confidence >= state.conf)) return false;
      if (q) {
        const hay = `${it.title} ${it.summary} ${it.source} ${it.tickers.join(" ")} ${a?.summary || ""}`.toLocaleLowerCase("tr");
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }

  // ------------------------------------------------------------ grafik
  function seriesFor(p, range) {
    if (!p) return [];
    const now = (p.intraday?.at(-1) || p.daily?.at(-1) || [0])[0];
    if (range === "1A") return (p.daily || []).filter(b => b[0] >= now - 31 * 86400);
    if (range === "1H") return (p.intraday || []).filter(b => b[0] >= now - 7 * 86400);
    const bars = p.intraday || [];
    if (!bars.length) return (p.daily || []).slice(-2);
    const lastDay = new Date(bars.at(-1)[0] * 1000).toLocaleDateString("tr-TR", { timeZone: TZ });
    return bars.filter(b => new Date(b[0] * 1000).toLocaleDateString("tr-TR", { timeZone: TZ }) === lastDay);
  }

  function drawSpark(svg, bars, newsTs) {
    svg.innerHTML = "";
    if (bars.length < 2) { svg.innerHTML = `<text x="0" y="40" fill="currentColor" font-size="11" opacity=".5">Fiyat verisi yok</text>`; return null; }
    const W = 240, H = 70, pad = 4;
    const t0 = bars[0][0], t1 = bars.at(-1)[0];
    const vals = bars.map(b => b[1]);
    const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
    const x = t => ((t - t0) / (t1 - t0 || 1)) * W;
    const y = v => H - pad - ((v - lo) / span) * (H - pad * 2);
    const up = vals.at(-1) >= vals[0];
    const color = up ? "var(--up)" : "var(--down)";
    const d = bars.map((b, i) => `${i ? "L" : "M"}${x(b[0]).toFixed(1)},${y(b[1]).toFixed(1)}`).join("");
    const ns = "http://www.w3.org/2000/svg";
    const area = document.createElementNS(ns, "path");
    area.setAttribute("d", `${d}L${W},${H}L0,${H}Z`); area.setAttribute("class", "ar"); area.setAttribute("fill", color);
    const line = document.createElementNS(ns, "path");
    line.setAttribute("d", d); line.setAttribute("class", "ln"); line.setAttribute("stroke", color);
    svg.append(area, line);
    if (newsTs >= t0 && newsTs <= t1) {
      const mk = document.createElementNS(ns, "line");
      const mx = x(newsTs).toFixed(1);
      Object.entries({ x1: mx, x2: mx, y1: 0, y2: H, class: "mk" }).forEach(([k, v]) => mk.setAttribute(k, v));
      svg.append(mk);
    }
    return (vals.at(-1) / vals[0] - 1) * 100;
  }

  // ------------------------------------------------------------ kart
  const tpl = $("#cardTpl");
  const watchSet = () => new Set((state.feed.watchlist || []).map(w => w.symbol));

  function card(it) {
    const el = tpl.content.firstElementChild.cloneNode(true);
    const watch = watchSet();
    // haber
    const shownTk = it.tickers.length ? it.tickers : (it.analysis?.affected_tickers || []).filter(t => watch.has(t));
    if (!it.tickers.length) {
      const g = document.createElement("span");
      g.className = "tk g"; g.textContent = it.market === "BIST" ? "Piyasa geneli" : "Market";
      $(".tickers", el).append(g);
    }
    $(".tickers", el).append(...shownTk.slice(0, 4).map(t => {
      const s = document.createElement("span");
      s.className = "tk" + (watch.has(t) ? " w" : "") + (it.tickers.includes(t) ? "" : " aff"); s.textContent = t;
      if (!it.tickers.includes(t)) s.title = "Claude'a göre etkilenebilecek hisse";
      s.onclick = () => { state.ticker = state.ticker === t ? null : t; render(); };
      return s;
    }));
    $(".ago", el).textContent = ago(it.published);
    const a = $(".title", el);
    a.textContent = it.analysis?.headline_tr && it.lang !== "tr" ? it.analysis.headline_tr : it.title;
    if (it.url) a.href = it.url;
    if (it.analysis?.headline_tr && it.lang !== "tr") a.title = it.title;
    $(".desc", el).textContent = it.summary || "";
    $(".src", el).textContent = it.source + (it.extra?.form ? ` · ${it.extra.form}` : "");
    $(".type", el).textContent = (TYPE[it.source_type] || it.source_type) + (it.extra?.demo ? " · ÖRNEK" : "");
    if (it.extra?.bist_measure) {
      const m = document.createElement("span");
      m.className = "measure" + (it.extra.bist_measure.includes("kaldır") || it.extra.bist_measure.includes("açıl") ? " off" : "");
      m.textContent = it.extra.bist_measure;
      $(".c-top", el).insertBefore(m, $(".ago", el));
    }
    const sv = $(".save", el);
    sv.classList.toggle("on", state.saved.has(it.id));
    sv.onclick = () => {
      state.saved.has(it.id) ? state.saved.delete(it.id) : state.saved.add(it.id);
      store.set("saved", [...state.saved]); sv.classList.toggle("on"); counts();
    };

    // AI
    const an = it.analysis;
    const sent = $(".sent", el);
    if (an) {
      sent.textContent = SENT[an.sentiment] || an.sentiment; sent.classList.add(an.sentiment);
      $(".confv", el).textContent = `%${an.confidence} güven`;
      $(".mat", el).textContent = MAT[an.materiality] || ""; $(".mat", el).classList.add(an.materiality);
      $(".ai-sum", el).textContent = an.summary || "";
      $(".ai-points", el).append(...(an.key_points || []).slice(0, 3).map(p => Object.assign(document.createElement("li"), { textContent: p })));
      $(".ai-risk", el).textContent = an.risks?.[0] ? `⚠ ${an.risks[0]}` : "";
      $(".meter", el).classList.add(an.sentiment);
      $(".meter i", el).style.width = `${an.confidence}%`;
      $(".hor", el).textContent = HOR[an.horizon] || "";
      $(".cat", el).textContent = an.category || "";
    } else {
      sent.textContent = "Değerlendirilmedi"; sent.classList.add("none");
      $(".ai-sum", el).textContent = it.tickers.some(t => watch.has(t))
        ? "Bu tur AI bütçesi dolduğu ya da anahtar tanımlı olmadığı için yorum yapılmadı."
        : it.tickers.length ? "İzleme listesi dışında; yalnızca listelendi."
        : "Piyasa geneli kayıt; izleme listesiyle doğrudan eşleşmedi.";
    }

    // fiyat
    const px = $(".c-px", el);
    const sym = it.tickers[0] || shownTk.find(t => state.prices[t]);
    if (!sym || it.source_type === "macro") { macroPanel(px, it); return el; }
    const p = state.prices[sym];
    $(".px-sym", el).innerHTML = `${sym} <small>/ ${p?.currency || (it.market === "BIST" ? "TRY" : "USD")}</small>`;
    const newsTs = Math.floor(new Date(it.published) / 1000);
    const paint = range => {
      $$(".px-rng button", el).forEach(b => b.classList.toggle("on", b.dataset.r === range));
      const chg = drawSpark($(".spark", el), seriesFor(p, range), newsTs);
      $(".px-last", el).textContent = fmtNum(p?.last, p?.currency);
      const shown = range === "1G" ? p?.change_pct : chg;
      const c = $(".px-chg", el); c.textContent = fmtPct(shown); c.className = "px-chg " + cls(shown);
    };
    $$(".px-rng button", el).forEach(b => b.onclick = () => paint(b.dataset.r));
    if (p) paint("1G"); else { $(".spark", el).remove(); px.insertAdjacentHTML("beforeend", `<p class="px-none">Fiyat verisi henüz yok.</p>`); }
    const r = it.reaction;
    if (r) {
      $(".react", el).innerHTML = [["15m", "15 dk"], ["1h", "1 sa"], ["1d", "1 gün"], ["since", "Şimdiye"]]
        .filter(([k]) => r[k] != null)
        .map(([k, l]) => `<span>${l} <b class="${cls(r[k])}">${fmtPct(r[k])}</b></span>`).join("");
    }
    $(".px-time", el).textContent = `Haber: ${fmtTime(it.published)} · ${p?.demo ? "örnek fiyat" : "Yahoo Finance, gecikmeli"}`;
    return el;
  }

  function macroPanel(px, it) {
    const ser = state.macro?.series || [];
    px.innerHTML = `<div class="px-head"><span class="px-sym">Makro göstergeler</span></div>` + (ser.length
      ? `<div class="macro">${ser.map(s => `<div><span>${s.name}</span><b>${fmtNum(s.last)}${s.unit || ""}</b><em class="${cls(s.change)}">${s.change == null ? "" : (s.change > 0 ? "+" : "") + s.change.toFixed(2)}</em></div>`).join("")}</div>
         <p class="px-time">EVDS · ${ser[0].date}${state.macro.demo ? " · örnek" : ""} · Haber: ${fmtTime(it.published)}</p>`
      : `<p class="px-none">EVDS verisi yok (EVDS_API_KEY tanımlı değil).</p><p class="px-time">Haber: ${fmtTime(it.published)}</p>`);
  }

  // ------------------------------------------------------------ çizim
  function counts() {
    const items = state.feed.items.filter(i => state.market === "ALL" || i.market === state.market);
    $("#cntFeed").textContent = items.length;
    $("#cntSig").textContent = items.filter(i => i.analysis && i.analysis.sentiment !== "neutral" && i.analysis.confidence >= 70 && i.analysis.materiality !== "low").length;
    $("#cntSaved").textContent = items.filter(i => state.saved.has(i.id)).length;
  }

  function sidebar() {
    const f = state.feed;
    const box = $("#watch"); box.innerHTML = "";
    for (const w of f.watchlist || []) {
      if (state.market !== "ALL" && w.market !== state.market) continue;
      const p = state.prices[w.symbol];
      const b = document.createElement("button");
      b.className = "w-item" + (state.ticker === w.symbol ? " on" : "");
      b.title = w.name;
      b.innerHTML = `<span><i>${w.market === "BIST" ? "TR" : "US"}</i><b>${w.symbol}</b></span><span class="chg ${cls(p?.change_pct)}">${fmtPct(p?.change_pct)}</span>`;
      b.onclick = () => { state.ticker = state.ticker === w.symbol ? null : w.symbol; render(); };
      box.append(b);
    }
    const mb = $("#macroList");
    const ser = state.macro?.series || [];
    $("#macroBox").hidden = !ser.length;
    mb.innerHTML = ser.map(s => `<div title="${s.date}"><span>${s.name}</span><b>${fmtNum(s.last)}${s.unit || ""}</b></div>`).join("");
    const esc = t => String(t).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
    $("#sources").innerHTML = (f.sources || []).map(s => {
      const warn = (s.warnings || []).length;
      const k = !s.ok ? "bad" : warn && !s.count ? "warn" : s.count ? "" : "idle";
      const tip = s.error || (s.warnings || []).join("\n");
      return `<div class="${k}" title="${esc(tip)}"><span>${esc(s.name)}</span><span>${s.ok ? s.count : "hata"}${warn ? " ⚠" : ""}</span></div>` +
        (warn ? `<p class="src-warn">${esc(s.warnings[0])}</p>` : "");
    }).join("");
    $("#gen").textContent = `Son güncelleme: ${fmtTime(f.generated)} · AI: ${f.ai?.enabled ? f.ai.model : "kapalı"}`;
    const missing = Object.entries(f.secrets || {}).filter(([k, v]) => !v && k !== "X_BEARER_TOKEN").map(([k]) => k);
    const aiErr = (f.ai?.errors || [])[0];
    const cfgMsg = [missing.length ? `Tanımlı olmayan secret: ${missing.join(", ")}` : "", aiErr ? `Claude hatası: ${aiErr}` : ""].filter(Boolean);
    let cfgEl = $("#cfgWarn");
    if (!cfgEl) { cfgEl = document.createElement("p"); cfgEl.id = "cfgWarn"; cfgEl.className = "src-warn"; $("#gen").after(cfgEl); }
    cfgEl.textContent = cfgMsg.join(" · ");
    cfgEl.hidden = !cfgMsg.length;
    const ban = $("#banner");
    if (f.demo) { ban.hidden = false; ban.textContent = "Örnek veri gösteriliyor. İlk GitHub Actions çalışmasından sonra gerçek akış burada olacak."; }
    else if (f.secrets && !f.secrets.ANTHROPIC_API_KEY) { ban.hidden = false; ban.textContent = "AI değerlendirmesi kapalı: ANTHROPIC_API_KEY secret'ı bu çalıştırmada bulunamadı (Settings → Secrets and variables → Actions)."; }
    else if (state.ticker) { ban.hidden = false; ban.innerHTML = `<b>${state.ticker}</b> filtresi açık — kaldırmak için hisseye tekrar dokun.`; }
    else ban.hidden = true;
  }

  function render() {
    sidebar(); counts();
    const list = $("#list"); list.innerHTML = "";
    const items = filtered();
    const frag = document.createDocumentFragment();
    items.slice(0, 150).forEach(it => frag.append(card(it)));
    list.append(frag);
    $("#empty").hidden = items.length > 0;
  }

  // ------------------------------------------------------------ etkileşim
  function bind() {
    $$("#marketSeg button").forEach(b => b.onclick = () => {
      state.market = b.dataset.market; state.ticker = null;
      $$("#marketSeg button").forEach(x => x.classList.toggle("on", x === b)); render();
    });
    $$("#views button").forEach(b => b.onclick = () => {
      state.view = b.dataset.view;
      $$("#views button").forEach(x => x.classList.toggle("on", x === b)); render();
    });
    const toggle = (sel, key, set) => $$(sel).forEach(b => b.onclick = () => {
      const v = b.dataset[key]; set.has(v) ? set.delete(v) : set.add(v); b.classList.toggle("on"); render();
    });
    toggle("#typeChips button", "type", state.types);
    toggle("#sentChips button", "sent", state.sents);
    $("#conf").oninput = e => { state.conf = +e.target.value; $("#confOut").textContent = state.conf; render(); };
    let t; $("#q").oninput = e => { clearTimeout(t); t = setTimeout(() => { state.q = e.target.value.trim(); render(); }, 150); };
  }

  async function boot() {
    bind();
    try { await load(); render(); }
    catch (e) { $("#list").innerHTML = `<p class="empty">Veri yüklenemedi: ${e.message}</p>`; }
    setInterval(async () => { try { await load(); render(); } catch { /* bir sonraki turda dener */ } }, 5 * 60 * 1000);
  }
  boot();
})();
