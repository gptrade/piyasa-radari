/* Piyasa Radarı — Portföy sekmesi.
   Pozisyonlar YALNIZ bu tarayıcıda saklanır (localStorage "radar.portfolio.v1"); sunucuya gönderilmez.
   Biçim ileride repoya (config/portfolio.yml) taşınabilecek şekilde sade tutulur; JSON olarak dışa/içe aktarılabilir.
   Fiyat: izleme listesi fiyat dosyaları (data/prices) → BIST geri alım fiyatları (data/bb_quotes.json) → elle girilen fiyat.
   Kur: TCMB EVDS USD/TRY (data/macro.json) ya da elle girilen kur. */
(() => {
  "use strict";
  const sh = window.shell;
  const { $, $$, esc, fmt, store, glyph, dirCls } = sh;
  const KEY = "radar.portfolio.v1";
  const SERIES = ["--series-1", "--series-2", "--series-3", "--series-4", "--series-5"];
  const S = { pf: loadPF(), px: {}, bbq: {}, cal: null, editing: null, loaded: false, sort: { k: "w", d: -1 } };

  // ─────────────────────────────── saklama
  function loadPF() {
    const v = store.get(KEY, null);
    return v && Array.isArray(v.positions) ? v : { v: 1, positions: [], usdtry: null };
  }
  function savePF() { S.pf.updated = new Date().toISOString(); store.set(KEY, S.pf); }
  const uid = () => Math.random().toString(36).slice(2, 10);
  const R = () => window.radar?.state;

  // ─────────────────────────────── veri
  async function getJSON(p) { try { const r = await fetch(`${p}?t=${Date.now()}`); return r.ok ? await r.json() : null; } catch { return null; } }
  async function load() {
    try { await window.radar?.ready; } catch { /* sinyal verisi olmadan da çalışır */ }
    const [bbq, cal] = await Promise.all([getJSON("data/bb_quotes.json"), getJSON("data/calendar.json")]);
    S.bbq = bbq?.quotes || {}; S.cal = cal;
    await fetchMissing();
    S.loaded = true;
    badge();
    const g = R()?.feed?.generated; if (g) sh.setUpdated("portfoy", g, { label: "Fiyatlar (son tarama)", staleMin: 45 });
    if (sh.route === "portfoy") render();
  }
  async function fetchMissing() {
    const have = R()?.prices || {};
    const need = [...S.pf.positions.map(p => p.sym), "_XU100", "_SPX"].filter(s => !have[s] && !(s in S.px));
    await Promise.all(need.map(async s => { S.px[s] = await getJSON(`data/prices/${s}.json`); }));
  }
  const watch = () => R()?.feed?.watchlist || [];
  function quote(pos) {
    const p = R()?.prices?.[pos.sym] || S.px[pos.sym];
    if (p?.last) return { last: p.last, chg: p.change_pct, src: "izleme", p };
    const q = pos.market === "BIST" && S.bbq[pos.sym];
    if (q?.last) return { last: q.last, chg: q.change_pct, src: "geri alım fiyatları", date: q.date };
    if (pos.manual) return { last: pos.manual, chg: null, src: "elle" };
    return null;
  }
  function usdtry() {
    const s = (R()?.macro?.series || []).find(x => x.code === "TP.DK.USD.A.YTL" || x.name === "USD/TRY");
    return S.pf.usdtry || s?.last || null;
  }
  const fxSrc = () => S.pf.usdtry ? "elle" : "TCMB EVDS";

  // ─────────────────────────────── hesap
  function rows() {
    const fx = usdtry();
    const out = S.pf.positions.map(pos => {
      const q = quote(pos), k = pos.market === "US" ? fx : 1;
      const last = q?.last ?? null, val = last != null && k ? pos.qty * last * k : null;
      const basis = pos.cost != null && k ? pos.qty * pos.cost * k : null;
      const prev = last != null && q?.chg != null ? last / (1 + q.chg / 100) : null;
      const day = prev != null && k ? pos.qty * (last - prev) * k : null;
      let alert = null;
      if (last != null && pos.stop && last <= pos.stop) alert = { k: "stop", t: "Stop altında", c: "down" };
      else if (last != null && pos.target && last >= pos.target) alert = { k: "target", t: "Hedefte", c: "up" };
      else if (last != null && pos.stop && last <= pos.stop * 1.03) alert = { k: "near", t: "Stop'a yakın", c: "warn" };
      return { pos, q, last, val, basis, day, pnl: val != null && basis != null ? val - basis : null,
        pnlPct: last != null && pos.cost ? (last / pos.cost - 1) * 100 : null, alert };
    });
    const tot = out.reduce((a, r) => a + (r.val || 0), 0);
    out.forEach(r => { r.w = tot && r.val != null ? r.val / tot * 100 : null; });
    return out;
  }
  function totals(rs) {
    const t = { val: 0, basis: 0, day: 0, bist: 0, us: 0, missing: 0 };
    rs.forEach(r => {
      if (r.val == null) { t.missing++; return; }
      t.val += r.val; t.basis += r.basis ?? r.val; t.day += r.day || 0;
      r.pos.market === "US" ? (t.us += r.val) : (t.bist += r.val);
    });
    t.pnl = t.val - t.basis; t.pnlPct = t.basis ? t.pnl / t.basis * 100 : null;
    t.dayPct = t.val - t.day ? t.day / (t.val - t.day) * 100 : null;
    return t;
  }
  // Risk: pozisyon betası (60 gün, kendi endeksine göre) ve TL bazında 1 günlük %95 tarihsel riske maruz değer (120 gün)
  const IDX = { BIST: "_XU100", US: "_SPX" };
  const dkey = (ts, tz) => new Date(ts * 1000).toLocaleDateString("en-CA", { timeZone: tz });
  const TZ = { BIST: "Europe/Istanbul", US: "America/New_York" };
  function rets(daily, tz) {
    const m = new Map();
    for (let i = 1; i < (daily || []).length; i++) m.set(dkey(daily[i][0], tz), daily[i][1] / daily[i - 1][1] - 1);
    return m;
  }
  function betaOf(sym, market) {
    const p = R()?.prices?.[sym] || S.px[sym], ix = R()?.prices?.[IDX[market]] || S.px[IDX[market]];
    if (!p?.daily || !ix?.daily) return null;
    const a = rets(p.daily, TZ[market]), b = rets(ix.daily, TZ[market]);
    const ds = [...a.keys()].filter(d => b.has(d)).slice(-61, -1);
    if (ds.length < 30) return null;
    const xs = ds.map(d => b.get(d)), ys = ds.map(d => a.get(d));
    const mx = xs.reduce((s, v) => s + v, 0) / xs.length, my = ys.reduce((s, v) => s + v, 0) / ys.length;
    const vx = xs.reduce((s, v) => s + (v - mx) ** 2, 0);
    return vx ? xs.reduce((s, v, i) => s + (v - mx) * (ys[i] - my), 0) / vx : null;
  }
  function risk(rs, t) {
    const bySide = { BIST: [0, 0], US: [0, 0] };
    rs.forEach(r => { const b = r.val != null && betaOf(r.pos.sym, r.pos.market); if (b != null && b !== false) { bySide[r.pos.market][0] += b * r.val; bySide[r.pos.market][1] += r.val; } });
    const beta = Object.fromEntries(Object.entries(bySide).map(([k, [s, w]]) => [k, w ? s / w : null]));
    // TL bazında portföy günlük getirisi: ABD pozisyonlarına kur getirisi eklenir
    const fxS = (R()?.macro?.series || []).find(x => x.code === "TP.DK.USD.A.YTL");
    const fx = new Map();
    (fxS?.history || []).forEach(([d, v], i, h) => { if (i) { const [dd, mm, yy] = d.split("-"); fx.set(`${yy}-${mm}-${dd}`, v / h[i - 1][1] - 1); } });
    const parts = rs.filter(r => r.val).map(r => {
      const p = R()?.prices?.[r.pos.sym] || S.px[r.pos.sym];
      return p?.daily ? { w: r.val / t.val, m: rets(p.daily, TZ[r.pos.market]), us: r.pos.market === "US" } : null;
    });
    const covered = parts.filter(Boolean);
    const cover = covered.reduce((s, x) => s + x.w, 0);
    if (!covered.length || cover < 0.5) return { beta, var: null, cover };
    const days = [...new Set(covered.flatMap(x => [...x.m.keys()]))].sort().slice(-121, -1);
    const pr = days.map(d => covered.reduce((s, x) => {
      const r = x.m.get(d) ?? 0, f = x.us ? (fx.get(d) ?? 0) : 0;
      return s + x.w / cover * ((1 + r) * (1 + f) - 1);
    }, 0));
    if (pr.length < 40) return { beta, var: null, cover };
    const sorted = pr.slice().sort((a, b) => a - b), q = sorted[Math.floor(0.05 * sorted.length)];
    const m = pr.reduce((s, v) => s + v, 0) / pr.length, sd = Math.sqrt(pr.reduce((s, v) => s + (v - m) ** 2, 0) / (pr.length - 1));
    return { beta, var: -q, sd, n: pr.length, cover, fx: fx.size > 0 };
  }
  // Sinyal özeti: son 24 saat
  function sig(sym) {
    const items = (R()?.feed?.items || []).filter(it => (it.tickers || []).includes(sym) && (Date.now() - new Date(it.published)) < 864e5 && it.analysis);
    const news = items.filter(it => it.source_type !== "technical");
    const strong = news.filter(it => it.analysis.sentiment !== "neutral" && it.analysis.confidence >= 70 && it.analysis.materiality !== "low");
    const net = strong.reduce((s, it) => s + (it.analysis.sentiment === "bullish" ? 1 : -1), 0);
    return { n: news.length, strong: strong.length, net, anom: items.find(it => it.extra?.anomaly) };
  }
  function nextEvent(sym) {
    const today = new Date().toLocaleDateString("en-CA", { timeZone: "Europe/Istanbul" });
    return (S.cal?.events || []).find(e => e.ticker === sym && e.date >= today);
  }

  // ─────────────────────────────── görünüm
  const tl = (v, d = 0) => v == null ? "—" : fmt.num(v, d) + " ₺";
  const tlShort = v => v == null ? "—" : Math.abs(v) >= 1e6 ? fmt.num(v / 1e6, 2) + " mn ₺" : fmt.num(v, 0) + " ₺";
  const pct = (v, d = 2) => v == null ? "—" : `<span class="${dirCls(v > 0 ? 1 : v < 0 ? -1 : 0)}">${fmt.pct(v, d)}</span>`;
  const signedTl = v => v == null ? "—" : `<span class="${dirCls(v > 0 ? 1 : v < 0 ? -1 : 0)}">${v > 0 ? "+" : v < 0 ? "−" : ""}${fmt.num(Math.abs(v), 0)} ₺</span>`;
  const cur = pos => pos.market === "US" ? "$" : "₺";

  function render() {
    const box = $("#pfBody");
    const rs = rows(), t = totals(rs), fx = usdtry();
    $("#pfCount").textContent = S.pf.positions.length ? `${S.pf.positions.length} pozisyon` : "";
    if (!S.pf.positions.length) {
      box.innerHTML = formHTML() + `<div class="card">${sh.stateHTML({ kind: "info", title: "Portföy boş",
        msg: "Yukarıdaki formdan pozisyon ekle (hisse, adet, ortalama maliyet; istersen stop ve hedef). Pozisyonlar yalnız bu tarayıcıda saklanır, sunucuya gönderilmez. Başka cihaza taşımak ya da yedeklemek için üst çubuktaki Dışa aktar → Portföy yedeği (JSON) ile indir, diğer cihazda İçe aktar ile yükle." })}</div>`;
      bindForm(); return;
    }
    const rk = risk(rs, t);
    const alerts = rs.filter(r => r.alert && r.alert.k !== "near");
    const near = rs.filter(r => r.alert?.k === "near");
    let html = "";
    if (alerts.length || near.length) html += `<div class="banner ${alerts.some(r => r.alert.k === "stop") ? "warn" : ""} pf-alerts" role="status">
      ${[...alerts, ...near].map(r => `<span><b>${esc(r.pos.sym)}</b> ${esc(r.alert.t)} (${fmt.num(r.last, 2)} ${cur(r.pos)}${r.alert.k === "target" ? ` · hedef ${fmt.num(r.pos.target, 2)}` : ` · stop ${fmt.num(r.pos.stop, 2)}`})</span>`).join("")}</div>`;
    html += `<div class="kpi-grid pf-kpis">
      <div class="kpi"><span class="kpi-label">Portföy değeri</span><span class="kpi-value">${tlShort(t.val)}</span><span class="kpi-sub">${fx ? `≈ ${fmt.num(t.val / fx, 0)} $ · USD/TRY ${fmt.num(fx, 2)}` : "kur yok"}</span></div>
      <div class="kpi"><span class="kpi-label">Bugün</span><span class="kpi-value">${signedTl(t.day)}</span><span class="kpi-sub">${t.dayPct == null ? "—" : fmt.pct(t.dayPct, 2)} · ABD kur etkisi hariç</span></div>
      <div class="kpi"><span class="kpi-label">Toplam kâr / zarar</span><span class="kpi-value">${signedTl(t.pnl)}</span><span class="kpi-sub">${t.pnlPct == null ? "—" : fmt.pct(t.pnlPct, 1)} · bugünkü kurla</span></div>
      <div class="kpi"><span class="kpi-label">1 günlük risk (%95)</span><span class="kpi-value">${rk.var != null ? tlShort(rk.var * t.val) : "—"}</span><span class="kpi-sub" data-tip="Tarihsel yöntem: bugünkü ağırlıklarla son ${rk.n || 120} günün TL bazında günlük getirileri; 20 günde 1 bu kadar ya da daha fazla kayıp beklenir${rk.cover < 0.999 ? ` (fiyat geçmişi olan pozisyonlar: portföyün %${fmt.num(rk.cover * 100, 0)}'i)` : ""}">${rk.var != null ? `%${fmt.num(rk.var * 100, 1)} · günlük oynaklık %${fmt.num(rk.sd * 100, 1)}` : "fiyat geçmişi yetersiz"}</span></div>
    </div>`;
    // dağılım
    const vals = rs.filter(r => r.val).sort((a, b) => b.val - a.val);
    const top = vals.slice(0, 5), rest = vals.slice(5).reduce((s, r) => s + r.val, 0);
    const segs = [...top.map((r, i) => ({ l: r.pos.sym, v: r.val, c: `var(${SERIES[i]})` })), ...(rest ? [{ l: "Diğer", v: rest, c: "var(--neutral)" }] : [])];
    html += `<div class="card pf-mix"><div class="card-head"><h2 class="card-title">Dağılım</h2>
        <span class="card-meta">BIST %${fmt.num(t.val ? t.bist / t.val * 100 : 0, 0)} · ABD %${fmt.num(t.val ? t.us / t.val * 100 : 0, 0)} (dolar maruziyeti)${rk.beta.BIST != null ? ` · BIST betası ${fmt.num(rk.beta.BIST, 2)}` : ""}${rk.beta.US != null ? ` · ABD betası ${fmt.num(rk.beta.US, 2)}` : ""}</span></div>
      <div class="pf-bar" role="img" aria-label="Ağırlıklar: ${segs.map(s => `${s.l} yüzde ${fmt.num(s.v / t.val * 100, 0)}`).join(", ")}">${segs.map(s =>
        `<span style="flex:${s.v};background:${s.c}" data-tip="<b>${esc(s.l)}</b> %${fmt.num(s.v / t.val * 100, 1)} · ${tlShort(s.v)}"></span>`).join("")}</div>
      <ul class="pf-leg">${segs.map(s => `<li><i style="background:${s.c}"></i>${esc(s.l)} <b>%${fmt.num(s.v / t.val * 100, 1)}</b></li>`).join("")}</ul>
      ${t.missing ? `<p class="k-note">${t.missing} pozisyonun fiyatı yok; toplamlara girmedi (satırda elle fiyat girebilirsin).</p>` : ""}</div>`;
    // tablo
    const K = S.sort, val = { w: r => r.val ?? -1, pnl: r => r.pnlPct ?? -999, day: r => r.q?.chg ?? -999, sym: r => r.pos.sym };
    const sorted = rs.slice().sort((a, b) => { const x = val[K.k](a), y = val[K.k](b); return (x > y ? 1 : x < y ? -1 : 0) * K.d; });
    const th = (k, l, cls = "") => `<th scope="col" class="${cls}">${k ? `<button type="button" class="th-sort" data-k="${k}" aria-sort="${K.k === k ? (K.d > 0 ? "ascending" : "descending") : "none"}">${l}${K.k === k ? (K.d > 0 ? " ▲" : " ▼") : ""}</button>` : l}</th>`;
    html += `<div class="card card-flush"><div class="tbl-scroll"><table class="tbl pf-tbl" aria-label="Pozisyonlar">
      <thead><tr>${th("sym", "Hisse")}${th("", "Adet", "num")}${th("", "Maliyet", "num")}${th("", "Son", "num")}${th("day", "Bugün", "num")}${th("w", "Değer (₺) · ağırlık", "num")}${th("pnl", "K/Z", "num")}${th("", "Stop / hedef", "num")}${th("", "Sinyal (24 sa)")}${th("", "")}</tr></thead>
      <tbody>${sorted.map(rowHTML).join("")}</tbody></table></div></div>`;
    // portföy haberleri
    html += newsHTML();
    html += formHTML();
    html += `<p class="k-note">Pozisyonlar yalnız bu tarayıcıda (localStorage) saklanır, sunucuya gönderilmez; tarayıcı verisi silinirse kaybolur — Dışa aktar → Portföy yedeği (JSON) ile yedekle. Fiyatlar son taramadan (15 dk); izleme listesi dışındaki BIST hisseleri için geri alım fiyat listesi, o da yoksa elle girilen fiyat kullanılır. ABD pozisyonları ${fxSrc()} USD/TRY kuruyla TL'ye çevrilir. Betalar son 60 günde kendi endeksine (BIST 100 / S&P 500) göre. Bu bir takip aracıdır, yatırım tavsiyesi değildir.</p>`;
    box.innerHTML = html;
    bindForm(); bindTable(); badge();
  }
  // Temel analiz notu (BIST-100 kapsamındaysa): tıklayınca şirket sayfası
  function faTag(sym) {
    const f = window.radarFundamentals?.rows?.find(x => x.code === sym);
    if (!f || !f.grade) return "";
    return ` <button type="button" class="grade g-${f.grade.toLowerCase()} fa-go" data-fa="${esc(sym)}" data-tip="Temel analiz: genel ${f.overall}/100 · kalite ${f.quality ?? "—"} · değerleme ${f.valuation_score ?? "—"} — şirket sayfasını aç">${f.grade}</button>`;
  }
  function rowHTML(r) {
    const p = r.pos, s = sig(p.sym), ev = nextEvent(p.sym), inW = watch().some(w => w.symbol === p.sym);
    const sd = r.last != null && p.stop ? (p.stop / r.last - 1) * 100 : null, td = r.last != null && p.target ? (p.target / r.last - 1) * 100 : null;
    return `<tr class="${r.alert ? "pf-" + r.alert.k : ""}" data-id="${p.id}">
      <th scope="row"><button type="button" class="tk-link" data-sym="${esc(p.sym)}">${esc(p.sym)}</button><span class="tag mk">${p.market === "US" ? "ABD" : "BIST"}</span>${faTag(p.sym)}
        ${p.note ? `<span class="pf-note">${esc(p.note)}</span>` : ""}</th>
      <td class="num">${fmt.num(p.qty, p.qty % 1 ? 2 : 0)}</td>
      <td class="num">${p.cost != null ? fmt.num(p.cost, 2) : "—"}</td>
      <td class="num">${r.last != null ? `${fmt.num(r.last, 2)}${r.q.src !== "izleme" ? `<span class="pf-src" data-tip="Fiyat kaynağı: ${esc(r.q.src)}${r.q.date ? " · " + esc(r.q.date) : ""}">${r.q.src === "elle" ? "elle" : "*"}</span>` : ""}` :
        `<button type="button" class="link-btn" data-a="manual" data-tip="Bu hisse izleme listesinde değil ve fiyatı bulunamadı. Elle fiyat gir ya da config/watchlist.yml'e ekle.">fiyat gir</button>`}</td>
      <td class="num">${r.q?.chg != null ? pct(r.q.chg) : "—"}</td>
      <td class="num">${r.val != null ? `${fmt.num(r.val, 0)}<span class="pf-w">%${fmt.num(r.w, 1)}</span>` : "—"}</td>
      <td class="num">${r.pnl != null ? `${signedTl(r.pnl)}<span class="pf-w">${pct(r.pnlPct, 1)}</span>` : "—"}</td>
      <td class="num pf-sl">${p.stop ? `<span data-tip="Stop'a uzaklık">${fmt.num(p.stop, 2)} <small>${fmt.pct(sd, 1)}</small></span>` : ""}${p.target ? `<span data-tip="Hedefe uzaklık">${fmt.num(p.target, 2)} <small>${fmt.pct(td, 1)}</small></span>` : ""}${!p.stop && !p.target ? "—" : ""}
        ${r.alert ? `<span class="tag pf-al ${r.alert.c}">${esc(r.alert.t)}</span>` : ""}</td>
      <td class="pf-sig">${s.anom ? `<span class="an-flag" data-tip="${esc(s.anom.analysis?.headline_tr || "Habersiz hareket")}">⚡</span>` : ""}
        ${s.n ? `<span data-tip="Son 24 saatte ${s.n} haber/bildirim, ${s.strong} güçlü sinyal">${s.strong ? `<span class="${dirCls(s.net)}">${glyph(s.net)}</span> ${s.strong} güçlü · ` : ""}${s.n} kayıt</span>` : `<span class="t3">${inW ? "haber yok" : "izlenmiyor"}</span>`}
        ${ev ? `<span class="pf-ev" data-tip="${esc(ev.title)} · ${esc(ev.date)}">📅 ${esc(ev.kind === "earnings" ? "bilanço" : ev.kind === "dividend" ? "temettü" : "olay")} ${fmt.date(ev.date + "T12:00:00Z")}</span>` : ""}</td>
      <td class="pf-act"><button type="button" class="btn btn-icon" data-a="edit" aria-label="${esc(p.sym)} pozisyonunu düzenle" data-tip="Düzenle"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 13.5V16h2.5L15 7.5 12.5 5 4 13.5z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg></button>
        <button type="button" class="btn btn-icon" data-a="del" aria-label="${esc(p.sym)} pozisyonunu sil" data-tip="Sil"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 6h10M8 6V4.5h4V6M6.5 6l.7 10h5.6l.7-10" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg></button></td>
    </tr>`;
  }
  function newsHTML() {
    const held = new Set(S.pf.positions.map(p => p.sym));
    const W = { high: 3, medium: 2, low: 1 };
    const items = (R()?.feed?.items || []).filter(it => it.analysis && (it.tickers || []).some(t => held.has(t)) && (Date.now() - new Date(it.published)) < 2 * 864e5
      && (it.analysis.materiality !== "low" || it.extra?.anomaly || it.source_type === "disclosure"))
      .map(it => ({ it, s: W[it.analysis.materiality] * it.analysis.confidence * (it.tier === 1 ? 1.3 : 1) * Math.max(.3, 1 - (Date.now() - new Date(it.published)) / 1728e5) }))
      .sort((a, b) => b.s - a.s).slice(0, 8);
    if (!items.length) return "";
    return `<div class="card pf-news"><div class="card-head"><h2 class="card-title">Pozisyonlarındaki önemli gelişmeler</h2><span class="card-meta">son 48 saat · önem ve güvene göre</span></div>
      <ul class="tp-news">${items.map(({ it }) => { const a = it.analysis, k = a.sentiment === "bullish" ? 1 : a.sentiment === "bearish" ? -1 : 0; return `
        <li><button type="button" data-id="${esc(it.id)}" data-sym="${esc((it.tickers || [])[0] || "")}"><span class="dir ${dirCls(k)}">${glyph(k)}</span>
          <span class="tp-t"><b>${esc((it.tickers || [])[0] || "")}</b> · ${a.event_label ? `<b>${esc(a.event_label)}</b> · ` : ""}${esc(a.what || a.headline_tr || it.title)}</span><span class="age">${fmt.ago(it.published)}</span></button></li>`; }).join("")}</ul></div>`;
  }
  function formHTML() {
    const e = S.editing && S.pf.positions.find(p => p.id === S.editing);
    const opts = [...new Set([...watch().map(w => w.symbol), ...Object.keys(S.bbq)])].sort().map(s => `<option value="${esc(s)}">`).join("");
    return `<form class="card pf-form" id="pfForm" autocomplete="off" novalidate>
      <div class="card-head"><h2 class="card-title">${e ? `${esc(e.sym)} pozisyonunu düzenle` : "Pozisyon ekle"}</h2>
        <span class="card-meta">${e ? "" : "aynı hisse tekrar eklenirse ortalama maliyet ağırlıklı hesaplanır"}</span></div>
      <div class="pf-fields">
        <label>Hisse<input name="sym" list="pfSyms" required value="${esc(e?.sym || "")}" placeholder="THYAO" ${e ? "readonly" : ""} style="text-transform:uppercase"></label>
        <label>Piyasa<select name="market"><option value="BIST"${e?.market !== "US" ? " selected" : ""}>BIST</option><option value="US"${e?.market === "US" ? " selected" : ""}>ABD</option></select></label>
        <label>Adet<input name="qty" inputmode="decimal" required value="${e ? String(e.qty).replace(".", ",") : ""}" placeholder="1.000"></label>
        <label>Ort. maliyet<input name="cost" inputmode="decimal" required value="${e?.cost != null ? String(e.cost).replace(".", ",") : ""}" placeholder="285,40"></label>
        <label><span>Stop <small>ops.</small></span><input name="stop" inputmode="decimal" value="${e?.stop ? String(e.stop).replace(".", ",") : ""}"></label>
        <label><span>Hedef <small>ops.</small></span><input name="target" inputmode="decimal" value="${e?.target ? String(e.target).replace(".", ",") : ""}"></label>
        <label class="pf-wide"><span>Not <small>ops.</small></span><input name="note" maxlength="80" value="${esc(e?.note || "")}" placeholder="tez, vade…"></label>
      </div>
      <datalist id="pfSyms">${opts}</datalist>
      <div class="pf-form-foot"><span class="pf-err" id="pfErr" role="alert"></span>
        ${e ? `<button type="button" class="btn" id="pfCancel">Vazgeç</button>` : ""}<button type="submit" class="btn btn-primary">${e ? "Kaydet" : "Ekle"}</button></div>
    </form>`;
  }
  // Türkçe sayı: "1.500" → 1500, "62,30" → 62.3, "1.234,5" → 1234.5, "0.75" → 0.75
  const num = v => {
    if (v == null || String(v).trim() === "") return null;
    let t = String(v).trim().replace(/\s/g, "");
    if (/,/.test(t)) t = t.replace(/\./g, "").replace(",", ".");
    else if (/^\d{1,3}(\.\d{3})+$/.test(t)) t = t.replace(/\./g, "");
    const n = Number(t); return isFinite(n) ? n : NaN;
  };
  function bindForm() {
    const f = $("#pfForm"); if (!f) return;
    f.sym.addEventListener("change", () => {
      const s = f.sym.value.trim().toUpperCase(), w = watch().find(x => x.symbol === s);
      if (w) f.market.value = w.market; else if (S.bbq[s]) f.market.value = "BIST";
    });
    $("#pfCancel")?.addEventListener("click", () => { S.editing = null; render(); });
    f.addEventListener("submit", ev => {
      ev.preventDefault();
      const sym = f.sym.value.trim().toUpperCase().replace(/\.IS$/, ""), qty = num(f.qty.value), cost = num(f.cost.value),
        stop = num(f.stop.value), target = num(f.target.value), err = $("#pfErr");
      if (!/^[A-Z0-9.\-]{1,12}$/.test(sym)) { err.textContent = "Geçerli bir hisse kodu yaz."; f.sym.focus(); return; }
      if (!(qty > 0)) { err.textContent = "Adet pozitif bir sayı olmalı."; f.qty.focus(); return; }
      if (!(cost > 0)) { err.textContent = "Ortalama maliyet pozitif bir sayı olmalı."; f.cost.focus(); return; }
      if ([stop, target].some(Number.isNaN)) { err.textContent = "Stop ve hedef sayı olmalı (boş bırakılabilir)."; return; }
      const rec = { sym, market: f.market.value, qty, cost, stop, target, note: f.note.value.trim() || null };
      if (S.editing) Object.assign(S.pf.positions.find(p => p.id === S.editing), rec);
      else {
        const ex = S.pf.positions.find(p => p.sym === sym && p.market === rec.market);
        if (ex) { ex.cost = (ex.cost * ex.qty + cost * qty) / (ex.qty + qty); ex.qty += qty; ex.stop = stop ?? ex.stop; ex.target = target ?? ex.target; ex.note = rec.note || ex.note; }
        else S.pf.positions.push({ id: uid(), ...rec });
      }
      S.editing = null; savePF(); fetchMissing().then(render); render(); sh.syncActions();
    });
  }
  function bindTable() {
    $$("#pfBody .th-sort").forEach(b => b.onclick = () => { const k = b.dataset.k; S.sort = { k, d: S.sort.k === k ? -S.sort.d : k === "sym" ? 1 : -1 }; render(); $(`#pfBody .th-sort[data-k="${k}"]`)?.focus(); });
    $("#pfBody").onclick = e => {
      const fa = e.target.closest("[data-fa]");
      if (fa) { sh.go("hisse", { param: fa.dataset.fa }); return; }
      const tk = e.target.closest(".tk-link");
      if (tk) { window.radar?.openTicker?.(tk.dataset.sym, tk); return; }
      const nb = e.target.closest(".pf-news button");
      if (nb) { window.radar?.openItem?.(nb.dataset.id, nb.dataset.sym || undefined); $("#sidePanel").hidden = false; return; }
      const b = e.target.closest("[data-a]"); if (!b) return;
      const id = b.closest("tr")?.dataset.id, pos = S.pf.positions.find(p => p.id === id); if (!pos) return;
      if (b.dataset.a === "edit") { S.editing = id; render(); $("#pfForm").scrollIntoView({ block: "center" }); $("#pfForm [name=qty]").focus(); }
      if (b.dataset.a === "del" && confirm(`${pos.sym} pozisyonu silinsin mi?`)) { S.pf.positions = S.pf.positions.filter(p => p.id !== id); savePF(); render(); sh.syncActions(); }
      if (b.dataset.a === "manual") { const v = num(prompt(`${pos.sym} için güncel fiyat (${cur(pos)})`)); if (v > 0) { pos.manual = v; savePF(); render(); } }
    };
  }
  function badge() {
    const n = rows().filter(r => r.alert && r.alert.k !== "near").length;
    sh.setBadge("portfoy", n, n ? `${n} pozisyonda stop ya da hedef seviyesi geçildi` : "");
  }
  // ─────────────────────────────── içe / dışa aktarma
  function exportJSON() {
    const ex = window.radarExport; if (!ex) return;
    ex.download(`portfoy_yedek_${ex.stamp()}.json`, JSON.stringify({ ...S.pf, format: "piyasa-radari-portfoy" }, null, 2), "application/json");
  }
  function exportCSV() {
    const ex = window.radarExport; if (!ex) return;
    ex.download(`portfoy_${ex.stamp()}.csv`, ex.toCSV(rows().map(r => ({ hisse: r.pos.sym, piyasa: r.pos.market, adet: r.pos.qty, maliyet: r.pos.cost,
      son_fiyat: r.last ?? "", bugun_yuzde: r.q?.chg ?? "", deger_tl: r.val != null ? Math.round(r.val) : "", agirlik_yuzde: r.w != null ? +r.w.toFixed(2) : "",
      kz_tl: r.pnl != null ? Math.round(r.pnl) : "", kz_yuzde: r.pnlPct != null ? +r.pnlPct.toFixed(2) : "", stop: r.pos.stop ?? "", hedef: r.pos.target ?? "", not: r.pos.note || "" }))), "text/csv;charset=utf-8");
  }
  function importFile(file) {
    const rd = new FileReader();
    rd.onload = () => {
      try {
        const d = JSON.parse(rd.result);
        const ps = (d.positions || []).filter(p => p.sym && p.qty > 0).map(p => ({ id: p.id || uid(), sym: String(p.sym).toUpperCase(), market: p.market === "US" ? "US" : "BIST",
          qty: +p.qty, cost: p.cost != null ? +p.cost : null, stop: p.stop ?? null, target: p.target ?? null, note: p.note ?? null, manual: p.manual ?? null }));
        if (!ps.length) throw new Error("dosyada pozisyon yok");
        if (S.pf.positions.length && !confirm(`Mevcut ${S.pf.positions.length} pozisyonun yerine dosyadaki ${ps.length} pozisyon yüklensin mi?`)) return;
        S.pf = { v: 1, positions: ps, usdtry: d.usdtry ?? null }; savePF(); fetchMissing().then(render); render(); sh.syncActions();
      } catch (e) { alert("Portföy dosyası okunamadı: " + e.message); }
    };
    rd.readAsText(file);
  }
  function bindTools() {
    $("#pfImport").onclick = () => $("#pfFile").click();
    $("#pfFile").onchange = e => { const f = e.target.files[0]; if (f) importFile(f); e.target.value = ""; };
    $("#pfFx").onclick = () => {
      const v = prompt("USD/TRY kuru (boş bırakılırsa TCMB EVDS kuru kullanılır)", S.pf.usdtry ? String(S.pf.usdtry).replace(".", ",") : "");
      if (v === null) return;
      const n = num(v); S.pf.usdtry = n > 0 ? n : null; savePF(); render();
    };
  }
  bindTools();
  addEventListener("fundamentalsloaded", () => { if (sh.route === "portfoy") render(); });
  addEventListener("storage", e => { if (e.key && e.key.endsWith(KEY)) { S.pf = loadPF(); if (sh.route === "portfoy") render(); } });
  sh.register("portfoy", {
    onShow() { if (!S.loaded) { $("#pfBody").innerHTML = `<div class="card"><div class="skeleton sk-line w40"></div><div class="skeleton sk-line"></div></div>`; load(); } else render(); },
    async refresh() { await window.radar?.poll?.(); S.px = {}; await load(); },
    exports: () => [{ label: "Portföy yedeği (JSON)", hint: "başka cihaza taşımak için", run: exportJSON, disabled: !S.pf.positions.length },
      { label: "Pozisyonlar (CSV)", hint: "güncel değerlerle", run: exportCSV, disabled: !S.pf.positions.length }],
    exportInfo: () => `${S.pf.positions.length} pozisyon`,
    exportNote: "Portföy boş",
  });
  setTimeout(() => { if (!S.loaded && S.pf.positions.length) load(); }, 2000);   // rozet için arka planda
  window.radarPortfolio = { held: () => new Set(S.pf.positions.map(p => p.sym)) };
})();
