/* Lyra Radar — Piyasa Gücü: BIST'in iç gücü (genişlik + rejim), sektör rotasyonu ve güçlü sektörlerin güçlü hisseleri.
   Veri: data/guc/guc.json (guc.yml, hafta içi kapanıştan sonra → guc dalı; radar/guc.py). Tarayıcı yalnız gösterir.
   Rota: #piyasa-gucu/genislik | /sektor | /hisse. Bugün sayfasına rejim kartı verir (window.radarGuc.card). */
(() => {
  "use strict";
  const sh = window.shell;
  const { $, $$, esc, fmt } = sh;
  const SRC = "data/guc/guc.json";
  const S = { doc: null, loaded: false, loading: false, error: null, missing: false, tab: "genislik", per: "1A", range: 252,
    sort: "rank", sdir: 1, tmPer: "d1", tmSec: "", tmSize: "mcap", vKind: "endeks", vSort: "mcap", hs: { quad: true, rs: 80, tt: 6, vol: false, liq: true, sec: "", q: "", sort: "rs", sdir: 1, limit: 60 }, selSec: null };
  const TABS = { genislik: "Genişlik ve rejim", harita: "Isı haritası", sektor: "Sektör rotasyonu", hisse: "Güçlü hisseler", deger: "Değerleme", kuresel: "Küresel" };
  const REG = {
    boga: ["Boğa", "up", "Endeks ve genişlik birlikte güçlü"],
    duzeltme: ["Düzeltme / kararsız", "warn-t", "Endeks ile genişlik ayrışıyor"],
    ayi: ["Ayı", "down", "Endeks ve genişlik birlikte zayıf"],
    dip: ["Dip arayışı", "warn-t", "Zayıf trend, ama aşırı satım / panik / pozitif diverjans"],
    toparlanma: ["Toparlanma", "up", "Genişlik sıçraması ya da %90 alım günü"],
  };
  const QUAD = { lider: ["Lider", "var(--up)"], zayif: ["Zayıflayan", "var(--warn, #c98a1b)"], geride: ["Geride", "var(--down)"], iyilesen: ["İyileşen", "var(--series-1)"] };
  const PERS = ["1G", "1H", "1A", "3A", "6A", "YBB", "1Y"];

  async function load(force = false) {
    if (S.loading || (S.loaded && !force)) return;
    S.loading = true; S.error = null; S.missing = false;
    if (!S.loaded && sh.route === "piyasa-gucu") renderLoading();
    try {
      const r = await fetch(`${SRC}?t=${Date.now()}`, { cache: "no-store" });
      if (r.status === 404) { S.missing = true; throw new Error("veri henüz yayımlanmadı"); }
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      S.doc = await r.json(); S.loaded = true;
      sh.setUpdated("piyasa-gucu", new Date(S.doc.generated), { label: "Hesaplandı", staleMin: 60 * 30 });
      dispatchEvent(new Event("radar:guc"));
    } catch (e) { S.error = e.message || "veri okunamadı"; }
    finally { S.loading = false; }
    if (sh.route === "piyasa-gucu") S.loaded ? render() : renderError();
  }
  function renderLoading() {
    $("#gcBody").innerHTML = `<div class="kpi-grid">${Array.from({ length: 4 }, () => `<div class="kpi"><div class="skeleton sk-line w60"></div><div class="skeleton sk-line lg w40"></div></div>`).join("")}</div><div class="skeleton sk-block" style="height:360px;margin-top:16px"></div>`;
  }
  function renderError() {
    $("#gcBody").innerHTML = S.missing
      ? sh.stateHTML({ kind: "info", title: "Piyasa gücü henüz hesaplanmadı", msg: "Hesap hafta içi kapanıştan sonra çalışıyor; ilk sonuç bir sonraki turda görünecek." })
      : sh.stateHTML({ kind: "error", title: "Piyasa gücü yüklenemedi", msg: esc(S.error), action: "Tekrar dene", actionId: "gcRetry" });
    $("#gcRetry")?.addEventListener("click", () => load(true));
  }

  const pc = (v, d = 1) => v == null || !isFinite(v) ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${fmt.num(Math.abs(v) * 100, d)}%`;
  const pp = (v, d = 0) => v == null ? "—" : `%${fmt.num(v * 100, d)}`;
  const sgn = v => v == null ? "" : v > 0 ? "up" : v < 0 ? "down" : "";
  const dlab = iso => { const [y, m, d] = iso.split("-"); return `${+d} ${["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"][+m - 1]} ${y.slice(2)}`; };
  const seg = (id, opts, cur, lbl) => `<div class="seg" role="radiogroup" aria-label="${lbl}" id="${id}">${Object.entries(opts).map(([v, l]) =>
    `<button type="button" role="radio" data-v="${v}" aria-checked="${String(cur) === String(v)}">${l}</button>`).join("")}</div>`;
  const kpi = (label, value, sub = "", tip = "") => `<div class="kpi" ${tip ? `data-tip="${esc(tip)}"` : ""}><span class="kpi-label">${label}</span><span class="kpi-value">${value}</span>${sub ? `<span class="kpi-sub">${sub}</span>` : ""}</div>`;

  // ─────────────────────────────── grafik
  // series: [{v:[], kind:"line"|"bar", color, label, axis:"l"|"r"}]; bg: [[iso, cls]] (rejim şeridi); marks: [{d, cls, tip}]
  function chart(dates, series, { h = 220, w = 900, bands = [], marks = [], bg = null, fmtY = v => fmt.num(v, 0), zero = false, title = "" } = {}) {
    const W = w, P = { l: 52, r: 14, t: 10, b: 24 }, n = dates.length;
    if (n < 2) return "";
    const vals = series.flatMap(s => s.v).filter(v => v != null && isFinite(v));
    let lo = Math.min(...vals, ...bands.map(b => b.v)), hi = Math.max(...vals, ...bands.map(b => b.v));
    if (zero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
    if (lo === hi) { lo -= 1; hi += 1; }
    const pad = (hi - lo) * 0.06; lo -= pad; hi += pad;
    const x = i => P.l + (W - P.l - P.r) * i / (n - 1), y = v => P.t + (h - P.t - P.b) * (hi - v) / (hi - lo);
    const bw = Math.max(1, (W - P.l - P.r) / n * 0.8);
    const ticks = [lo + pad, (lo + hi) / 2, hi - pad];
    const months = []; let pm = "";
    dates.forEach((d, i) => { const m = d.slice(0, 7); if (m !== pm) { pm = m; months.push(i); } });
    const step = Math.ceil(months.length / (W / 90));
    let bgs = "";
    if (bg) {
      const idx = new Map(dates.map((d, i) => [d, i]));
      const pts = bg.map(([d, c]) => [idx.get(d) ?? dates.findIndex(z => z >= d), c]).filter(([i]) => i >= 0);
      pts.forEach(([i, c], k) => { const j = k + 1 < pts.length ? pts[k + 1][0] : n - 1; bgs += `<rect class="gc-bg ${c}" x="${x(i)}" y="${P.t}" width="${Math.max(0, x(j) - x(i))}" height="${h - P.t - P.b}"/>`; });
    }
    const idx = new Map(dates.map((d, i) => [d, i]));
    return `<svg class="gc-svg" viewBox="0 0 ${W} ${h}" role="img" aria-label="${esc(title)}">${bgs}
      ${ticks.map(t => `<line x1="${P.l}" x2="${W - P.r}" y1="${y(t)}" y2="${y(t)}" class="g"/><text x="${P.l - 6}" y="${y(t) + 4}" text-anchor="end">${fmtY(t)}</text>`).join("")}
      ${zero ? `<line x1="${P.l}" x2="${W - P.r}" y1="${y(0)}" y2="${y(0)}" class="z"/>` : ""}
      ${bands.map(b => `<line x1="${P.l}" x2="${W - P.r}" y1="${y(b.v)}" y2="${y(b.v)}" class="band"/><text x="${W - P.r - 4}" y="${y(b.v) - 4}" text-anchor="end" class="bl">${esc(b.l)}</text>`).join("")}
      ${months.filter((_, k) => k % step === 0).map(i => `<text x="${x(i)}" y="${h - 6}" text-anchor="middle">${dlab(dates[i]).split(" ").slice(1).join(" ")}</text>`).join("")}
      ${series.map(s => s.kind === "bar"
        ? s.v.map((v, i) => v == null ? "" : `<rect x="${x(i) - bw / 2}" y="${Math.min(y(0), y(v))}" width="${bw}" height="${Math.max(0.5, Math.abs(y(v) - y(0)))}" fill="${s.color || (v >= 0 ? "var(--up)" : "var(--down)")}" opacity="${s.op ?? 0.85}"/>`).join("")
        : `<path class="ln" style="stroke:${s.color}" d="${s.v.map((v, i) => v == null ? "" : `${i && s.v[i - 1] != null ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("")}"/>`).join("")}
      ${marks.map(m => { const i = idx.get(m.d); if (i == null) return ""; const s0 = series[0].v[i]; return `<circle class="mk ${m.cls}" cx="${x(i)}" cy="${s0 != null ? y(s0) : P.t + 6}" r="5"><title>${esc(m.tip)}</title></circle>`; }).join("")}
      <rect class="gc-hit" x="${P.l}" y="${P.t}" width="${W - P.l - P.r}" height="${h - P.t - P.b}" data-n="${n}"/>
    </svg>${series.length > 1 || series[0].label ? `<div class="chart-legend">${series.filter(s => s.label).map(s => `<span><i style="background:${s.color || "var(--up)"}"></i>${esc(s.label)}</span>`).join("")}</div>` : ""}`;
  }
  const ema = (xs, n) => { const k = 2 / (n + 1); let e = null; return xs.map(v => v == null ? e : (e = e == null ? v : v * k + e * (1 - k))); };
  const sma = (xs, n) => xs.map((_, i) => { if (i < n - 1) return null; let s = 0, c = 0; for (let j = i - n + 1; j <= i; j++) if (xs[j] != null) { s += xs[j]; c++; } return c ? s / c : null; });

  // ─────────────────────────────── rejim kartı (Bugün sayfası da kullanır)
  function regimeCard(compact = false) {
    if (!S.loaded) return "";
    const g = S.doc.regime, c = g.c, f = g.flags, r = REG[g.state] || REG.duzeltme;
    const ck = (ok, txt, tip = "") => `<li class="${ok ? "ok" : "no"}" ${tip ? `data-tip="${esc(tip)}"` : ""}><span aria-hidden="true">${ok ? "✓" : "✗"}</span>${txt}</li>`;
    const conds = [
      ck(c.above200, "XU100 200 günlük ortalamanın üstünde"),
      ck(c.golden, "50 günlük ortalama 200 günlüğün üstünde"),
      ck(c.br200 >= 0.5, `Hisselerin ${pp(c.br200)}'i 200 günlük ortalamanın üstünde`, "Eşik %50"),
      ck(c.nhl50 > 0, `Net yeni zirve − dip (50 gün ort.) ${fmt.num(c.nhl50, 0)}`),
      ck(c.mco > 0, `McClellan osilatörü ${fmt.num(c.mco, 0)}`, "Yükselen − düşen hisse farkının 19 ve 39 günlük EMA farkı; sıfırın üstü kısa vadeli genişliğin olumlu olduğunu gösterir"),
    ].join("");
    const sig = [
      f.thrust && `<span class="tag up">Genişlik sıçraması · ${dlab(f.thrust)}</span>`,
      f.up90 && `<span class="tag up">${f.up90} %90 alım günü (15 gün)</span>`,
      f.down90 && `<span class="tag down">${f.down90} %90 satış günü (15 gün)</span>`,
      f.posdiv && `<span class="tag up" data-tip="${esc(`XU100 yeni dip yaptı ama yeni dibe düşen hisse ${f.posdiv.now} (pencere zirvesi ${f.posdiv.peak})`)}">Pozitif diverjans · ${dlab(f.posdiv.d)}</span>`,
      f.negdiv && `<span class="tag down" data-tip="${esc(`XU100 yeni zirve yaptı ama yeni zirvedeki hisse ${f.negdiv.now} (pencere zirvesi ${f.negdiv.peak})`)}">Negatif diverjans · ${dlab(f.negdiv.d)}</span>`,
      f.oversold && `<span class="tag warn">Aşırı satım: 20/50 günlük ortalamanın üstündeki hisse < %15</span>`,
    ].filter(Boolean).join("");
    return `<section class="card gc-reg" data-tone="${r[1]}" aria-labelledby="gcRegT">
      <div class="card-head"><h2 class="card-title" id="gcRegT">Piyasa rejimi · <span class="${r[1]}">${r[0]}</span></h2><span class="card-meta">${dlab(g.asof)} kapanışı${compact ? ` · <a href="#piyasa-gucu/genislik">Piyasa Gücü →</a>` : ""}</span></div>
      <p class="t2">${esc(g.why)}</p>
      ${compact ? `<div class="gc-sig">${sig}</div>` : `<div class="res-cols"><div><p class="d-sub">Koşullar</p><ul class="gc-ck">${conds}</ul></div><div><p class="d-sub">Son sinyaller</p><div class="gc-sig">${sig || `<span class="t3">Son 15–30 günde sinyal yok</span>`}</div></div></div>`}
    </section>`;
  }

  // ─────────────────────────────── 1. genişlik
  function tabBreadth() {
    const d = S.doc, s = d.series, n = s.d.length, k = Math.min(S.range, n), sl = a => a.slice(n - k);
    const D = sl(s.d), L = i => s[i].at(-1);
    const nhl = s.nh.map((v, i) => v == null || s.nl[i] == null ? null : v - s.nl[i]);
    const ewr = sl(s.ew_rel), ewr0 = ewr.find(v => v != null);
    const ad = sl(s.ad_line), ad0 = ad.find(v => v != null);
    const bg = d.regime_hist.map(([dd, st]) => [dd, "r-" + st]);
    const ev = d.events;
    const marks = [...ev.thrust.map(t => ({ d: t, cls: "th", tip: `Genişlik sıçraması ${dlab(t)}` })),
      ...ev.ninety.map(e => ({ d: e.d, cls: e.k === "up" ? "u90" : "d90", tip: `%90 ${e.k === "up" ? "alım" : "satış"} günü ${dlab(e.d)}` })),
      ...ev.div.map(e => ({ d: e.d, cls: e.k === "pos" ? "pdv" : "ndv", tip: `${e.k === "pos" ? "Pozitif" : "Negatif"} diverjans ${dlab(e.d)}` }))];
    const ewr1a = s.ew_rel.length > 22 ? s.ew_rel.at(-1) / s.ew_rel.at(-22) - 1 : null;
    const card = (id, title, meta, body, foot = "") => `<section class="card" aria-labelledby="${id}"><div class="card-head"><h2 class="card-title" id="${id}">${title}</h2><span class="card-meta">${meta}</span></div>${body}${foot ? `<p class="t3 gc-foot">${foot}</p>` : ""}</section>`;
    return `${regimeCard()}
      <div class="kpi-grid">
        ${kpi("20 / 50 / 200 günlük ort. üstü", `${pp(L("p20"))} · ${pp(L("p50"))} · ${pp(L("p200"))}`, "hisse oranı · %15 altı aşırı satım, %85 üstü aşırı alım")}
        ${kpi("Yeni zirve / dip (52 hafta)", `<span class="up">${fmt.int(L("nh"))}</span> / <span class="down">${fmt.int(L("nl"))}</span>`, `net 50 gün ort. ${fmt.num(d.regime.c.nhl50, 0)}`)}
        ${kpi("Yükselen / düşen", `<span class="up">${fmt.int(L("adv"))}</span> / <span class="down">${fmt.int(L("dec"))}</span>`, `yükselen hacim payı ${pp(L("upv"))}`, "Yükselen hisselerin TL hacminin, yükselen + düşen hisselerin toplam hacmine oranı. %90 üstü/%10 altı günler aşağıda işaretli.")}
        ${kpi("Eşit ağırlık / XU100 (1 ay)", `<span class="${sgn(ewr1a)}">${pc(ewr1a)}</span>`, "eksi: yükseliş/düşüş büyük hisselerde, tabana yayılmıyor", "Eşit ağırlıklı BIST Tüm endeksinin XU100'e oranının son 1 aydaki değişimi")}
      </div>
      <div class="toolbar">${seg("gcRange", { 126: "6A", 252: "1Y", 504: "2Y", 756: "3Y" }, S.range, "Grafik dönemi")}<span class="grow"></span><span class="card-meta">Arka plan: rejim · <i class="gc-dot th"></i> sıçrama <i class="gc-dot u90"></i> %90 alım <i class="gc-dot d90"></i> %90 satış <i class="gc-dot pdv"></i> pozitif / <i class="gc-dot ndv"></i> negatif diverjans</span></div>
      ${card("gcC1", "XU100 ve piyasa rejimi", "kapanış · arka plan rejim", chart(D, [{ v: sl(s.bench), kind: "line", color: "var(--text)", label: "XU100" }], { bg, marks, h: 240, fmtY: v => fmt.num(v, 0), title: "XU100" }),
        `<span class="gc-key"><i class="r-boga"></i>Boğa <i class="r-toparlanma"></i>Toparlanma <i class="r-duzeltme"></i>Düzeltme <i class="r-dip"></i>Dip arayışı <i class="r-ayi"></i>Ayı</span>`)}
      <div class="fa-two">
        ${card("gcC2", "Ortalamanın üstündeki hisse oranı", "BIST Tüm", chart(D, [{ v: sl(s.p50).map(v => v == null ? null : v * 100), color: "var(--series-1)", label: "50 günlük" }, { v: sl(s.p200).map(v => v == null ? null : v * 100), color: "var(--series-2)", label: "200 günlük" }, { v: sl(s.p20).map(v => v == null ? null : v * 100), color: "var(--text-3)", label: "20 günlük" }], { bands: [{ v: 15, l: "aşırı satım" }, { v: 85, l: "aşırı alım" }], fmtY: v => `%${fmt.num(v, 0)}`, title: "ortalama üstü oran", w: 520, h: 260 }),
          "Dipler çoğunlukla 20 ve 50 günlükte %15'in altında oluşur; endeks yeni dip yaparken bu oran daha yüksekte kalıyorsa satış zayıflıyor demektir.")}
        ${card("gcC3", "Net yeni zirve − yeni dip", "52 hafta · çizgi 50 günlük ortalama", chart(D, [{ v: sl(nhl), kind: "bar" }, { v: sl(sma(nhl, 50)), color: "var(--text)" }], { zero: true, title: "net yeni zirve dip", w: 520, h: 260 }),
          `En az 11 aylık geçmişi olan ${fmt.int(L("nhl_n"))} hisse. Endeks yeni dip yaparken yeni dipteki hisse sayısı azalıyorsa pozitif diverjans.`)}
      </div>
      <div class="fa-two">
        ${card("gcC4", "McClellan osilatörü", "oran ayarlı · yükselen − düşen", chart(D, [{ v: sl(s.mco), kind: "bar" }], { zero: true, title: "McClellan", w: 520, h: 260 }),
          "Yükselen − düşen hisse farkının (oran olarak) 19 ve 39 günlük EMA farkı. Derin eksiden sıfırın üstüne dönüş, kısa vadeli dip sonrası genişlemenin işaretidir.")}
        ${card("gcC5", "Yükselen–düşen çizgisi ve eşit ağırlık / XU100", "dönem başı = 100", chart(D, [{ v: ad.map(v => v == null ? null : 100 + (v - ad0) / 50), color: "var(--series-1)", label: "Yükselen − düşen (birikimli, ölçekli)" }, { v: ewr.map(v => v == null ? null : v / ewr0 * 100), color: "var(--series-2)", label: "Eşit ağırlık / XU100" }], { title: "AD çizgisi", w: 520, h: 260 }),
          "Endeks yeni zirve yaparken yükselen–düşen çizgisi yapamıyorsa yükseliş daralıyordur (tepe uyarısı). Eşit ağırlık / XU100 düşüyorsa hareket büyük hisselerde yoğunlaşmış.")}
      </div>
      ${card("gcC6", "Yükselen hacim payı", "%90 üstü alım, %10 altı satış günü", chart(D, [{ v: sl(s.upv).map(v => v == null ? null : v * 100 - 50), kind: "bar" }], { zero: true, h: 160, bands: [{ v: 40, l: "%90 alım" }, { v: -40, l: "%90 satış" }], fmtY: v => `%${fmt.num(v + 50, 0)}`, title: "yükselen hacim" }),
        "Panik (%90 satış) günlerinin ardından gelen %90 alım günü ya da 10 gün içinde yükselen oranının %40'ın altından %61,5'in üstüne çıkması (Zweig sıçraması) güçlü dip teyitleri olarak bilinir. BIST'teki isabetleri geriye dönük testle ayrıca ölçülecek.")}`;
  }

  // ─────────────────────────────── 2. sektör
  function rrgChart(secs) {
    const W = 640, H = 460, P = 36;
    // ölçek: son konumların tamamı + kuyrukların %90'ı (uç kuyruklar kenarda kırpılır, kalabalık merkez açılır)
    const lastP = secs.map(s => s.tail.filter(t => t[0] != null).at(-1)).filter(Boolean), allP = secs.flatMap(s => s.tail.filter(t => t[0] != null));
    const q90 = a => { const v = a.sort((p, q) => p - q); return v[Math.floor(v.length * 0.9)] || 4; };
    const rx = Math.max(3, ...lastP.map(t => Math.abs(t[0] - 100)), q90(allP.map(t => Math.abs(t[0] - 100)))) * 1.12;
    const ry = Math.max(3, ...lastP.map(t => Math.abs(t[1] - 100)), q90(allP.map(t => Math.abs(t[1] - 100)))) * 1.12;
    const clampX = v => Math.max(100 - rx, Math.min(100 + rx, v)), clampY = v => Math.max(100 - ry, Math.min(100 + ry, v));
    const top = new Set([...secs].sort((a, b) => a.rank - b.rank).slice(0, 6).map(s => s.name));
    const show = s => S.selSec ? S.selSec === s.name : top.has(s.name) || s.quad === "lider" || s.quad_prev !== s.quad;
    const x = v => P + (W - 2 * P) * (clampX(v) - 100 + rx) / (2 * rx), y = v => P + (H - 2 * P) * (100 + ry - clampY(v)) / (2 * ry);
    const q = (x0, y0, x1, y1, cls, lbl, ax, ay, anc) => `<rect class="q ${cls}" x="${x0}" y="${y0}" width="${x1 - x0}" height="${y1 - y0}"/><text class="ql" x="${ax}" y="${ay}" text-anchor="${anc}">${lbl}</text>`;
    const cx = x(100), cy = y(100);
    return `<svg class="gc-rrg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Sektör rotasyon grafiği">
      ${q(cx, P, W - P, cy, "lider", "Lider", W - P - 6, P + 16, "end")}${q(cx, cy, W - P, H - P, "zayif", "Zayıflayan", W - P - 6, H - P - 8, "end")}
      ${q(P, cy, cx, H - P, "geride", "Geride", P + 6, H - P - 8, "start")}${q(P, P, cx, cy, "iyilesen", "İyileşen", P + 6, P + 16, "start")}
      <line x1="${cx}" x2="${cx}" y1="${P}" y2="${H - P}" class="z"/><line x1="${P}" x2="${W - P}" y1="${cy}" y2="${cy}" class="z"/>
      <text x="${W - P}" y="${H - 10}" text-anchor="end" class="ax">göreli güç oranı →</text><text x="12" y="${P - 10}" class="ax">↑ ivme</text>
      ${secs.map(s => { const t = s.tail.filter(p => p[0] != null), sel = S.selSec === s.name, col = QUAD[s.quad][1]; if (!t.length) return "";
        const last = t.at(-1);
        const on = show(s);
        return `<g class="gc-sec ${sel ? "sel" : ""} ${on ? "" : "dim"}" data-sec="${esc(s.name)}">${on ? `<path d="${t.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join("")}" style="stroke:${col}"/>
          ${t.slice(0, -1).map(p => `<circle cx="${x(p[0])}" cy="${y(p[1])}" r="2" style="fill:${col}"/>`).join("")}` : ""}
          <circle cx="${x(last[0])}" cy="${y(last[1])}" r="${sel ? 7 : on ? 5 : 4}" style="fill:${col}"><title>${esc(`${s.name} · sıra ${s.rank} · ${QUAD[s.quad][0]} · oran ${fmt.num(last[0], 1)}, ivme ${fmt.num(last[1], 1)}`)}</title></circle>
          ${on ? `<text x="${x(last[0]) + 8}" y="${y(last[1]) + 4}" class="sl">${esc(short(s.name))}</text>` : ""}</g>`; }).join("")}
    </svg>`;
  }
  const SHORT = { "GAYRİMENKUL YATIRIM ORTAKLIKLARI": "GYO", "HOLDİNGLER VE YATIRIM ŞİRKETLERİ": "Holding", "KİMYA İLAÇ PETROL LASTİK VE PLASTİK ÜRÜNLER": "Kimya-petrol", "METAL EŞYA MAKİNE ELEKTRİKLİ CİHAZLAR VE ULAŞIM ARAÇLARI": "Metal eşya-makine", "GIDA, İÇECEK VE TÜTÜN": "Gıda-içecek", "ELEKTRİK GAZ VE BUHAR": "Elektrik", "TAŞ VE TOPRAĞA DAYALI SANAYİ": "Taş-toprak", "KAĞIT VE KAĞIT ÜRÜNLERİ BASIM": "Kağıt-basım", "YİYECEK VE İÇECEK HİZMETLERİ": "Yiyecek hizm.", "KİRALAMA VE LEASING FAALİYETLERİ": "Kiralama", "TARIM VE HAYVANCILIK AVCILIK VE İLGİLİ HİZMET FAALİYETLERİ": "Tarım-hayvancılık", "SPOR FAALİYETLERİ EĞLENCE VE OYUN FAALİYETLERİ": "Spor-eğlence", "ULAŞTIRMA VE DEPOLAMA": "Ulaştırma", "TEKSTİL, GİYİM EŞYASI VE DERİ": "Tekstil", "İNSAN SAĞLIĞI VE SOSYAL HİZMETLER": "Sağlık", "FİNANSAL KİRALAMA VE FAKTORİNG ŞİRKETLERİ": "Fin. kiralama", "ORMAN ÜRÜNLERİ VE MOBİLYA": "Orman-mobilya", "VARLIK YÖNETİM ŞİRKETLERİ": "Varlık yön.", "GİRİŞİM SERMAYESİ YATIRIM ORTAKLIKLARI": "GSYO" };
  const short = n => { if (SHORT[n]) return SHORT[n]; let w = n.split(/\s+/); if (n.length > 18) { w = w.slice(0, 2); if (["VE", "İLE", ","].includes(w.at(-1))) w = w.slice(0, 1); }
    return w.join(" ").replace(/,$/, "").toLocaleLowerCase("tr").replace(/(^|\s)\S/g, c => c.toLocaleUpperCase("tr")); };

  function tabSector() {
    const d = S.doc, secs = [...d.sectors];
    const key = { rank: s => s.rank, name: s => s.name, ret: s => -(s.med[S.per] ?? -9), br: s => -(s.br50 ?? -1), vs: s => -(s.vshare ?? 0) }[S.sort] || (s => s.rank);
    secs.sort((a, b) => { const p = key(a), q = key(b); return (p < q ? -1 : p > q ? 1 : 0) * S.sdir; });
    const b1 = d.series.bench, bi = { "1G": 1, "1H": 5, "1A": 21, "3A": 63, "6A": 126, "1Y": 252 }[S.per];
    const xr = S.per === "YBB" ? (() => { const y = d.asof.slice(0, 4), j = d.series.d.findLastIndex(x => x.slice(0, 4) < y); return j >= 0 ? b1.at(-1) / b1[j] - 1 : null; })() : b1.length > bi ? b1.at(-1) / b1.at(-1 - bi) - 1 : null;
    const th = (k, l, tip = "", num = true) => `<th scope="col" class="${num ? "num" : ""}" ${tip ? `data-tip="${esc(tip)}"` : ""}><button type="button" class="th-sort" data-k="${k}">${l}${S.sort === k ? (S.sdir > 0 ? " ↓" : " ↑") : ""}</button></th>`;
    const mv = s => s.rank_prev - s.rank;
    const row = s => `<tr class="${S.selSec === s.name ? "is-sel" : ""}" data-sec="${esc(s.name)}">
      <td class="num"><b>${s.rank}</b> ${mv(s) ? `<small class="${mv(s) > 0 ? "up" : "down"}">${mv(s) > 0 ? "▲" : "▼"}${Math.abs(mv(s))}</small>` : ""}</td>
      <td><b>${esc(s.name)}</b><span class="t3 ok-sub">${s.n} hisse</span></td>
      <td class="num"><span class="gc-score" style="--v:${s.score}">${s.score}</span></td>
      <td><span class="gc-q" style="--c:${QUAD[s.quad][1]}">${QUAD[s.quad][0]}</span>${s.quad_prev !== s.quad ? `<span class="t3 ok-sub">önceki hafta ${QUAD[s.quad_prev][0]}</span>` : ""}</td>
      <td class="num ${sgn(s.med[S.per])}">${pc(s.med[S.per])}<span class="t3 ok-sub ${sgn(s.med[S.per] - xr)}">XU100'e ${pc(s.med[S.per] == null || xr == null ? null : s.med[S.per] - xr)}</span></td>
      <td class="num">${pp(s.br50)}${s.br50_prev != null ? `<span class="t3 ok-sub">1 hafta önce ${pp(s.br50_prev)}</span>` : ""}</td>
      <td class="num ${s.vshare > 1.1 ? "up" : s.vshare < 0.9 ? "down" : ""}">${s.vshare == null ? "—" : `×${fmt.num(s.vshare, 2)}`}<span class="t3 ok-sub">pay ${pp(s.share, 1)}</span></td>
      <td class="gc-lead">${s.leaders.slice(0, 3).map(c => `<button type="button" class="link-btn mono" data-tk="${c}">${c}</button>`).join(" ")}</td></tr>`;
    return `<div class="fa-two gc-sec-top">
      <section class="card" aria-labelledby="gcRrgT"><div class="card-head"><h2 class="card-title" id="gcRrgT">Rotasyon grafiği</h2><span class="card-meta">haftalık · ${S.selSec ? esc(short(S.selSec)) : "ilk 6, lider ve bölge değiştirenler"} · ${d.sectors[0]?.tail.length || 8} hafta izi</span></div>
        ${rrgChart(d.sectors)}
        <p class="t3 gc-foot">Yatay: sektörün eşit ağırlıklı endeksinin XU100'e oranı, kendi 10 haftalık ortalamasına göre (100 üstü = endeksten güçlü). Dikey: bu oranın 4 haftalık değişimi (100 üstü = güçleniyor). Sektörler genelde saat yönünde döner: İyileşen → Lider → Zayıflayan → Geride. İyileşen'den Lider'e geçiş en erken rotasyon işaretidir. RRG benzeri, kendi formülümüz.</p></section>
      <section class="card" aria-labelledby="gcQT"><div class="card-head"><h2 class="card-title" id="gcQT">Bölgelere göre</h2><span class="card-meta">noktaya ya da satıra tıkla</span></div>
        ${["lider", "iyilesen", "zayif", "geride"].map(q => { const xs = d.sectors.filter(s => s.quad === q); return `<div class="gc-qbox"><p class="d-sub"><span class="gc-q" style="--c:${QUAD[q][1]}">${QUAD[q][0]}</span> ${xs.length}</p><div class="gc-chips">${xs.map(s => `<button type="button" class="chip" aria-pressed="${S.selSec === s.name}" data-sec="${esc(s.name)}">${esc(short(s.name))}${s.quad_prev !== s.quad ? " •" : ""}</button>`).join("") || `<span class="t3">—</span>`}</div></div>`; }).join("")}
        <p class="t3 gc-foot">• bu hafta bölge değiştirdi.</p></section></div>
      <section class="card card-flush" aria-labelledby="gcSecT"><div class="card-head"><h2 class="card-title" id="gcSecT">Sektör skoru</h2>${seg("gcPer", Object.fromEntries(PERS.map(p => [p, p])), S.per, "Getiri dönemi")}</div>
        <div class="tbl-scroll"><table class="tx ok-tbl gc-tbl"><thead><tr>${th("rank", "Sıra", "Sektör skoruna göre; ok bir hafta öncesine göre değişim")}${th("name", "Sektör", "", false)}
          <th scope="col" class="num" data-tip="0–100: 3 aylık medyan getiri (%25), göreli güç oranı (%25), ivme (%20), 50 günlük ortalama üstü hisse oranı (%15), piyasa hacmindeki payın artışı (%15) sıralarının ağırlıklı ortalaması">Skor</th>
          <th scope="col">Bölge</th>${th("ret", `Medyan ${S.per}`, "Sektördeki hisselerin medyan getirisi ve XU100'e farkı")}${th("br", "Genişlik", "Sektörde 50 günlük ortalamasının üstündeki hisse oranı")}
          ${th("vs", "Hacim akışı", "Sektörün BIST toplam TL hacmindeki payı: son 20 gün / son 60 gün. 1,1 üstü para girişi, 0,9 altı çıkış.")}<th scope="col">Göreli gücü en yüksek</th></tr></thead>
          <tbody>${secs.map(row).join("")}</tbody></table></div>
        <p class="t3 gc-foot">KAP alt sektörleri; en az ${3} işlem gören hisse. Sektör endeksi eşit ağırlıklı (her hisse aynı ağırlık), bölünme/bedelsiz düzeltilmiş; nakit temettü dahil değil.</p></section>`;
  }

  // ─────────────────────────────── 3. hisse
  function tabStocks() {
    const d = S.doc, F = S.hs;
    const okQ = new Set(["lider", "iyilesen"]);
    const q = sh.compact ? sh.compact(F.q) : F.q.toLowerCase();
    let xs = d.stocks.filter(r => (!F.quad || okQ.has(r.quad)) && r.rs >= F.rs && (r.tt ?? 0) >= F.tt && (!F.vol || (r.udv ?? 0) > 1) && (!F.liq || r.liq) && (!F.sec || r.sector === F.sec) && (!q || (sh.match ? sh.match(r.code + " " + r.sector, F.q) : r.code.toLowerCase().includes(q))));
    const key = { rs: r => -r.rs, tt: r => -(r.tt ?? -1), udv: r => -(r.udv ?? 0), hi: r => -(r.hi ?? -9), r1a: r => -(r.r1a ?? -9), r3a: r => -(r.r3a ?? -9), srank: r => r.srank ?? 99, f: r => -(r.f ?? -1), code: r => r.code }[F.sort] || (r => -r.rs);
    xs.sort((a, b) => { const p = key(a), q2 = key(b); return (p < q2 ? -1 : p > q2 ? 1 : 0) * F.sdir || b.rs - a.rs; });
    const TT = ["Fiyat 150 ve 200 günlük ortalamanın üstünde", "150 günlük > 200 günlük", "200 günlük ortalama 1 aydır yükseliyor", "50 günlük > 150 ve 200 günlük", "Fiyat 50 günlüğün üstünde", "52 hafta dibinin en az %30 üstünde", "52 hafta zirvesine %25'ten yakın"];
    const th = (k, l, tip = "", num = true) => `<th scope="col" class="${num ? "num" : ""}" ${tip ? `data-tip="${esc(tip)}"` : ""}><button type="button" class="th-sort" data-hk="${k}">${l}${F.sort === k ? (F.sdir > 0 ? " ↓" : " ↑") : ""}</button></th>`;
    const row = r => `<tr><td><button type="button" class="link-btn mono" data-tk="${r.code}"><b>${r.code}</b></button></td>
      <td>${esc(short(r.sector))}<span class="t3 ok-sub">${r.srank ? `sıra ${r.srank}` : ""}${r.quad ? ` · <span style="color:${QUAD[r.quad][1]}">${QUAD[r.quad][0]}</span>` : ""}</span></td>
      <td class="num"><span class="gc-score" style="--v:${r.rs}">${r.rs}</span></td>
      <td class="num">${r.tt == null ? "—" : `<span class="gc-tt" data-tip="${esc(r.tti.map((ok, i) => `${ok ? "✓" : "✗"} ${TT[i]}`).join("<br>"))}">${r.tti.map(ok => `<i class="${ok ? "on" : ""}"></i>`).join("")}</span> ${r.tt}/7`}</td>
      <td class="num ${r.udv > 1.2 ? "up" : r.udv < 0.8 ? "down" : ""}">${r.udv == null ? "—" : fmt.num(r.udv, 2)}</td>
      <td class="num">${pc(r.hi)}</td><td class="num ${sgn(r.r1a)}">${pc(r.r1a)}</td><td class="num ${sgn(r.r3a)}">${pc(r.r3a)}</td>
      <td class="num">${r.f ?? "—"}${r.grade ? `<span class="t3 ok-sub">not ${esc(r.grade)}</span>` : ""}</td>
      <td class="num t3">${r.tv ? fmt.num(r.tv / 1e6, 0) : "—"}</td></tr>`;
    const secs = [...new Set(d.stocks.map(r => r.sector))].sort((a, b) => a.localeCompare(b, "tr"));
    return `<section class="card" aria-labelledby="gcHsT"><div class="card-head"><h2 class="card-title" id="gcHsT">Güçlü sektörlerin güçlü hisseleri</h2><span class="card-meta">${fmt.int(xs.length)} / ${fmt.int(d.stocks.length)} hisse</span></div>
      <div class="toolbar ok-tb">
        <button type="button" class="chip" id="gcHQ" aria-pressed="${F.quad}" data-tip="Yalnız rotasyon grafiğinde Lider ya da İyileşen bölgedeki sektörler"><svg class="ck" viewBox="0 0 12 12"><path d="M2.5 6.2 5 8.5l4.5-5" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>Lider / iyileşen sektör</button>
        <label class="gc-lbl">Göreli güç ≥ ${seg("gcHR", { 0: "Tümü", 70: "70", 80: "80", 90: "90" }, F.rs, "Göreli güç alt sınırı")}</label>
        <label class="gc-lbl">Trend şablonu ≥ ${seg("gcHT", { 0: "Tümü", 5: "5", 6: "6", 7: "7" }, F.tt, "Trend şablonu alt sınırı")}</label>
        <button type="button" class="chip" id="gcHV" aria-pressed="${F.vol}" data-tip="Son 50 günde yükselen günlerin hacmi düşen günlerinkinden fazla (birikim)"><svg class="ck" viewBox="0 0 12 12"><path d="M2.5 6.2 5 8.5l4.5-5" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>Hacim teyidi</button>
        <button type="button" class="chip" id="gcHL" aria-pressed="${F.liq}" data-tip="Son 20 günün medyan işlem hacmi ≥ ${fmt.num(d.liq_tl / 1e6, 0)} milyon TL"><svg class="ck" viewBox="0 0 12 12"><path d="M2.5 6.2 5 8.5l4.5-5" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>Likit</button>
        <select id="gcHS" class="fa-select" aria-label="Sektör"><option value="">Tüm sektörler</option>${secs.map(s => `<option ${F.sec === s ? "selected" : ""}>${esc(s)}</option>`).join("")}</select>
        <label class="search"><svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="9" cy="9" r="5.5" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="m13.5 13.5 3 3" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg><input id="gcHQs" type="search" placeholder="Hisse ara" value="${esc(F.q)}" aria-label="Hisse ara"></label>
      </div>
      ${xs.length ? `<div class="tbl-scroll"><table class="tx ok-tbl gc-tbl"><thead><tr>${th("code", "Hisse", "", false)}${th("srank", "Sektör", "Sektör skoru sırası ve rotasyon bölgesi", false)}
        ${th("rs", "Göreli güç", "1–99: 3 aylık getiri %40, 6, 9 ve 12 aylık getiri %20'şer ağırlıkla; BIST Tüm içinde yüzdelik sıra (IBD yöntemi)")}
        ${th("tt", "Trend şablonu", "Minervini trend şablonunun 7 fiyat maddesi; üzerine gelince maddeler")}
        ${th("udv", "Yük./düş. hacim", "Son 50 günde yükselen günlerin TL hacmi / düşen günlerin TL hacmi. 1 üstü birikim.")}
        ${th("hi", "52H zirveye", "52 haftalık zirveye uzaklık")}${th("r1a", "1A")}${th("r3a", "3A")}${th("f", "F-skoru", "Piotroski F-skoru (0–9) ve temel analiz notu")}
        <th scope="col" class="num" data-tip="Son 20 günün medyan günlük işlem hacmi, milyon TL">Hacim</th></tr></thead>
        <tbody>${xs.slice(0, F.limit).map(row).join("")}</tbody></table></div>${xs.length > F.limit ? `<div class="gc-more"><button type="button" class="btn" id="gcHMore">${fmt.int(Math.min(60, xs.length - F.limit))} hisse daha</button></div>` : ""}`
      : sh.stateHTML({ kind: "empty", title: "Bu süzgeçle hisse yok", msg: d.regime.state === "ayi" || d.regime.state === "dip" ? "Zayıf piyasada trend şablonuna uyan hisse az olur; eşikleri gevşetmeyi dene." : "" })}
      <p class="t3 gc-foot">Göreli güç ve trend şablonu fiyat temelli göstergelerdir; tek başına alım-satım kuralı değildir. Yöntem Karnesi'ne göre BIST'te 12-1 ay momentum tek başına zayıf (t 1,7), kısa vadeli devam etkisi daha güçlü; bu listenin geçmiş başarısı ayrıca test edilecek.</p></section>`;
  }

  // ─────────────────────────────── ısı haritası, değerleme, küresel (market.js)
  const MK = () => window.radarMarket;
  function tabMap() {
    const secs = [...new Set(S.doc.stocks.filter(r => r.mcap).map(r => r.sector))].sort((a, b) => a.localeCompare(b, "tr"));
    return `<section class="card" aria-labelledby="gcTmT"><div class="card-head"><h2 class="card-title" id="gcTmT">BIST ısı haritası</h2>
        <span class="card-meta">kutu büyüklüğü ${S.tmSize === "tv" ? "günlük işlem hacmi" : "piyasa değeri"} · renk getiri · kutuya tıkla: hisse paneli</span></div>
      <div class="toolbar ok-tb">${seg("gcTmP", Object.fromEntries(Object.entries(MK().PERK).map(([k, v]) => [k, v[0]])), S.tmPer, "Dönem")}
        ${seg("gcTmZ", { mcap: "Piyasa değeri", tv: "İşlem hacmi" }, S.tmSize, "Kutu boyutu")}
        <select id="gcTmS" class="fa-select" aria-label="Sektör"><option value="">Tüm sektörler</option>${secs.map(x => `<option ${S.tmSec === x ? "selected" : ""} value="${esc(x)}">${esc(MK().short(x))}</option>`).join("")}</select>
        <span class="grow"></span>${MK().legend(S.tmPer)}</div>
      <div id="gcTm" class="tm-box"></div>
      <p class="t3 gc-foot">${dlab(S.doc.asof)} kapanışı. Piyasa değeri son fiyat × ödenmiş sermaye (aynı şirketin ikincil pay sınıfları hariç); işlem hacmi son 20 günün günlük medyanı. Sektör başlığındaki getiri piyasa değeriyle ağırlıklı. Gri kutu: değişim yok (±%0,05).</p></section>`;
  }
  function tabValue() {
    return `<section class="card card-flush" aria-labelledby="gcVT"><div class="card-head"><h2 class="card-title" id="gcVT">Endeks ve sektör değerlemesi</h2>
        ${seg("gcVK", { endeks: "Endeksler", sektor: "Sektörler" }, S.vKind, "Grup")}</div>
      ${S.vKind === "sektor" ? `<div class="toolbar ok-tb" style="padding:0 var(--s-4)">Sırala ${seg("gcVS", { mcap: "Piyasa değeri", roe: "Kârlılık", pe: "F/K", pb: "PD/DD" }, S.vSort, "Sıralama")}</div>` : ""}
      ${MK().valuationTable(S.vKind, S.vSort)}
      <p class="t3 gc-foot" style="padding:0 var(--s-4) var(--s-3)">KAP mali tabloları (son dönem, son 12 ay) ve son kapanış · dolar karşılığı ${S.doc.usdtry ? `USD/TRY ${fmt.num(S.doc.usdtry, 4)}` : "—"}. F/K, PD/DD ve kârlılık şirket değerlerinin ortalaması değil, toplamların oranıdır (endeksin bütün olarak çarpanı). Dönem değişimi bugünkü pay sayısıyla, fiyat getirilerinden geriye hesaplanır. Halka açık piyasa değeri MKK verisi gerektirdiği için yok.</p></section>`;
  }
  function tabGlobal() {
    const x = MK().data.cross;
    return `${MK().stripHTML() || ""}${MK().crossCard(false) || `<p class="t3">Küresel rejim henüz hesaplanmadı (hafta içi akşam çalışır).</p>`}
      ${x?.score_hist?.length ? `<section class="card" aria-labelledby="gcXH"><div class="card-head"><h2 class="card-title" id="gcXH">Risk iştahı puanı · son 3 yıl</h2><span class="card-meta">haftalık · ±0,5 eşikleri</span></div>
        ${chart(x.score_hist.map(p => p[0]), [{ v: x.score_hist.map(p => p[1]), kind: "bar" }], { zero: true, h: 200, bands: [{ v: 0.5, l: "yüksek" }, { v: -0.5, l: "düşük" }], fmtY: v => fmt.num(v, 1), title: "risk iştahı" })}</section>` : ""}`;
  }

  // ─────────────────────────────── görünüm
  function render() {
    const d = S.doc;
    $("#gcBody").innerHTML = `<div class="toolbar">${seg("gcTab", TABS, S.tab, "Bölüm")}<span class="grow"></span><span class="card-meta">${dlab(d.asof)} kapanışı · ${fmt.int(d.universe)} hisse</span></div>
      ${S.tab === "sektor" ? tabSector() : S.tab === "hisse" ? tabStocks() : S.tab === "harita" ? tabMap() : S.tab === "deger" ? tabValue() : S.tab === "kuresel" ? tabGlobal() : tabBreadth()}
      <p class="m-foot">${window.radarMethod?.link("piyasa-gucu") || ""}</p>
      <p class="src-line">Kaynak: Yahoo Finance günlük kapanış ve hacim (kişisel kullanım; ham fiyat yayımlanmaz), KAP sektör sınıflaması · ${fmt.date(d.generated, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</p>`;
    bind();
  }
  function bind() {
    const segB = (id, f) => { $$(`#${id} button`).forEach(b => b.onclick = () => { f(b.dataset.v); render(); }); $(`#${id}`) && sh.radioKeys($(`#${id}`)); };
    segB("gcTab", v => { S.tab = v; sh.go("piyasa-gucu", { param: v }); });
    segB("gcTmP", v => { S.tmPer = v; });
    segB("gcTmZ", v => { S.tmSize = v; });
    segB("gcVK", v => { S.vKind = v; });
    segB("gcVS", v => { S.vSort = v; });
    $("#gcTmS")?.addEventListener("change", e => { S.tmSec = e.target.value; render(); });
    if (S.tab === "harita") MK()?.load().then(() => MK().treemap($("#gcTm"), { per: S.tmPer, size: S.tmSize, sector: S.tmSec || null, height: S.tmSec ? 420 : Math.max(420, Math.min(720, innerWidth * 0.5)) }));
    segB("gcRange", v => { S.range = +v; });
    segB("gcPer", v => { S.per = v; });
    segB("gcHR", v => { S.hs.rs = +v; S.hs.limit = 60; });
    segB("gcHT", v => { S.hs.tt = +v; S.hs.limit = 60; });
    const body = $("#gcBody");
    $$("[data-k]", body).forEach(b => b.onclick = () => { const k = b.dataset.k; S.sdir = S.sort === k ? -S.sdir : 1; S.sort = k; render(); });
    $$("[data-hk]", body).forEach(b => b.onclick = () => { const k = b.dataset.hk; S.hs.sdir = S.hs.sort === k ? -S.hs.sdir : 1; S.hs.sort = k; render(); });
    $$("[data-sec]", body).forEach(el => el.onclick = e => { if (e.target.closest("[data-tk]")) return; const n = el.dataset.sec; S.selSec = S.selSec === n ? null : n; render(); });
    $$("[data-tk]", body).forEach(b => b.onclick = e => { e.stopPropagation(); window.radar?.openTicker?.(b.dataset.tk, b); });
    const tog = (id, k) => { const b = $(id); if (b) b.onclick = () => { S.hs[k] = !S.hs[k]; S.hs.limit = 60; render(); }; };
    tog("#gcHQ", "quad"); tog("#gcHV", "vol"); tog("#gcHL", "liq");
    $("#gcHS")?.addEventListener("change", e => { S.hs.sec = e.target.value; S.hs.limit = 60; render(); });
    const qs = $("#gcHQs"); if (qs) { let t; qs.oninput = () => { clearTimeout(t); t = setTimeout(() => { S.hs.q = qs.value; render(); const n = $("#gcHQs"); n.focus(); n.setSelectionRange(n.value.length, n.value.length); }, 250); }; }
    $("#gcHMore")?.addEventListener("click", () => { S.hs.limit += 60; render(); });
    // sektör seçiliyken hisse sekmesine geç
    if (S.tab === "sektor" && S.selSec) {
      const b = document.createElement("button"); b.type = "button"; b.className = "btn gc-go"; b.textContent = `${short(S.selSec)} hisselerini göster →`;
      b.onclick = () => { S.hs.sec = S.selSec; S.hs.quad = false; S.tab = "hisse"; sh.go("piyasa-gucu", { param: "hisse" }); render(); };
      $("#gcRrgT")?.parentElement.append(b);
    }
  }

  function exportCSV() {
    const ex = window.radarExport, d = S.doc;
    if (S.tab === "hisse") ex.download(`guclu_hisseler_${ex.stamp()}.csv`, ex.toCSV(d.stocks.map(r => ({ hisse: r.code, sektor: r.sector, sektor_sira: r.srank, bolge: r.quad, goreli_guc: r.rs, trend_sablonu: r.tt, yuk_dus_hacim: r.udv, zirveye: r.hi, getiri_1a: r.r1a, getiri_3a: r.r3a, f_skoru: r.f, hacim_tl: r.tv }))), "text/csv;charset=utf-8");
    else if (S.tab === "sektor") ex.download(`sektor_skoru_${ex.stamp()}.csv`, ex.toCSV(d.sectors.map(s => ({ sira: s.rank, sektor: s.name, hisse: s.n, skor: s.score, bolge: s.quad, oran: s.ratio, ivme: s.mom, genislik50: s.br50, hacim_akisi: s.vshare, ...Object.fromEntries(PERS.map(p => ["medyan_" + p, s.med[p]])) }))), "text/csv;charset=utf-8");
    else { const s = d.series; ex.download(`bist_genislik_${ex.stamp()}.csv`, ex.toCSV(s.d.map((dd, i) => ({ tarih: dd, xu100: s.bench[i], ust20: s.p20[i], ust50: s.p50[i], ust200: s.p200[i], yeni_zirve: s.nh[i], yeni_dip: s.nl[i], yukselen: s.adv[i], dusen: s.dec[i], mcclellan: s.mco[i], yukselen_hacim: s.upv[i] }))), "text/csv;charset=utf-8"); }
  }

  addEventListener("radar:market", () => { if (sh.route === "piyasa-gucu" && S.loaded && ["harita", "deger", "kuresel"].includes(S.tab)) render(); });
  let rz; addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(() => { if (sh.route === "piyasa-gucu" && S.tab === "harita") render(); }, 250); });
  window.radarGuc = { card: () => S.loaded ? regimeCard(true) : (load(), "") };
  sh.register("piyasa-gucu", {
    onShow() { if (TABS[sh.param]) S.tab = sh.param; S.loaded ? render() : S.error ? renderError() : load(); },
    async refresh() { await load(true); },
    exports: () => [{ label: `${TABS[S.tab]} (CSV)`, hint: "seçili bölüm", run: exportCSV, disabled: !S.loaded }],
    exportNote: "Piyasa gücü henüz yüklenmedi",
  });
})();
