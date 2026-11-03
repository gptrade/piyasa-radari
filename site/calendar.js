/* Lyra Radar — Takvim sekmesi (katalizörler).
   Veri: data/calendar.json (pipeline: TÜİK Ulusal Veri Yayımlama Takvimi + config/calendar.yml makro takvim
   + hesaplanan vade sonları + KAP/Yahoo bilanço/temettü).
   Görünümler: Hafta (iş günü sütunları), Ay (ızgara), Liste (gün gün). Olaya tıklayınca ayrıntı penceresi. */
(() => {
  "use strict";
  const sh = window.shell;
  const { $, $$, esc, fmt, store } = sh;
  const DAY = 86400000;
  const KIND = {
    cb: { l: "Merkez bankası", s: "MB" }, macro: { l: "Makro veri", s: "Veri" }, data: { l: "Diğer resmi veri", s: "Veri" },
    report: { l: "Rapor", s: "Rapor" }, earnings: { l: "Bilanço", s: "Bilanço" }, agm: { l: "Genel kurul", s: "GK" },
    dividend: { l: "Temettü", s: "Temettü" }, expiry: { l: "Vade sonu", s: "Vade" },
  };
  const RANGE = { 14: "2 hafta", 30: "1 ay", 60: "2 ay" };
  const VIEWS = { week: "Hafta", month: "Ay", list: "Liste" };
  const REGIONS = { TR: "Türkiye", US: "ABD", EU: "Avrupa", UK: "İngiltere", JP: "Japonya" };
  const RTAG = { US: "ABD", EU: "AB", UK: "UK", JP: "JP" };
  const SESSION = { bmo: "açılış öncesi", amc: "kapanış sonrası" };
  const WD = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"];
  const S = { cal: null, loaded: false, error: null, kinds: new Set(store.get("radar.calKinds", [])),
    regions: new Set(store.get("radar.calRegions", [])),
    days: store.get("radar.calDays", 30), important: store.get("radar.calImp", false),
    view: store.get("radar.calView", "week"), anchor: null, idx: [] };
  if (!VIEWS[S.view]) S.view = "week";

  async function load() {
    try {
      const r = await fetch(`data/calendar.json?t=${Date.now()}`);
      if (!r.ok) throw new Error(`data/calendar.json okunamadı (HTTP ${r.status})`);
      S.cal = await r.json(); S.error = null;
    } catch (e) { S.error = e; }
    try { const r = await fetch(`data/surprise.json?t=${Date.now()}`); S.sur = r.ok ? await r.json() : null; } catch { S.sur = null; }
    S.loaded = true;
    if (S.cal) sh.setUpdated("takvim", S.cal.generated, { label: "Takvim güncellendi", staleMin: 180 });
    badge();
    if (sh.route === "takvim") render();
  }

  // ── tarih yardımcıları (ISO YYYY-MM-DD, UTC öğlen üzerinden: saat dilimi kayması olmasın)
  const istDate = d => new Date(d).toLocaleDateString("en-CA", { timeZone: "Europe/Istanbul" });
  const todayISO = () => istDate(Date.now());
  const D = iso => new Date(iso + "T12:00:00Z");
  const addDays = (iso, n) => new Date(D(iso).getTime() + n * DAY).toISOString().slice(0, 10);
  const monday = iso => addDays(iso, -((D(iso).getUTCDay() + 6) % 7));
  const daysTo = iso => Math.round((D(iso) - D(todayISO())) / DAY);
  const dLabel = (iso, o) => D(iso).toLocaleDateString("tr-TR", { timeZone: "UTC", ...o });

  // Üstteki piyasa seçimi (BIST/ABD) yalnız piyasaya ait olaylara uygulanır: bilanço, temettü, genel kurul/rapor, vade sonu.
  // Makro veri ve merkez bankası kararları piyasa seçiminden bağımsızdır (Fed kararı BIST için de önemli); onları
  // takvimin kendi "Bölge" süzgeci daraltır. Eskiden BoE/BoJ "ALL" işaretli olduğu için kalıyor, Fed ve ECB kayboluyordu.
  const MARKET_KINDS = new Set(["earnings", "dividend", "report", "expiry"]);
  const inMarket = e => sh.market === "ALL" || !MARKET_KINDS.has(e.kind) || e.market === "ALL" || e.market === sh.market;
  const regionOf = e => e.region || ({ BIST: "TR", US: "US", EU: "EU" })[e.market] || "TR";
  // "Benimkiler" açıkken şirket olayları (bilanço, temettü, genel kurul) yalnız izleme listesi + portföy hisseleri; makro olaylar kalır
  const mineOk = e => !sh.mine || !e.ticker || sh.mineSet().has(e.ticker);
  const passes = e => inMarket(e) && mineOk(e) && (!S.kinds.size || S.kinds.has(e.kind)) && (!S.regions.size || S.regions.has(regionOf(e)))
    && (!S.important || e.importance >= 3);
  // Düşük önemli bilançolar (S&P 500'ün geri kalanı) gün ve bölge başına tek kutuda toplanır
  function grouped(list) {
    const keep = [], bucket = new Map();
    for (const e of list) {
      if (e.kind === "earnings" && e.importance <= 1 && !e.members) {
        const k = e.date + "|" + regionOf(e);
        (bucket.get(k) || bucket.set(k, []).get(k)).push(e);
      } else keep.push(e);
    }
    for (const [, items] of bucket) {
      if (items.length < 3) { keep.push(...items); continue; }
      const r = regionOf(items[0]);
      keep.push({ kind: "earnings", importance: 1, date: items[0].date, when: items[0].date + "T23:59", timed: false,
        market: items[0].market, region: r, title: `${r === "US" ? "S&P 500" : REGIONS[r]} bilançoları`, count: items.length,
        members: items.sort((a, b) => (a.ticker || "").localeCompare(b.ticker || "")) });
    }
    return keep;
  }
  function visible() {
    const lim = todayISO(), hi = addDays(lim, S.days);
    return (S.cal?.events || []).filter(e => passes(e) && e.date >= lim && e.date <= hi);
  }
  function between(lo, hi) { return (S.cal?.events || []).filter(e => passes(e) && e.date >= lo && e.date <= hi); }
  const covered = (lo, hi) => { const r = S.cal?.range || []; return r.length === 2 && hi >= r[0] && lo <= r[1]; };

  function rel(n) { return n === 0 ? "bugün" : n === 1 ? "yarın" : n === -1 ? "dün" : n < 0 ? `${-n} gün önce` : `${n} gün sonra`; }
  function dayHead(iso) {
    const n = daysTo(iso);
    return `<span class="cal-day-name">${esc(dLabel(iso, { weekday: "long", day: "numeric", month: "long" }))}</span><span class="cal-rel${n >= 0 && n <= 1 ? " soon" : ""}">${rel(n)}</span>`;
  }
  const hm = e => new Date(e.when).toLocaleTimeString("tr-TR", { timeZone: "Europe/Istanbul", hour: "2-digit", minute: "2-digit" });
  const timeOf = e => e.timed ? hm(e) : SESSION[e.session] || (["earnings", "dividend", "agm"].includes(e.kind) ? "—" : "gün boyu");
  const imp = n => `<span class="meter" data-l="${n}" role="img" aria-label="Önem ${n === 3 ? "yüksek" : n === 2 ? "orta" : "düşük"}"><i></i><i></i><i></i></span>`;
  const mk = m => m === "ALL" ? "" : `<span class="tag mk">${m === "US" ? "ABD" : m === "EU" ? "Avrupa" : m}</span>`;
  const shortTitle = e => e.title.split(" · ")[0];
  const reg = e => { S.idx.push(e); return S.idx.length - 1; };

  function chip(e, { time = true } = {}) {
    const lbl = e.members ? `${e.title} · ${e.count}` : shortTitle(e);
    const x = cpiTag(e);
    return `<li><button type="button" class="cal-chip k-${e.kind} i${e.importance}${x ? " has-x" : ""}" data-i="${reg(e)}"
      aria-label="${esc(`${e.timed ? hm(e) + " " : ""}${e.title}, ${KIND[e.kind]?.l || e.kind}, önem ${e.importance}`)}">
      ${time && e.timed ? `<span class="cal-chip-t">${hm(e)}</span>` : ""}<span class="cal-chip-n">${esc(lbl)}</span>${RTAG[regionOf(e)] ? `<span class="cal-chip-m">${RTAG[regionOf(e)]}</span>` : ""}${x}</button></li>`;
  }

  // ── TÜFE sürprizi (data/surprise.json): gerçekleşen − TCMB Piyasa Katılımcıları Anketi cari ay beklentisi
  const pp = (v, d = 2) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${fmt.num(Math.abs(v), d)}`;
  const AYL = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"];
  const ymLabel = ym => `${AYL[+ym.slice(5, 7) - 1]} ${ym.slice(0, 4)}`;
  function cpiInfo(e) {
    if (e.key !== "tufe" || !S.sur || !e.period) return null;
    const r = (S.sur.rows || []).find(x => ymLabel(x.m) === e.period);
    if (r) return { done: true, ...r };
    const p = S.sur.pending;
    return p && p.label === e.period ? { done: false, ...p } : null;
  }
  function cpiTag(e) {
    const c = cpiInfo(e); if (!c) return "";
    return c.done ? `<span class="cal-chip-x ${c.sur >= S.sur.band ? "down" : c.sur <= -S.sur.band ? "up" : ""}">%${fmt.num(c.act, 2)} · bkl. %${fmt.num(c.exp, 2)}</span>`
      : `<span class="cal-chip-x">bkl. %${fmt.num(c.exp, 2)}</span>`;
  }
  function cpiBox(e) {
    const c = cpiInfo(e); if (!c) return "";
    const b = S.sur.band;
    return `<div class="cal-dlg-box"><span class="k-lbl">TCMB Piyasa Katılımcıları Anketi</span>
      ${c.done ? `<b>Gerçekleşen aylık %${fmt.num(c.act, 2)} · beklenti %${fmt.num(c.exp, 2)} · sürpriz <span class="${c.sur >= b ? "down" : c.sur <= -b ? "up" : ""}">${pp(c.sur)} puan</span></b>
        ${c.xb != null || c.xu != null ? `<span class="k-note">Açıklama günü: ${c.xu != null ? `BIST 100 ${fmt.pct(c.xu, 1)}` : ""}${c.xu != null && c.xb != null ? " · " : ""}${c.xb != null ? `Banka endeksi ${fmt.pct(c.xb, 1)}` : ""}</span>` : ""}`
        : `<b>Aylık TÜFE beklentisi %${fmt.num(c.exp, 2)}</b><span class="k-note">${esc(c.src === "anket" ? "Bu ayın anketi" : "Bu ayın anketi henüz yok; önceki anketin 1 ay sonrası beklentisi")} · ±${fmt.num(b, 2)} puan dışı "belirgin sürpriz" sayılır</span>`}</div>`;
  }
  function surpriseCard() {
    const d = S.sur; if (!d?.rows?.length) return "";
    const rows = d.rows.slice(-48), b = d.band, last = d.rows[d.rows.length - 1], p = d.pending, w = d.stats?.w12;
    const W = 720, H = 210, P = { l: 34, r: 8, t: 12, b: 26 }, LIM = 2;
    const X = i => P.l + (W - P.l - P.r) * (i + 0.5) / rows.length, bw = Math.max(3, (W - P.l - P.r) / rows.length - 3);
    const Y = v => P.t + (H - P.t - P.b) * (LIM - Math.max(-LIM, Math.min(LIM, v))) / (2 * LIM);
    const col = v => v >= b ? "var(--down)" : v <= -b ? "var(--up)" : "var(--text-3)";
    const bars = `<svg class="sp-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Son ${rows.length} ay TÜFE sürprizi">
      <rect x="${P.l}" width="${W - P.l - P.r}" y="${Y(b)}" height="${Y(-b) - Y(b)}" class="sp-band"/>
      ${[-2, -1, 0, 1, 2].map(v => `<line x1="${P.l}" x2="${W - P.r}" y1="${Y(v)}" y2="${Y(v)}" class="${v ? "g" : "z"}"/><text x="${P.l - 5}" y="${Y(v) + 3.5}" text-anchor="end">${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v)}</text>`).join("")}
      ${rows.map((r, i) => { const y0 = Y(0), y1 = Y(r.sur), cl = Math.abs(r.sur) > LIM; return `<rect class="sp-bar" x="${(X(i) - bw / 2).toFixed(1)}" width="${bw.toFixed(1)}" y="${Math.min(y0, y1).toFixed(1)}" height="${Math.max(1, Math.abs(y1 - y0)).toFixed(1)}" fill="${col(r.sur)}"><title>${esc(`${ymLabel(r.m)}: gerçekleşen %${fmt.num(r.act, 2)}, beklenti %${fmt.num(r.exp, 2)} → ${pp(r.sur)} puan${r.xb != null ? ` · banka endeksi o gün ${fmt.pct(r.xb, 1)}` : ""}`)}</title></rect>${cl ? `<text x="${X(i)}" y="${r.sur > 0 ? P.t + 9 : H - P.b - 3}" text-anchor="middle" class="sp-clip">▲</text>` : ""}`; }).join("")}
      ${rows.map((r, i) => r.m.endsWith("-01") ? `<text x="${X(i)}" y="${H - 8}" text-anchor="middle">${r.m.slice(0, 4)}</text>` : "").join("")}
    </svg>`;
    // sürpriz ↔ açıklama günü banka endeksi
    const rx = d.react?.xb || d.react?.xu, rk = d.react?.xb ? "xb" : "xu", rname = rk === "xb" ? "Banka endeksi" : "BIST 100";
    let sc = "";
    if (rx) {
      const pts = d.rows.filter(r => r[rk] != null), C = d.clip || 1.5, SW = 300, SH = 222, Q = { l: 34, r: 8, t: 12, b: 38 }, YL = 7;
      const sx = v => Q.l + (SW - Q.l - Q.r) * (Math.max(-C, Math.min(C, v)) + C) / (2 * C), sy = v => Q.t + (SH - Q.t - Q.b) * (YL - Math.max(-YL, Math.min(YL, v))) / (2 * YL);
      const o = rx.ols_recent || rx.ols, ma = pts.filter(r => r.m >= rx.recent);
      const my = ma.reduce((a, r) => a + r[rk], 0) / (ma.length || 1), mx = ma.reduce((a, r) => a + Math.max(-C, Math.min(C, r.sur)), 0) / (ma.length || 1);
      sc = `<svg class="sp-svg" viewBox="0 0 ${SW} ${SH}" role="img" aria-label="Sürpriz ve açıklama günü ${rname} getirisi">
        ${[-6, -3, 0, 3, 6].map(v => `<line x1="${Q.l}" x2="${SW - Q.r}" y1="${sy(v)}" y2="${sy(v)}" class="${v ? "g" : "z"}"/><text x="${Q.l - 5}" y="${sy(v) + 3.5}" text-anchor="end">${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v)}</text>`).join("")}
        <line x1="${sx(0)}" x2="${sx(0)}" y1="${Q.t}" y2="${SH - Q.b}" class="z"/>
        ${[-1, 1].map(v => `<text x="${sx(v)}" y="${SH - Q.b + 14}" text-anchor="middle">${v > 0 ? "+" : "−"}1</text>`).join("")}
        ${pts.map(r => `<circle cx="${sx(r.sur).toFixed(1)}" cy="${sy(r[rk]).toFixed(1)}" r="${r.m >= rx.recent ? 3.6 : 2.4}" class="${r.m >= rx.recent ? "sp-pt" : "sp-pt old"}"><title>${esc(`${ymLabel(r.m)}: sürpriz ${pp(r.sur)} puan, ${rname} ${fmt.pct(r[rk], 1)}`)}</title></circle>`).join("")}
        ${o ? `<line class="sp-fit" x1="${sx(-C)}" y1="${sy(my + o.b * (-C - mx))}" x2="${sx(C)}" y2="${sy(my + o.b * (C - mx))}"/>` : ""}
        <text x="${SW - Q.r}" y="${SH - 4}" text-anchor="end" class="ax">sürpriz, puan →</text>
      </svg>`;
    }
    const g = rx?.groups || {}, o = rx?.ols, orc = rx?.ols_recent;
    const verdict = o && orc ? (Math.abs(orc.t) >= 2 ? `2023 ortasından beri anlamlı: 1 puan yukarı sürpriz o gün ortalama ${fmt.pct(orc.b, 1)} (t ${fmt.num(orc.t, 1)}, ${orc.n} ay).`
      : `Günlük tepki zayıf: 1 puan yukarı sürpriz ortalama ${fmt.pct(o.b, 1)} (t ${fmt.num(o.t, 1)}, ${o.n} ay); 2023 ortasından beri ${fmt.pct(orc.b, 1)} (t ${fmt.num(orc.t, 1)}). Tek başına işlem sinyali değil.`) : "";
    return `<section class="card sp-card" aria-labelledby="spT"><div class="card-head"><h2 class="card-title" id="spT">Enflasyon sürprizi</h2>
        <span class="card-meta">aylık TÜFE gerçekleşen − TCMB Piyasa Katılımcıları Anketi beklentisi · yüzde puan</span></div>
      <div class="sp-kpis">
        ${p ? `<div class="sp-k"><span class="k-lbl">Sıradaki · ${esc(p.label)}</span><b>bkl. %${fmt.num(p.exp, 2)}</b><span class="t3">${esc(dLabel(p.rel, { day: "numeric", month: "long", weekday: "short" }))} 10:00 · ${rel(daysTo(p.rel))}</span></div>` : ""}
        <div class="sp-k"><span class="k-lbl">Son · ${esc(ymLabel(last.m))}</span><b class="${last.sur >= b ? "down" : last.sur <= -b ? "up" : ""}">${pp(last.sur)} puan</b><span class="t3">%${fmt.num(last.act, 2)} gerçekleşen · %${fmt.num(last.exp, 2)} beklenti</span></div>
        ${w ? `<div class="sp-k"><span class="k-lbl">Son 12 ay</span><b>${w.above} üstünde · ${w.below} altında</b><span class="t3">ortalama mutlak sapma ${fmt.num(w.mae, 2)} puan</span></div>` : ""}
        ${g.hi && g.lo ? `<div class="sp-k"><span class="k-lbl">${rname} açıklama günü</span><b><span class="down">${fmt.pct(g.hi.mean, 2)}</span> / <span class="up">${fmt.pct(g.lo.mean, 2)}</span></b><span class="t3">beklentiden yüksek (${g.hi.n}) / düşük (${g.lo.n}) aylarda ortalama</span></div>` : ""}
      </div>
      <div class="sp-grid"><div><p class="d-sub">Son ${rows.length} ay</p>${bars}</div>${sc ? `<div><p class="d-sub">Sürpriz ve aynı gün ${rname.toLowerCase()} getirisi (%) · ${pts0(d, rk)} ay</p>${sc}</div>` : ""}</div>
      <p class="t3 gc-foot">Kırmızı: enflasyon beklentiden en az ${fmt.num(b, 2)} puan yüksek; yeşil: düşük; gri bant içi sürpriz sayılmaz. ±2 puan dışı çubuklar kırpılır (▲; 2018 ve 2021–22 kur şokları).
        ${verdict ? esc(verdict) : ""} Noktalar: koyu 2023 ortası sonrası, açık öncesi; çizgi son dönem eğimi. Açıklama günü kuralla (ayın 3'ü, hafta sonuysa pazartesi) belirlenir. Kaynak: TÜİK ve TCMB (EVDS), endeks getirisi Yahoo.</p></section>`;
  }
  const pts0 = (d, k) => d.rows.filter(r => r[k] != null).length;

  // ── önümüzdeki haftaların yoğunluğu (yüksek önemli olaylar türe göre)
  const DGRP = [["cb", "Merkez bankası", ["cb"]], ["macro", "Makro veri", ["macro", "data", "report"]], ["earnings", "Bilanço", ["earnings"]], ["other", "Temettü, vade", ["dividend", "agm", "expiry"]]];
  function density() {
    const start = monday(todayISO()), r = S.cal?.range || [], weeks = [];
    for (let i = 0; i < 8; i++) {
      const mon = addDays(start, 7 * i), sun = addDays(mon, 6);
      if (r[1] && mon > r[1]) break;
      const evs = between(mon, sun).filter(e => e.importance >= 3);
      weeks.push({ mon, n: evs.length, g: DGRP.map(([k, , ks]) => evs.filter(e => ks.includes(e.kind)).length), cb: evs.filter(e => e.kind === "cb").map(e => shortTitle(e).replace(/ faiz kararı.*$/i, "")) });
    }
    if (weeks.length < 2) return "";
    const mx = Math.max(1, ...weeks.map(w => w.n)), cur = monday(S.anchor);
    return `<div class="cal-dens" role="list" aria-label="Önümüzdeki haftalarda yüksek önemli olaylar">${weeks.map(w => `
      <button type="button" role="listitem" class="cal-dw${w.mon === cur ? " on" : ""}" data-week="${w.mon}" aria-label="${esc(`${dLabel(w.mon, { day: "numeric", month: "long" })} haftası: ${w.n} yüksek önemli olay`)}">
        <span class="cal-dw-h">${esc(dLabel(w.mon, { day: "numeric", month: "short" }))}<b>${w.n}</b></span>
        <span class="cal-dw-bar">${w.g.map((n, j) => n ? `<i class="k-${DGRP[j][0]}" style="width:${(n / mx * 100).toFixed(1)}%" title="${esc(`${DGRP[j][1]}: ${n}`)}"></i>` : "").join("")}</span>
        <span class="cal-dw-cb">${w.cb.length ? esc([...new Set(w.cb)].slice(0, 3).join(", ")) : "&nbsp;"}</span></button>`).join("")}</div>`;
  }

  // ── Hafta görünümü
  function navBar(label, sub) {
    return `<div class="cal-nav">
      <div class="cal-nav-btns">
        <button type="button" class="btn btn-sm" data-nav="-1" aria-label="Önceki ${S.view === "month" ? "ay" : "hafta"}">‹ Önceki</button>
        <button type="button" class="btn btn-sm" data-nav="0">Bugün</button>
        <button type="button" class="btn btn-sm" data-nav="1" aria-label="Sonraki ${S.view === "month" ? "ay" : "hafta"}">Sonraki ›</button>
      </div>
      <h3 class="cal-nav-h">${esc(label)}${sub ? ` <span class="cal-nav-sub">${esc(sub)}</span>` : ""}</h3>
      <label class="cal-pick"><span class="sr-only">Tarih seç</span><input type="date" id="calPick" value="${S.anchor}"></label>
    </div>`;
  }
  function renderWeek() {
    const mon = monday(S.anchor), sun = addDays(mon, 6), t = todayISO();
    const evs = between(mon, sun);
    const days = [...Array(7)].map((_, i) => addDays(mon, i)).filter((d, i) => i < 5 || evs.some(e => e.date === d));
    const label = `${dLabel(mon, { day: "numeric", month: D(mon).getUTCMonth() === D(addDays(mon, 4)).getUTCMonth() ? undefined : "long" })}–${dLabel(addDays(mon, 4), { day: "numeric", month: "long", year: "numeric" })}`;
    const cols = days.map(d => {
      const list = grouped(evs.filter(e => e.date === d)).sort((a, b) => (a.when > b.when) - (a.when < b.when) || b.importance - a.importance);
      const wd = WD[(D(d).getUTCDay() + 6) % 7];
      return `<section class="cal-col${d === t ? " today" : ""}${d < t ? " past" : ""}" aria-label="${esc(dLabel(d, { weekday: "long", day: "numeric", month: "long" }))}">
        <header class="cal-col-h"><span class="cal-wd">${wd}</span><b class="cal-dn">${D(d).getUTCDate()}</b>${list.length ? `<span class="cal-cnt">${list.length}</span>` : ""}</header>
        ${list.length ? `<ul class="cal-chips">${list.map(e => chip(e)).join("")}</ul>` : `<p class="cal-none">—</p>`}
      </section>`;
    }).join("");
    const out = !covered(mon, sun) ? `<div class="card cal-out">${sh.stateHTML({ kind: "empty", title: "Bu hafta takvim kapsamı dışında", msg: `Takvim ${fmt.date(S.cal.range[0], { day: "numeric", month: "long" })} – ${fmt.date(S.cal.range[1], { day: "numeric", month: "long" })} aralığını kapsar.` })}</div>` : "";
    return `${navBar(label, evs.length ? `${evs.length} olay` : "")}${density()}${out}
      <div class="cal-wk"><div class="cal-grid" style="--cols:${days.length}">${cols}</div>${side()}</div>${surpriseCard()}`;
  }

  // ── Ay görünümü
  function renderMonth() {
    const a = D(S.anchor), first = `${a.getUTCFullYear()}-${String(a.getUTCMonth() + 1).padStart(2, "0")}-01`;
    const nextFirst = new Date(Date.UTC(a.getUTCFullYear(), a.getUTCMonth() + 1, 1, 12)).toISOString().slice(0, 10);
    const last = addDays(nextFirst, -1), start = monday(first), t = todayISO();
    const end = addDays(monday(last), 6);
    const evs = between(start, end);
    const cells = [];
    for (let d = start; d <= end; d = addDays(d, 1)) {
      const list = grouped(evs.filter(e => e.date === d)).sort((x, y) => y.importance - x.importance || (x.when > y.when) - (x.when < y.when));
      const show = list.slice(0, 4), more = list.length - show.length;
      const wkend = (D(d).getUTCDay() + 6) % 7 >= 5;
      const nodata = !covered(d, d);
      cells.push(`<div class="cal-cell${d.slice(0, 7) !== first.slice(0, 7) ? " other" : ""}${nodata ? " nodata" : ""}${d === t ? " today" : ""}${wkend ? " wkend" : ""}" role="gridcell" aria-label="${esc(dLabel(d, { day: "numeric", month: "long" }))}, ${list.length} olay">
        <button type="button" class="cal-cell-d" data-week="${d}" aria-label="${esc(dLabel(d, { day: "numeric", month: "long" }))} haftasını aç">${D(d).getUTCDate()}</button>
        ${show.length ? `<ul class="cal-chips">${show.map(e => chip(e, { time: false })).join("")}</ul>` : ""}
        ${more > 0 ? `<button type="button" class="cal-more" data-week="${d}">+${more} daha</button>` : ""}</div>`);
    }
    const label = dLabel(first, { month: "long", year: "numeric" });
    return `${navBar(label, evs.length ? `${evs.filter(e => e.date >= first && e.date <= last).length} olay` : "")}
      <div class="card card-flush cal-month" role="grid" aria-label="${esc(label)}">
        <div class="cal-month-h" role="row">${WD.map(w => `<span role="columnheader">${w}</span>`).join("")}</div>
        <div class="cal-month-g">${cells.join("")}</div></div>
      <p class="k-note">Hücrede en önemli 4 olay; tümü için "+ daha" ya da gün numarası (Hafta görünümü). Taralı günler takvim kapsamı dışında.</p>${surpriseCard()}`;
  }

  // ── yan panel: her iş günü yayımlananlar + gösterim
  function side() {
    const daily = S.cal?.daily || [];
    return `<aside class="cal-side">
      <div class="card"><h3 class="card-h">Her iş günü · Türkiye</h3>
        ${daily.length ? `<ul class="cal-daily">${daily.map(d => `<li><span class="cal-daily-t">${esc(d.time)}</span><span>${d.url ? `<a href="${esc(d.url)}" target="_blank" rel="noopener">${esc(d.name)}</a>` : esc(d.name)}</span><span class="cal-inst">${esc(d.inst)}</span></li>`).join("")}</ul>`
          : `<p class="k-note">Liste resmi takvimle birlikte gelir.</p>`}</div>
      <div class="card"><h3 class="card-h">Gösterim</h3>
        <ul class="cal-legend">
          <li><span class="cal-chip i3 k-macro demo">Kalın</span> yüksek önem</li>
          <li><span class="cal-chip i2 k-macro demo">Normal</span> orta</li>
          <li><span class="cal-chip i1 k-data demo">Soluk</span> düşük</li>
        </ul>
        <ul class="cal-legend kinds">${Object.entries(KIND).map(([k, v]) => `<li><span class="cal-dot k-${k}"></span>${esc(v.l)}</li>`).join("")}</ul>
      </div></aside>`;
  }

  // ── Liste görünümü (önceki sürüm)
  function upcomingCards(evs) {
    const top = evs.filter(e => e.importance >= 3).slice(0, 3);
    if (!top.length) return "";
    return `<div class="cal-next">${top.map(e => { const n = daysTo(e.date); return `
      <div class="card cal-card k-${e.kind}"><span class="cal-kind">${esc(KIND[e.kind]?.l || e.kind)} ${mk(e.market)}</span>
        <b class="cal-title"><button type="button" class="cal-open" data-i="${reg(e)}">${esc(e.title)}</button></b>
        <span class="cal-when">${esc(dLabel(e.date, { day: "numeric", month: "short", weekday: "short" }))} · ${timeOf(e)}</span>
        <span class="cal-count${n <= 1 ? " soon" : ""}">${n === 0 ? "Bugün" : n === 1 ? "Yarın" : `${n} gün`}</span></div>`; }).join("")}</div>`;
  }
  function renderList() {
    const evs = visible();
    let html = upcomingCards(evs);
    if (!evs.length) {
      html += `<div class="card">${sh.stateHTML({ kind: "empty", title: "Bu aralıkta olay yok", msg: S.kinds.size || S.important ? "Filtreleri gevşet ya da aralığı uzat." : "Seçili piyasa için yaklaşan olay bulunamadı." })}</div>`;
      return html;
    }
    const byDay = new Map();
    evs.forEach(e => (byDay.get(e.date) || byDay.set(e.date, []).get(e.date)).push(e));
    for (const [d, list] of byDay) byDay.set(d, grouped(list).sort((a, b) => (a.when > b.when) - (a.when < b.when) || b.importance - a.importance));
    return html + surpriseCard() + `<div class="card card-flush"><ol class="cal-list">${[...byDay].map(([d, list]) => `
      <li class="cal-day${daysTo(d) <= 1 ? " soon" : ""}"><h3 class="cal-day-h">${dayHead(d)}</h3>
        <ul>${list.map(e => `<li class="cal-ev k-${e.kind}">
          <span class="cal-t">${timeOf(e)}</span>
          <span class="cal-k"><span class="cal-dot" aria-hidden="true"></span>${esc(KIND[e.kind]?.s || e.kind)}</span>
          <span class="cal-main"><span class="cal-name">${e.ticker ? `<button type="button" class="tk-link" data-sym="${esc(e.ticker)}">${esc(e.ticker)}</button> ` : ""}<button type="button" class="cal-open" data-i="${reg(e)}">${esc(e.members ? `${e.title} · ${e.count} şirket` : e.ticker ? (e.name && e.region !== "TR" ? e.name + " bilanço" : e.title.replace(e.ticker + " ", "")) : e.title)}</button> ${mk(e.market)}</span>
            ${e.detail ? `<span class="cal-detail">${esc(e.detail)}</span>` : ""}${e.last ? `<span class="cal-detail cal-last">Son: ${esc(e.last)}</span>` : ""}</span>
          <span class="cal-imp">${imp(e.importance)}</span>
          <span class="cal-src">${e.url ? `<a href="${esc(e.url)}" target="_blank" rel="noopener" aria-label="${esc(e.title)} kaynağı">Kaynak ↗</a>` : ""}</span>
        </li>`).join("")}</ul></li>`).join("")}</ol></div>`;
  }

  // ── ayrıntı penceresi
  function openGroup(e, opener) {
    const dlg = $("#calDlg");
    $("#calDlgBody").innerHTML = `
      <p class="cal-dlg-meta"><span class="cal-dot k-earnings" aria-hidden="true"></span>Bilanço · ${esc(REGIONS[e.region] || "")}</p>
      <h2 class="cal-dlg-t" id="calDlgTitle">${esc(e.title)} · ${e.count} şirket</h2>
      <p class="cal-dlg-when">${esc(dLabel(e.date, { weekday: "long", day: "numeric", month: "long", year: "numeric" }))} <span class="cal-rel">${rel(daysTo(e.date))}</span></p>
      <div class="tbl-wrap"><table class="tbl cal-grp"><thead><tr><th>Hisse</th><th>Şirket</th><th>Zaman</th><th class="num">EPS bekl.</th></tr></thead><tbody>
      ${e.members.map(m => `<tr><td><a href="${esc(m.url || "#")}" target="_blank" rel="noopener" class="mono">${esc(m.ticker)}</a></td><td>${esc(m.name || "")}</td>
        <td>${esc(SESSION[m.session] || "—")}</td><td class="num mono">${m.eps_est != null ? fmt.num(m.eps_est, 2) : "—"}</td></tr>`).join("")}
      </tbody></table></div>
      <p class="k-note">S&P 500 içindeki en büyük şirketler ve izleme listen ayrı kutularda, yüksek önemle gösterilir. Kaynak: Alpha Vantage.</p>`;
    S.opener = opener;
    dlg.showModal();
  }
  function openDetail(e, opener) {
    if (e.members) return openGroup(e, opener);
    const dlg = $("#calDlg");
    const when = `${dLabel(e.date, { weekday: "long", day: "numeric", month: "long", year: "numeric" })}${e.timed ? ` · ${hm(e)}` : ""}`;
    const meta = [KIND[e.kind]?.l || e.kind, e.inst, e.group, e.freq ? e.freq + " yayın" : "", REGIONS[regionOf(e)]].filter(Boolean);
    $("#calDlgBody").innerHTML = `
      <p class="cal-dlg-meta"><span class="cal-dot k-${e.kind}" aria-hidden="true"></span>${meta.map(esc).join(" · ")} ${mk(e.market)}</p>
      <h2 class="cal-dlg-t" id="calDlgTitle">${esc(e.name && e.kind === "earnings" ? `${e.name} (${e.ticker}) bilanço` : shortTitle(e))}</h2>
      <p class="cal-dlg-when">${esc(when)}${e.session ? ` · ${esc(SESSION[e.session] || "")}` : ""}${e.period ? ` · dönem: ${esc(e.period)}` : ""} <span class="cal-rel">${rel(daysTo(e.date))}</span></p>
      ${e.detail ? `<p>${esc(e.detail)}</p>` : ""}
      ${cpiBox(e)}
      ${e.last ? `<div class="cal-dlg-box"><span class="k-lbl">Son açıklanan</span><b>${esc(e.last)}</b><span class="k-note">Kaynak: TCMB EVDS</span></div>` : ""}
      ${e.assets?.length ? `<div class="cal-dlg-sec"><span class="k-lbl">Etkilediği varlıklar</span><div class="cal-assets">${e.assets.map(a => `<span class="tag">${esc(a)}</span>`).join("")}</div></div>` : ""}
      ${e.items?.length > 1 ? `<div class="cal-dlg-sec"><span class="k-lbl">Bu yayındaki tablolar</span><ul class="cal-items">${e.items.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>` : ""}
      <div class="cal-dlg-sec cal-dlg-imp"><span class="k-lbl">Önem</span>${imp(e.importance)} ${e.importance === 3 ? "yüksek" : e.importance === 2 ? "orta" : "düşük"}</div>
      <div class="cal-dlg-act">
        ${e.ticker ? `<button type="button" class="btn btn-sm" data-sym="${esc(e.ticker)}" id="calDlgTk">${esc(e.ticker)} hisse paneli</button>` : ""}
        ${e.url ? `<a class="btn btn-sm" href="${esc(e.url)}" target="_blank" rel="noopener">Kaynağa git ↗</a>` : ""}
      </div>`;
    S.opener = opener;
    dlg.showModal();
    $("#calDlgTk")?.addEventListener("click", () => { dlg.close(); window.radar?.openTicker?.(e.ticker, opener); });
  }

  function render() {
    const box = $("#calBody");
    $$("#calView button").forEach(b => b.setAttribute("aria-checked", String(b.dataset.v === S.view)));
    $("#calRange").hidden = S.view !== "list";
    if (!S.loaded) { box.innerHTML = `<div class="card"><div class="skeleton sk-line w40"></div><div class="skeleton sk-line"></div><div class="skeleton sk-line w80"></div></div>`; return; }
    if (S.error && !S.cal) {
      box.innerHTML = `<div class="card">${sh.stateHTML({ kind: "error", title: "Takvim yüklenemedi", msg: esc(S.error.message) + ". Takvim ilk taramadan sonra oluşur.", action: "Tekrar dene", actionId: "calRetry" })}</div>`;
      $("#calRetry").onclick = () => { S.loaded = false; render(); load(); };
      return;
    }
    if (!S.anchor) S.anchor = todayISO();
    const all = (S.cal.events || []).filter(e => inMarket(e) && e.date >= todayISO());
    $("#calRegions").innerHTML = Object.entries(REGIONS).filter(([r]) => all.some(e => regionOf(e) === r)).map(([r, l]) =>
      `<button type="button" class="chip" data-r="${r}" aria-pressed="${S.regions.has(r)}">${esc(l)} <span class="n">${all.filter(e => regionOf(e) === r).length}</span></button>`).join("");
    $("#calKinds").innerHTML = Object.entries(KIND).filter(([k]) => all.some(e => e.kind === k)).map(([k, v]) =>
      `<button type="button" class="chip" data-k="${k}" aria-pressed="${S.kinds.has(k)}">${esc(v.l)} <span class="n">${all.filter(e => e.kind === k).length}</span></button>`).join("");
    $$("#calRange button").forEach(b => b.setAttribute("aria-checked", String(+b.dataset.d === S.days)));
    $("#calImp").setAttribute("aria-pressed", String(S.important));
    S.idx = [];
    const body = S.view === "week" ? renderWeek() : S.view === "month" ? renderMonth() : renderList();
    const until = S.cal.tr_until, mu = S.cal.macro_until;
    box.innerHTML = body + `<p class="k-note">Saatler İstanbul saatiyle · ${window.radarMethod?.link("takvim") || ""}</p>`;
  }
  function badge() {
    const n = (S.cal?.events || []).filter(e => inMarket(e) && e.importance >= 3 && [0, 1].includes(daysTo(e.date))).length;
    sh.setBadge("takvim", n, n ? `Bugün ve yarın ${n} önemli olay` : "", { tone: "info" });
  }
  function shift(dir) {
    if (dir === 0) S.anchor = todayISO();
    else if (S.view === "month") { const a = D(S.anchor); S.anchor = new Date(Date.UTC(a.getUTCFullYear(), a.getUTCMonth() + dir, 1, 12)).toISOString().slice(0, 10); }
    else S.anchor = addDays(S.anchor, 7 * dir);
    render();
  }
  function bind() {
    $("#calRegions").addEventListener("click", e => {
      const b = e.target.closest(".chip"); if (!b) return;
      S.regions.has(b.dataset.r) ? S.regions.delete(b.dataset.r) : S.regions.add(b.dataset.r);
      store.set("radar.calRegions", [...S.regions]); render(); $(`#calRegions .chip[data-r="${b.dataset.r}"]`)?.focus();
    });
    $("#calKinds").addEventListener("click", e => {
      const b = e.target.closest(".chip"); if (!b) return;
      S.kinds.has(b.dataset.k) ? S.kinds.delete(b.dataset.k) : S.kinds.add(b.dataset.k);
      store.set("radar.calKinds", [...S.kinds]); render(); $(`#calKinds .chip[data-k="${b.dataset.k}"]`)?.focus();
    });
    $$("#calRange button").forEach(b => b.onclick = () => { S.days = +b.dataset.d; store.set("radar.calDays", S.days); render(); });
    $$("#calView button").forEach(b => b.onclick = () => { S.view = b.dataset.v; store.set("radar.calView", S.view); render(); });
    sh.radioKeys?.($("#calRange")); sh.radioKeys?.($("#calView"));
    $("#calImp").onclick = () => { S.important = !S.important; store.set("radar.calImp", S.important); render(); };
    $("#calBody").addEventListener("click", e => {
      const nav = e.target.closest("[data-nav]");
      if (nav) { shift(+nav.dataset.nav); $(`#calBody [data-nav="${nav.dataset.nav}"]`)?.focus(); return; }
      const more = e.target.closest("[data-week]");
      if (more) { S.anchor = more.dataset.week; S.view = "week"; store.set("radar.calView", "week"); render(); return; }
      const t = e.target.closest(".tk-link");
      if (t) { sh.go("sinyal"); setTimeout(() => window.radar?.openTicker?.(t.dataset.sym, t), 60); return; }
      const o = e.target.closest("[data-i]");
      if (o && S.idx[+o.dataset.i]) openDetail(S.idx[+o.dataset.i], o);
    });
    $("#calBody").addEventListener("change", e => {
      if (e.target.id === "calPick" && e.target.value) { S.anchor = e.target.value; render(); $("#calPick")?.focus(); }
    });
    const dlg = $("#calDlg");
    $("#calDlgClose").onclick = () => dlg.close();
    dlg.addEventListener("click", e => { if (e.target === dlg) dlg.close(); });
    dlg.addEventListener("close", () => S.opener?.isConnected && S.opener.focus());
    addEventListener("marketchange", () => { badge(); if (sh.route === "takvim") render(); });
    addEventListener("minechange", () => { if (sh.route === "takvim") render(); });
  }
  function rangeRows() {
    if (S.view === "list") return visible();
    if (S.view === "week") { const m = monday(S.anchor); return between(m, addDays(m, 6)); }
    const a = D(S.anchor), f = `${S.anchor.slice(0, 7)}-01`;
    return between(f, addDays(new Date(Date.UTC(a.getUTCFullYear(), a.getUTCMonth() + 1, 1, 12)).toISOString().slice(0, 10), -1));
  }
  function exportCSV() {
    const ex = window.radarExport; if (!ex) return;
    const rows = rangeRows().map(e => ({ tarih: e.date, saat_istanbul: e.timed ? timeOf(e) : "", tur: KIND[e.kind]?.l || e.kind, piyasa: e.market,
      kurum: e.inst || "", hisse: e.ticker || "", olay: e.title, donem: e.period || "", ayrinti: e.detail || "",
      son_aciklanan: e.last || "", etkiledigi: (e.assets || []).join("; "), onem: e.importance, kaynak: e.url || "" }));
    ex.download(`takvim_${ex.stamp()}.csv`, ex.toCSV(rows), "text/csv;charset=utf-8");
  }
  bind();
  sh.register("takvim", {
    onShow() { S.loaded ? render() : (render(), load()); },
    async refresh() { S.loaded = false; render(); await load(); },
    exports: () => [{ label: "Takvim (CSV)", hint: S.view === "list" ? `${RANGE[S.days] || S.days + " gün"}, filtreli` : `görünen ${S.view === "week" ? "hafta" : "ay"}, filtreli`, run: exportCSV, disabled: !S.cal }],
    exportInfo: () => S.cal ? `${S.view === "list" ? RANGE[S.days] : VIEWS[S.view]}${S.kinds.size ? ` · ${[...S.kinds].map(k => KIND[k].l).join(", ")}` : ""}${S.important ? " · yalnız önemli" : ""}` : "",
    exportNote: "Takvim henüz yüklenmedi",
  });
  setTimeout(() => { if (!S.loaded) load(); }, 1200);           // rozet için arka planda
})();
