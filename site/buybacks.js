/* Piyasa Radarı — Şirket Geri Alım sekmesi.
   Veri, ayrı repodaki takipçiden gelir (gptrade/kap-geri-alim-takibi → kap-buybacks.json).
   Güncel fiyatlar: data/bb_quotes.json (pipeline saatte bir Yahoo'dan toplu çeker) + izleme listesi fiyatları. */
(() => {
  "use strict";
  const sh = window.shell;
  const { $, $$, esc, fmt, glyph, dirCls } = sh;
  const me = document.currentScript;
  const SRC = me.dataset.src, FALLBACK = me.dataset.fallback;
  const DAY = 86400000;
  const R = () => window.radar;
  const SERIES = ["--series-1", "--series-2", "--series-3", "--series-4", "--series-5"];

  const S = { rows: null, quotes: {}, quotesAt: null, loaded: false, loading: false, error: null,
    days: 30, q: "", watch: false, suspectOnly: false, sort: "amount", dir: -1, open: new Set(), updated: null };

  // ─────────────────────────────── birimler (başlıkta yazar, hücrede yalnız sayı)
  const mn = v => v == null ? "—" : fmt.num(v / 1e6, 2);            // mn ₺
  const bin = v => v == null ? "—" : fmt.num(v / 1e3, 0);           // bin adet
  const tlShort = v => v == null ? "—" : Math.abs(v) >= 1e9 ? fmt.num(v / 1e9, 2) + " mr ₺" : Math.abs(v) >= 1e6 ? fmt.num(v / 1e6, 1) + " mn ₺" : Math.abs(v) >= 1e3 ? fmt.num(v / 1e3, 0) + " bin ₺" : fmt.num(v, 0) + " ₺";
  const lotsShort = v => v == null ? "—" : v >= 1e6 ? fmt.num(v / 1e6, 2) + " mn" : v >= 1e3 ? fmt.num(v / 1e3, 0) + " bin" : fmt.int(v);

  // ─────────────────────────────── veri
  function parseTR(s) {          // "30.09.2026 14:19:37" (İstanbul) → Date
    const m = /(\d{2})\.(\d{2})\.(\d{4})(?:\s+(\d{2}):(\d{2}))?/.exec(s || "");
    return m ? new Date(Date.UTC(+m[3], +m[2] - 1, +m[1], (+m[4] || 12) - 3, +m[5] || 0)) : null;
  }
  function kindOf(r) {
    if (r.quantity) return "tx";
    const t = (r.notice_type || "").toLocaleLowerCase("tr");
    if (/başlat|yönetim kurulu|karar|program/.test(t)) return "program";
    if (/tamamlan|sona er|bitir/.test(t)) return "end";
    return "other";
  }
  function normalize(raw) {
    return raw.map(r => {
      const pub = parseTR(r.publish_date);
      const txd = r.transaction_date ? new Date(r.transaction_date + "T12:00:00Z") : pub;
      const price = r.price ?? (r.price_low && r.price_high ? (r.price_low + r.price_high) / 2 : null);
      return {
        id: r.disclosure_index, t: (r.tickers || "").split(/[,\s]+/)[0].toUpperCase(), name: r.company_title || "",
        pub, date: txd, price, qty: r.quantity, amount: price && r.quantity ? price * r.quantity : null,
        own: r.ownership_pct_after, url: r.source_url, type: r.notice_type || "", kind: kindOf(r), review: !!r.needs_review, fields: r.raw_fields || {},
      };
    }).filter(r => r.t && r.pub);
  }
  // Ayrıştırma hatası koruması: fiyat, şirketin medyan işlem fiyatından 10 kattan fazla saparsa ya da
  // mantıksız yüksekse işlem şüpheli sayılır; tutarı toplamlara girmez.
  const MAX_PRICE = 50000;
  function flagOutliers(rows) {
    const by = new Map();
    rows.forEach(r => { if (r.kind === "tx" && r.price) (by.get(r.t) || by.set(r.t, []).get(r.t)).push(r.price); });
    const med = new Map([...by].map(([t, ps]) => { const s = ps.slice().sort((a, b) => a - b); return [t, s[Math.floor(s.length / 2)]]; }));
    rows.forEach(r => {
      if (r.kind !== "tx" || !r.price) return;
      const m = med.get(r.t);
      if (r.price > MAX_PRICE || (by.get(r.t).length >= 2 && m && (r.price / m > 10 || r.price / m < 0.1))) { r.suspect = true; r.amount = null; }
    });
  }
  // Program bildirimi alanları: azami pay (nominal ₺ ≈ adet), ayrılan azami fon (₺), süre
  const trNum = v => { if (v == null) return null; const n = parseFloat(String(v).replace(/[^\d,.-]/g, "").replace(/\./g, "").replace(",", ".")); return isFinite(n) && n > 0 ? n : null; };
  function programMap(rows) {
    const m = new Map();
    rows.filter(r => r.kind !== "tx").sort((a, b) => a.pub - b.pub).forEach(r => {
      const f = r.fields || {};
      const maxQty = trNum(f["geri alıma konu azami pay miktarı (nominal tl)"] ?? f["geri alıma konu pay miktarı (nominal tl)"]);
      const maxFund = trNum(f["geri alım için ayrılan fonun toplam tutarı (tl)"] ?? f["ödenecek azami tutar (tl)"]);
      const dur = (f["varsa geri alım programının uygulanacağı süre"] || "").trim();
      const ended = r.kind === "end" || /evet/i.test(f["geri alım programı sonlandı mı?"] || "");
      const prev = m.get(r.t) || {};
      if (ended) { m.set(r.t, { ...prev, ended: r.pub, endUrl: r.url }); return; }
      if (maxQty || maxFund || dur || r.kind === "program")
        m.set(r.t, { pub: r.pub, url: r.url, type: r.type, maxQty: maxQty ?? prev.maxQty ?? null, maxFund: maxFund ?? prev.maxFund ?? null, dur: dur || prev.dur || "", ended: null });
    });
    return m;
  }
  // Süre metnini kısalt: "Yönetim kurulu karar tarihinden itibaren bir yıl" → "1 yıl", "3 YIL" → "3 yıl", "18 (on sekiz) ay" → "18 ay"
  const WORDN = { bir: 1, iki: 2, üç: 3, dört: 4, beş: 5, altı: 6, yedi: 7, sekiz: 8, dokuz: 9, on: 10, "on iki": 12, "on sekiz": 18, "yirmi dört": 24, "otuz altı": 36 };
  function durShort(d) {
    if (!d) return "";
    const t = d.toLocaleLowerCase("tr").replace(/\s+/g, " ").trim();
    const end = /(\d{2})[./](\d{2})[./](\d{4}).*sona er/.exec(t);
    if (end) return `${end[1]}.${end[2]}.${end[3]} bitiş`;
    if (/genel kurul(?:\S*)? tarihine kadar/.test(t)) return "ilk GK'ya kadar";
    const yrs = /(\d{4})\s*[-–]\s*(\d{4})/.exec(t);
    if (yrs) return `${yrs[1]}–${yrs[2]}`;
    const u = t.replace(/\([^)]*\)/g, " ");
    const m = /(?<![\p{L}\d])(?:(\d+)\s*|(on iki|on sekiz|yirmi dört|otuz altı|bir|iki|üç|dört|beş|altı|yedi|sekiz|dokuz|on)\s+)(yıl|sene|ay|gün)/u.exec(u);
    if (!m) return t.length > 18 ? t.slice(0, 17) + "…" : t;
    return `${m[1] || WORDN[m[2]]} ${m[3] === "sene" ? "yıl" : m[3]}`;
  }


  async function getJSON(url, bust = true) {
    const r = await fetch(bust ? `${url}${url.includes("?") ? "&" : "?"}t=${Date.now()}` : url, { cache: "no-store" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  }
  async function load(force = false) {
    if (S.loading || (S.loaded && !force)) return;
    S.loading = true; S.error = null;
    if (!S.loaded) renderLoading();
    let raw = null, lastErr = null;
    for (const u of [SRC, FALLBACK]) { try { raw = await getJSON(u); break; } catch (e) { lastErr = e; } }
    try { const q = await getJSON("data/bb_quotes.json"); S.quotes = q.quotes || {}; S.quotesAt = q.generated; } catch { /* isteğe bağlı */ }
    S.loading = false;
    if (!Array.isArray(raw)) {
      S.error = lastErr?.message || "veri okunamadı";
      if (!S.loaded) renderError();
      return;
    }
    S.rows = normalize(raw);
    flagOutliers(S.rows);
    S.prog = programMap(S.rows);
    S.updated = S.rows.reduce((m, r) => (r.pub > m ? r.pub : m), new Date(0));
    S.loaded = true;
    sh.setUpdated("geri-alim", S.updated, { label: "Son KAP bildirimi" });
    await Promise.race([R()?.ready, new Promise(r => setTimeout(r, 3000))]);
    badge();
    render();
  }
  function badge() {
    const n = S.rows.filter(r => r.kind === "tx" && r.pub >= Date.now() - DAY).length;
    sh.setBadge("geri-alim", n, `Son 24 saatte ${n} geri alım işlemi bildirildi`);
  }

  // ─────────────────────────────── hesap
  function watchSet() { return new Set((R()?.state?.feed?.watchlist || []).filter(w => w.market === "BIST").map(w => w.symbol)); }
  function quote(t) {
    const p = R()?.state?.prices?.[t];
    if (p?.last) return { last: p.last, at: p.updated, src: "izleme listesi" };
    const q = S.quotes[t];
    return q ? { last: q.last, at: q.date + "T15:00:00Z", src: "Yahoo kapanış" } : null;
  }
  function inPeriod() {
    const cut = Date.now() - S.days * DAY, q = S.q.toLocaleLowerCase("tr"), w = watchSet();
    return S.rows.filter(r => r.date >= cut && (!S.watch || w.has(r.t))
      && (!q || r.t.toLocaleLowerCase("tr").includes(q) || r.name.toLocaleLowerCase("tr").includes(q)));
  }
  function aggregate(rows) {
    const m = new Map();
    for (const r of rows) {
      if (r.kind !== "tx") continue;
      const o = m.get(r.t) || { t: r.t, name: r.name, n: 0, qty: 0, amount: 0, pq: 0, last: null, own: null, ownAt: null, tx: [], review: 0, suspect: 0 };
      o.n++; o.qty += r.qty || 0; o.amount += r.amount || 0;
      if (r.amount) o.pq += r.qty;
      if (r.suspect) o.suspect++;
      if (!o.last || r.date > o.last) o.last = r.date;
      if (r.own != null && (!o.ownAt || r.pub > o.ownAt)) { o.own = r.own; o.ownAt = r.pub; }
      o.review += r.review ? 1 : 0;
      o.tx.push(r);
      m.set(r.t, o);
    }
    // dönemde program açıklayıp henüz işlem bildirmeyenler de tabloda görünsün
    for (const r of rows) if (r.kind === "program" && !m.has(r.t)) m.set(r.t, { t: r.t, name: r.name, n: 0, qty: 0, amount: 0, pq: 0, last: null, own: null, ownAt: null, tx: [], review: 0, suspect: 0 });
    const cut = Date.now() - S.days * DAY;
    return [...m.values()].map(o => {
      const pg = S.prog?.get(o.t);
      o.pg = pg && !pg.ended ? pg : pg || null;
      o.maxQty = pg && !pg.ended ? pg.maxQty : null;
      o.maxFund = pg && !pg.ended ? pg.maxFund : null;
      o.dur = pg && !pg.ended ? durShort(pg.dur) : "";
      o.newProg = !!(pg && pg.pub >= cut && !pg.ended);
      o.avg = o.pq ? o.amount / o.pq : null;
      o.q = quote(o.t);
      o.ratio = o.q && o.avg ? o.q.last / o.avg : null;
      o.tx.sort((a, b) => b.date - a.date);
      return o;
    });
  }

  // ─────────────────────────────── çizim: KPI
  function kpis(rows, agg) {
    const tx = rows.filter(r => r.kind === "tx"), prog = rows.filter(r => r.kind === "program");
    const total = tx.reduce((s, r) => s + (r.amount || 0), 0), qty = tx.reduce((s, r) => s + (r.qty || 0), 0);
    const top = agg.slice().sort((a, b) => b.amount - a.amount)[0];
    const k = (label, value, sub = "", tip = "") => `<div class="kpi" ${tip ? `data-tip="${esc(tip)}"` : ""}><span class="kpi-label">${label}</span><span class="kpi-value">${value}</span>${sub ? `<span class="kpi-sub">${sub}</span>` : ""}</div>`;
    return `<div class="kpi-grid">
      ${k("Geri alım yapan şirket", fmt.int(agg.length))}
      ${k("İşlem bildirimi", fmt.int(tx.length))}
      ${k("Toplam adet", lotsShort(qty), fmt.int(qty) + " pay")}
      ${k("Toplam tutar", tlShort(total), "", "Fiyatı şüpheli işlemler toplama katılmaz")}
      ${k("En çok alan", top ? esc(top.t) : "—", top ? tlShort(top.amount) : "")}
      ${k("Yeni program / YK kararı", fmt.int(prog.length))}
    </div>`;
  }

  // ─────────────────────────────── çizim: günlük yığılmış çubuk grafik (ilk 5 şirket + Diğer)
  function dailyChart(rows, agg, W) {
    const H = 160, padL = 44, padB = 20, padT = 16;
    const top5 = agg.filter(o => o.amount > 0).sort((a, b) => b.amount - a.amount).slice(0, 5).map(o => o.t);
    const colors = SERIES.map(v => sh.cssVar(v)), other = sh.cssVar("--series-other");
    const key = d => d.toISOString().slice(0, 10);
    const today = fmt.dayKey(Date.now());
    const end = new Date(today + "T12:00:00Z");
    const byDay = new Map();
    for (let i = S.days - 1; i >= 0; i--) {
      const d = new Date(end - i * DAY), g = d.getUTCDay();
      if (g !== 0 && g !== 6) byDay.set(key(d), { amount: 0, n: 0, parts: new Map() });
    }
    for (const r of rows) {
      if (r.kind !== "tx" || !r.amount) continue;
      const o = byDay.get(key(r.date));
      if (!o) continue;
      const s = top5.includes(r.t) ? r.t : "Diğer";
      const p = o.parts.get(s) || { amount: 0, n: 0, cos: new Set() };
      p.amount += r.amount; p.n++; p.cos.add(r.t); o.parts.set(s, p);
      o.amount += r.amount; o.n++;
    }
    const days = [...byDay.entries()];
    if (!days.some(([, o]) => o.amount)) return `<section class="card bb-chart"><div class="card-head"><h2 class="card-title">Günlük geri alım tutarı</h2></div>${sh.stateHTML({ kind: "empty", compact: true, title: "Bu dönemde tutarı hesaplanabilen işlem yok" })}</section>`;
    const max = Math.max(...days.map(([, o]) => o.amount));
    const nice = (v => { const p = 10 ** Math.floor(Math.log10(v)); return [1, 2, 2.5, 5, 10].map(m => m * p).find(x => x >= v); })(max);
    const bw = (W - padL) / days.length, gap = Math.max(1, Math.min(4, bw * 0.25));
    const y = v => H - padB - (v / nice) * (H - padB - padT);
    const order = [...top5, "Diğer"], colorOf = s => s === "Diğer" ? other : colors[top5.indexOf(s)];
    let cols = "";
    days.forEach(([k, o], i) => {
      const x = padL + i * bw + gap / 2, w = Math.max(1, bw - gap);
      let acc = 0, segs = "";
      const present = order.filter(s => o.parts.has(s));
      present.forEach((s, j) => {
        const p = o.parts.get(s), y0 = y(acc), y1 = y(acc + p.amount), h = y0 - y1;
        acc += p.amount;
        if (h <= 0) return;
        const isTop = j === present.length - 1, r = isTop ? Math.min(4, w / 2, h) : 0;
        const d = r ? `M${x},${y0} V${y1 + r} Q${x},${y1} ${x + r},${y1} H${x + w - r} Q${x + w},${y1} ${x + w},${y1 + r} V${y0} Z` : `M${x},${y0} V${y1} H${x + w} V${y0} Z`;
        segs += `<path d="${d}" fill="${colorOf(s)}" class="seg-r"/>`;
        if (k === today) segs += `<path d="${d}" fill="url(#bbHatch)"/>`;
      });
      const dl = fmt.date(k + "T12:00:00Z", { day: "numeric", month: "short", weekday: "short" });
      const tip = `<b>${dl}${k === today ? " · gün içi" : ""}</b><br>${tlShort(o.amount)} · ${o.n} işlem` +
        (o.parts.size ? "<hr>" + order.filter(s => o.parts.has(s)).map(s => { const p = o.parts.get(s); return `<i class="sw" style="background:${colorOf(s)}"></i>${esc(s)}${s === "Diğer" ? ` (${p.cos.size} şirket)` : ""}: ${tlShort(p.amount)} · ${p.n} işlem`; }).join("<br>") : "");
      cols += `<g class="col" data-tip="${esc(tip)}"><rect class="hit" x="${padL + i * bw}" y="${padT}" width="${bw}" height="${H - padB - padT}"/>${segs}` +
        (k === today ? `<text class="today-lbl" x="${Math.min(W - 2, x + w / 2)}" y="${Math.max(10, y(o.amount) - 4)}" text-anchor="${x + w / 2 > W - 30 ? "end" : "middle"}">gün içi</text>` : "") + `</g>`;
    });
    const ticks = [0, nice / 2, nice].map(v => `<line class="grid" x1="${padL}" x2="${W}" y1="${y(v)}" y2="${y(v)}"/><text class="ax" x="${padL - 6}" y="${y(v) + 3}" text-anchor="end">${fmt.num(v / 1e6, v / 1e6 < 10 && v ? 1 : 0)}</text>`).join("");
    const step = Math.ceil(days.length / Math.max(3, Math.floor(W / 70)));
    const xl = days.map(([k], i) => i % step ? "" : `<text class="ax" x="${padL + i * bw + bw / 2}" y="${H - 5}" text-anchor="middle">${fmt.date(k + "T12:00:00Z", { day: "2-digit", month: "2-digit" })}</text>`).join("");
    const legend = order.filter(s => s !== "Diğer" || days.some(([, o]) => o.parts.has("Diğer")))
      .map(s => `<span><i class="sw" style="background:${colorOf(s)}"></i>${esc(s)}</span>`).join("") +
      (byDay.has(today) ? `<span><i class="sw hatch-sw"></i>bugün (gün içi)</span>` : "");
    return `<section class="card bb-chart" aria-labelledby="bbChartT">
      <div class="card-head"><h2 class="card-title" id="bbChartT">Günlük geri alım tutarı <span class="card-meta">· mn ₺ · işlem tarihine göre</span></h2><div class="chart-legend">${legend}</div></div>
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Son ${S.days} günün günlük geri alım tutarları; ilk beş şirket ve diğerleri yığılmış">
        <defs><pattern id="bbHatch" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="2" height="5" style="fill:var(--surface)" opacity=".65"/></pattern></defs>
        ${ticks}${cols}${xl}</svg></section>`;
  }

  // ─────────────────────────────── çizim: tablo
  function table(agg, showRatio) {
    const w = watchSet();
    const COLS = [["t", "Hisse"], ["name", "Şirket"], ["maxQty", "Azami pay (bin)", 1], ["maxFund", "Azami fon (mn ₺)", 1], ["dur", "Süre"], ["n", "İşlem", 1], ["qty", "Adet (bin)", 1], ["amount", "Tutar (mn ₺)", 1], ["avg", "Ort. fiyat (₺)", 1],
      ...(showRatio ? [["ratio", "Güncel / Ort.", 1]] : []), ["own", "Sermaye payı (%)", 1], ["last", "Son işlem", 1]];
    const k = S.sort, dir = S.dir;
    agg.sort((a, b) => {
      const va = a[k], vb = b[k];
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      return (typeof va === "string" ? va.localeCompare(vb, "tr") : va - vb) * dir;
    });
    const TIPS = { maxQty: "Son program bildirimindeki geri alınabilecek azami pay (nominal ₺ ≈ adet, bin)",
      maxFund: "Geri alım için ayrılan azami fon (ödenecek azami tutar)", dur: "Programın uygulanacağı süre", ratio: "Güncel fiyat ÷ ortalama geri alım fiyatı. 1'in üstü: şirket bugünkü fiyattan ucuza almış.", qty: "Dönemdeki toplam geri alınan pay (bin adet)", amount: "Fiyat × adet; şüpheli fiyatlı işlemler hariç" };
    const head = COLS.map(([c, l, num]) => `<th scope="col" class="${num ? "num" : ""}" aria-sort="${c === k ? (dir > 0 ? "ascending" : "descending") : "none"}">
      <button type="button" class="th-sort" data-c="${c}" ${TIPS[c] ? `data-tip="${esc(TIPS[c])}"` : ""}>${l}<span class="arr" aria-hidden="true">${c === k ? (dir > 0 ? "▲" : "▼") : "▼"}</span></button></th>`).join("");
    const body = agg.map(o => {
      const open = S.open.has(o.t) || (S.suspectOnly && o.suspect);
      const flags = [o.suspect ? `${o.suspect} işlemde fiyat şüpheli (toplamlara katılmadı)` : "", o.review ? `${o.review} bildirim elle kontrol istiyor` : ""].filter(Boolean).join(" · ");
      const rk = o.ratio == null ? null : Math.abs(o.ratio - 1) < 0.005 ? 0 : o.ratio - 1;
      const ratioTip = o.ratio == null ? (o.avg ? "Güncel fiyat yok" : "Ortalama fiyat hesaplanamadı") :
        `Güncel ${fmt.num(o.q.last)} ₺ (${o.q.src}) ÷ ort. ${fmt.num(o.avg)} ₺ = ${fmt.num(o.ratio)}<br>Ortalamaya göre ${fmt.pct((o.ratio - 1) * 100)}`;
      return `<tr class="row ${open ? "open" : ""} ${w.has(o.t) ? "mine" : ""}" data-t="${esc(o.t)}" tabindex="0" aria-expanded="${!!open}">
        <td class="tk">${esc(o.t)}${w.has(o.t) ? ` <span class="mine-dot" data-tip="İzleme listende">●</span>` : ""}</td>
        <td class="nm" data-tip="${esc(o.name)}">${o.newProg ? `<span class="tag up" data-tip="Bu dönemde yeni program / YK kararı açıklandı (${o.pg ? fmt.date(o.pg.pub) : ""})">yeni</span> ` : ""}${esc(o.name)}</td>
        <td class="num">${o.maxQty == null ? "—" : `<span data-tip="${esc(`Azami ${fmt.int(o.maxQty)} pay (nominal ₺)<br>Program bildirimi: ${fmt.date(o.pg.pub, { day: "numeric", month: "short", year: "numeric" })}`)}">${bin(o.maxQty)}</span>`}</td>
        <td class="num">${o.maxFund == null ? "—" : mn(o.maxFund)}</td>
        <td class="dur" ${o.pg?.dur && o.pg.dur !== o.dur ? `data-tip="${esc(o.pg.dur)}"` : ""}>${o.dur ? esc(o.dur) : "—"}</td>
        <td class="num">${o.n || "—"}${flags ? ` <span class="rv" data-tip="${esc(flags)}">⚠</span>` : ""}</td>
        <td class="num">${o.n ? bin(o.qty) : "—"}</td>
        <td class="num"><b>${o.n ? mn(o.amount) : "—"}</b></td>
        <td class="num">${o.avg ? fmt.num(o.avg) : "—"}</td>
        ${showRatio ? `<td class="num"><span class="ratio ${dirCls(rk)}" data-tip="${esc(ratioTip)}">${o.ratio == null ? "—" : `${glyph(rk)} ${fmt.num(o.ratio)}`}</span></td>` : ""}
        <td class="num">${o.own == null ? "—" : fmt.num(o.own)}</td>
        <td class="num">${o.last ? fmt.date(o.last) : "—"}</td>
      </tr>${open ? `<tr class="drawer"><td colspan="${COLS.length}">${txList(o)}</td></tr>` : ""}`;
    }).join("");
    return `<section class="card card-flush" aria-labelledby="bbTblT">
      <div class="card-head"><h2 class="card-title" id="bbTblT">Şirket bazında (${agg.length})</h2><span class="card-meta">satıra tıkla: işlemler · başlığa tıkla: sırala${showRatio ? "" : " · güncel fiyat verisi yok"}</span></div>
      <div class="tbl-scroll bb-scroll"><table class="tbl bb-tbl"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>
      ${agg.length ? "" : sh.stateHTML({ kind: "empty", title: S.suspectOnly ? "Bu dönemde şüpheli işlem yok" : "Bu dönemde geri alım işlemi yok", msg: S.q || S.watch ? "Arama ya da “Sadece izleme listem” filtresi açık." : "Dönemi uzatmayı dene." })}</div></section>`;
  }
  function progLine(o) {
    const pg = o.pg;
    if (!pg) return "";
    const bits = [pg.maxQty ? `azami ${fmt.int(pg.maxQty)} pay` : "", pg.maxFund ? `azami fon ${tlShort(pg.maxFund)}` : "", pg.dur ? `süre ${esc(durShort(pg.dur))}` : "",
].filter(Boolean).join(" · ");
    return `<p class="prog-line">${pg.ended ? `<span class="tag">program sonlandı ${fmt.date(pg.ended)}</span>` : `<span class="tag up">program</span>`}
      <a href="${esc(pg.url)}" target="_blank" rel="noopener">${esc(pg.type || "Program bildirimi")} ↗</a> <span class="meta">${fmt.date(pg.pub, { day: "numeric", month: "short", year: "numeric" })}${bits ? " · " + bits : ""}</span></p>`;
  }
  function txList(o) {
    if (!o.tx.length) return progLine(o) + `<p class="meta">Bu dönemde işlem bildirimi yok.</p>`;
    return progLine(o) + `<table class="tx" aria-label="${esc(o.t)} işlemleri"><thead><tr><th>İşlem tarihi</th><th class="num">Fiyat (₺)</th><th class="num">Adet</th><th class="num">Tutar (₺)</th><th class="num">Sermaye payı (%)</th><th>Bildirim</th></tr></thead><tbody>` +
      o.tx.map(r => `<tr class="${r.suspect ? "sus" : ""}"><td>${fmt.date(r.date, { day: "numeric", month: "short", year: "numeric" })}</td>
        <td class="num">${r.price ? fmt.num(r.price, 3) : "—"}${r.suspect ? ` <span class="rv" data-tip="Fiyat şüpheli: şirketin diğer işlemlerinden çok farklı; KAP bildirimini kontrol et">⚠</span>` : ""}</td>
        <td class="num">${fmt.int(r.qty)}</td><td class="num">${r.suspect ? "—" : fmt.num(r.amount, 0)}</td>
        <td class="num">${r.own == null ? "—" : fmt.num(r.own)}</td>
        <td>${r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener">KAP ${r.id} ↗</a>` : r.id}${r.review ? ` <span class="rv" data-tip="Ayrıştırma elle kontrol istiyor">⚠</span>` : ""}</td></tr>`).join("") + `</tbody></table>`;
  }
  // ─────────────────────────────── ana çizim
  function render() {
    if (!S.loaded || sh.route !== "geri-alim") return;              // gizliyken çizme: genişlik ölçülemez
    const body = $("#bbBody"), sus = $("#bbSuspect");
    queueMicrotask(sh.syncActions);                              // dışa aktar düğmesinin durumu filtreye bağlı
    if (sh.market === "US") {
      sus.hidden = true; $("#bbSrc").textContent = "";
      body.innerHTML = sh.stateHTML({ kind: "info", title: "Geri alım verisi yalnız BIST şirketleri için", msg: "Piyasa filtresi şu an <b>ABD</b>. KAP pay geri alım bildirimleri Borsa İstanbul şirketlerini kapsar.", action: "Piyasayı Tümü yap", actionId: "bbAll" });
      $("#bbAll").onclick = () => sh.setMarket("ALL");
      return;
    }
    const period = inPeriod();
    const nSus = period.filter(r => r.suspect).length;
    sus.hidden = !nSus;
    if (!nSus) S.suspectOnly = false;
    sus.setAttribute("aria-pressed", String(S.suspectOnly));
    sus.innerHTML = `⚠ ${nSus} işlemde fiyat şüpheli${S.suspectOnly ? " · filtre açık ✕" : ""}`;
    sus.dataset.tip = S.suspectOnly ? "Tüm şirketleri göster" : "Fiyatı şirketin diğer işlemlerinden 10 kattan fazla sapan işlemler (ayrıştırma hatası şüphesi). Tıkla: tabloyu bu şirketlere süz.";
    let agg = aggregate(period);
    if (S.suspectOnly) agg = agg.filter(o => o.suspect);
    const showRatio = aggregate(period).some(o => o.ratio != null);
    const W = Math.max(280, Math.round((body.getBoundingClientRect().width || 720) - 34));
    const qAt = S.quotesAt ? ` · güncel fiyatlar ${fmt.dt(S.quotesAt)}` : "";
    $("#bbSrc").innerHTML = `Kaynak: <a href="https://github.com/gptrade/kap-geri-alim-takibi" target="_blank" rel="noopener">kap-geri-alim-takibi</a> · son bildirim ${fmt.dt(S.updated)} · ${fmt.int(S.rows.length)} kayıt${qAt}`;
    const scroll = $(".bb-scroll")?.scrollTop || 0;
    body.innerHTML = `<div class="view" style="gap:var(--s-4)">${kpis(period, aggregate(period))}${dailyChart(period, aggregate(period), W)}${table(agg, showRatio)}</div>`;
    if ($(".bb-scroll")) $(".bb-scroll").scrollTop = scroll;
    $$("#bbBody .th-sort").forEach(b => b.onclick = () => {
      const c = b.dataset.c;
      S.dir = S.sort === c ? -S.dir : (["t", "name"].includes(c) ? 1 : -1); S.sort = c;
      render(); $(`#bbBody .th-sort[data-c="${c}"]`)?.focus();
    });
  }
  function toggleRow(tr) {
    const t = tr.dataset.t;
    S.open.has(t) ? S.open.delete(t) : S.open.add(t);
    render();
    $(`#bbBody tr.row[data-t="${CSS.escape(t)}"]`)?.focus();
  }
  function renderLoading() {
    $("#bbSrc").innerHTML = `<span class="skeleton sk-line w40" style="display:inline-block;width:320px"></span>`;
    $("#bbBody").innerHTML = `<div class="view" style="gap:var(--s-4)" aria-busy="true" aria-label="Geri alım verisi yükleniyor">
      <div class="kpi-grid">${Array.from({ length: 6 }, () => `<div class="kpi"><div class="skeleton sk-line w60"></div><div class="skeleton sk-line lg w40"></div></div>`).join("")}</div>
      <div class="card"><div class="skeleton sk-line w40"></div><div class="skeleton" style="height:160px;margin-top:12px"></div></div>
      <div class="card card-flush"><table class="tbl"><tbody>${sh.skeletonRows(8, 6)}</tbody></table></div></div>`;
  }
  function renderError() {
    $("#bbSrc").textContent = "";
    $("#bbBody").innerHTML = sh.stateHTML({ kind: "error", title: "Geri alım verisi yüklenemedi", msg: `${esc(S.error)}. Takipçi reposu (kap-geri-alim-takibi) yayında mı? Biraz sonra tekrar dene.`, action: "Tekrar dene", actionId: "bbRetry" });
    $("#bbRetry").onclick = () => load(true);
  }

  // ─────────────────────────────── dışa aktarma
  function exportCompanies() {
    const ex = window.radarExport;
    const rows = aggregate(inPeriod()).filter(o => !S.suspectOnly || o.suspect).sort((a, b) => b.amount - a.amount).map(o => ({
      hisse: o.t, sirket: o.name, yeni_program: o.newProg ? "evet" : "", azami_pay: o.maxQty ?? "", azami_fon_tl: o.maxFund ?? "", sure: o.dur, program_tarihi: o.pg?.pub ? o.pg.pub.toISOString().slice(0, 10) : "", islem_sayisi: o.n, toplam_adet: o.qty, tutar_tl: Math.round(o.amount), ort_fiyat_tl: o.avg ?? "", guncel_fiyat_tl: o.q?.last ?? "",
      guncel_bolu_ort: o.ratio ?? "", sermaye_payi_pct: o.own ?? "", son_islem: o.last ? o.last.toISOString().slice(0, 10) : "", supheli_islem: o.suspect, kontrol_gereken: o.review }));
    ex.download(`geri-alim_sirketler_${S.days}g_${ex.stamp()}.csv`, ex.toCSV(rows), "text/csv;charset=utf-8");
  }
  function exportTx() {
    const ex = window.radarExport;
    const rows = inPeriod().filter(r => r.kind === "tx" && (!S.suspectOnly || r.suspect)).sort((a, b) => b.date - a.date).map(r => ({
      islem_tarihi: r.date.toISOString().slice(0, 10), bildirim_zamani: r.pub.toISOString(), hisse: r.t, sirket: r.name, fiyat_tl: r.price ?? "", adet: r.qty ?? "",
      tutar_tl: r.amount == null ? "" : Math.round(r.amount), sermaye_payi_pct: r.own ?? "", supheli: r.suspect ? "evet" : "", kap_no: r.id, url: r.url || "" }));
    ex.download(`geri-alim_islemler_${S.days}g_${ex.stamp()}.csv`, ex.toCSV(rows), "text/csv;charset=utf-8");
  }

  // ─────────────────────────────── bağla
  $$("#bbPeriod button").forEach(b => b.onclick = () => {
    S.days = +b.dataset.d; $$("#bbPeriod button").forEach(x => x.setAttribute("aria-checked", String(x === b))); render();
  });
  sh.radioKeys($("#bbPeriod"));
  $("#bbWatch").onchange = e => { S.watch = e.target.checked; render(); };
  let t; $("#bbQ").oninput = e => { clearTimeout(t); t = setTimeout(() => { S.q = e.target.value.trim(); render(); }, 150); };
  $("#bbSuspect").onclick = () => { S.suspectOnly = !S.suspectOnly; render(); $("#bbSuspect").focus(); };
  $("#bbBody").addEventListener("click", e => {
    const tr = e.target.closest("tr.row");
    if (tr && !e.target.closest("a, button")) toggleRow(tr);
  });
  $("#bbBody").addEventListener("keydown", e => {
    const tr = e.target.closest("tr.row");
    if (!tr || e.target !== tr) return;
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleRow(tr); }
    else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const rows = $$("#bbBody tr.row"), i = rows.indexOf(tr);
      rows[i + (e.key === "ArrowDown" ? 1 : -1)]?.focus();
    }
  });
  let rt; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(render, 200); });
  addEventListener("themechange", render);
  addEventListener("marketchange", render);

  sh.register("geri-alim", {
    onShow() { S.loaded ? render() : load(); },
    async refresh() { await load(true); if (S.error && S.loaded) render(); },
    exports() {
      const has = S.loaded && sh.market !== "US" && inPeriod().some(r => r.kind === "tx");
      return [{ label: "Şirket tablosu (CSV)", hint: `${S.days} gün`, run: exportCompanies, disabled: !has },
        { label: "İşlemler (CSV)", hint: "tek tek bildirimler", run: exportTx, disabled: !has }];
    },
    exportInfo: () => S.loaded ? `Dönem: son ${S.days} gün${S.q ? ` · arama “${S.q}”` : ""}${S.watch ? " · izleme listesi" : ""}${S.suspectOnly ? " · şüpheliler" : ""}` : "",
    exportNote: "Geri alım verisi henüz yüklenmedi",
  });
  // Rozet için arka planda yükle (sekme açık değilse)
  setTimeout(() => { if (!S.loaded) load(); }, 1500);
})();
