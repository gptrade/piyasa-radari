/* Piyasa Radarı — "Şirket geri alımları" sekmesi.
   Veri, ayrı repodaki takipçiden gelir (gptrade/kap-geri-alim-takibi → kap-buybacks.json);
   sekme ilk açıldığında bir kez yüklenir. */
(() => {
  "use strict";
  const me = document.currentScript;
  const SRC = me.dataset.src, FALLBACK = me.dataset.fallback;
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const NS = "http://www.w3.org/2000/svg";
  const DAY = 86400000;
  const R = () => window.radar;
  const esc = t => String(t ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const nf = (v, d = 0) => v == null ? "—" : new Intl.NumberFormat("tr-TR", { maximumFractionDigits: d, minimumFractionDigits: d }).format(v);
  const tl = v => {
    if (v == null) return "—";
    const a = Math.abs(v);
    if (a >= 1e9) return nf(v / 1e9, 2) + " mr ₺";
    if (a >= 1e6) return nf(v / 1e6, 1) + " mn ₺";
    if (a >= 1e3) return nf(v / 1e3, 0) + " bin ₺";
    return nf(v, 0) + " ₺";
  };
  const lots = v => v == null ? "—" : v >= 1e6 ? nf(v / 1e6, 2) + " mn" : v >= 1e3 ? nf(v / 1e3, 0) + " bin" : nf(v);
  const pct = (v, d = 1) => v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(d)}%`;
  const cls = v => v == null ? "" : v > 0 ? "pos" : v < 0 ? "neg" : "";

  const S = { rows: null, loaded: false, loading: false, days: 30, q: "", watch: false, sort: "amount", dir: -1, open: new Set(), updated: null };

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
        own: r.ownership_pct_after, pctTx: r.pct_this_transaction, url: r.source_url,
        type: r.notice_type || "", kind: kindOf(r), review: !!r.needs_review, fields: r.raw_fields || {},
      };
    }).filter(r => r.t && r.pub);
  }

  // Ayrıştırma hatası koruması: fiyat, aynı şirketin medyan işlem fiyatından 10 kattan fazla
  // saparsa (ör. fiyat alanına adet yazılmışsa) ya da mantıksız yüksekse işlem şüpheli sayılır,
  // tutarı toplamlara girmez ve tabloda ⚠ ile gösterilir.
  const MAX_PRICE = 50000;
  function flagOutliers(rows) {
    const by = new Map();
    rows.forEach(r => { if (r.kind === "tx" && r.price) (by.get(r.t) || by.set(r.t, []).get(r.t)).push(r.price); });
    const med = new Map([...by].map(([t, ps]) => { const s = ps.slice().sort((a, b) => a - b); return [t, s[Math.floor(s.length / 2)]]; }));
    let n = 0;
    rows.forEach(r => {
      if (r.kind !== "tx" || !r.price) return;
      const m = med.get(r.t);
      const off = r.price > MAX_PRICE || (by.get(r.t).length >= 2 && m && (r.price / m > 10 || r.price / m < 0.1));
      if (off) { r.suspect = true; r.amount = null; n++; }
    });
    return n;
  }
  async function getJSON(url) {
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  }
  async function load() {
    if (S.loaded || S.loading) return;
    S.loading = true;
    let raw = null, src = SRC;
    for (const u of [SRC, FALLBACK]) {
      try { raw = await getJSON(u); src = u; break; } catch { /* sıradaki */ }
    }
    S.loading = false;
    if (!Array.isArray(raw)) {
      $("#bbBody").innerHTML = `<p class="empty">Geri alım verisi alınamadı. Takipçi reposu (kap-geri-alim-takibi) yayında mı?</p>`;
      return;
    }
    S.rows = normalize(raw);
    S.suspect = flagOutliers(S.rows);
    S.src = src;
    S.updated = S.rows.reduce((m, r) => (r.pub > m ? r.pub : m), new Date(0));
    S.loaded = true;
    await Promise.race([R()?.ready, new Promise(r => setTimeout(r, 3000))]);
    render();
    badge();
  }
  function badge() {
    const since = Date.now() - 1 * DAY;
    const n = S.rows.filter(r => r.kind === "tx" && r.pub >= since).length;
    $("#bbBadge").textContent = n ? n : "";
    $("#bbBadge").title = n ? `Son 24 saatte ${n} geri alım işlemi` : "";
  }

  // ─────────────────────────────── hesap
  function watchSet() {
    const st = R()?.state;
    return new Set((st?.feed?.watchlist || []).filter(w => w.market === "BIST").map(w => w.symbol));
  }
  function inPeriod() {
    const cut = Date.now() - S.days * DAY;
    const q = S.q.toLocaleLowerCase("tr");
    const w = watchSet();
    return S.rows.filter(r => r.date >= cut
      && (!S.watch || w.has(r.t))
      && (!q || r.t.toLocaleLowerCase("tr").includes(q) || r.name.toLocaleLowerCase("tr").includes(q)));
  }
  function aggregate(rows) {
    const m = new Map();
    for (const r of rows) {
      if (r.kind !== "tx") continue;
      const o = m.get(r.t) || { t: r.t, name: r.name, n: 0, qty: 0, amount: 0, pq: 0, last: null, own: null, ownAt: null, tx: [], review: 0 };
      o.n++; o.qty += r.qty || 0; o.amount += r.amount || 0;
      if (r.amount) o.pq += r.qty;
      if (r.suspect) o.suspect = (o.suspect || 0) + 1;
      if (!o.last || r.date > o.last) o.last = r.date;
      if (r.own != null && (!o.ownAt || r.pub > o.ownAt)) { o.own = r.own; o.ownAt = r.pub; }
      o.review += r.review ? 1 : 0;
      o.tx.push(r);
      m.set(r.t, o);
    }
    const st = R()?.state;
    return [...m.values()].map(o => {
      o.avg = o.pq ? o.amount / o.pq : null;
      const p = st?.prices?.[o.t];
      o.px = p?.last ?? null;
      o.prem = o.px && o.avg ? (o.px / o.avg - 1) * 100 : null;
      o.tx.sort((a, b) => b.date - a.date);
      return o;
    });
  }

  // ─────────────────────────────── çizim
  function kpis(rows, agg) {
    const tx = rows.filter(r => r.kind === "tx");
    const prog = rows.filter(r => r.kind === "program");
    const total = tx.reduce((s, r) => s + (r.amount || 0), 0);
    const top = agg.slice().sort((a, b) => b.amount - a.amount)[0];
    return `<div class="kpis">
      <div><small>Geri alım yapan şirket</small><b>${agg.length}</b></div>
      <div><small>İşlem bildirimi</small><b>${tx.length}</b></div>
      <div><small>Toplam tutar</small><b>${tl(total)}</b></div>
      <div><small>En çok alan</small><b>${top ? esc(top.t) : "—"}</b>${top ? `<span>${tl(top.amount)}</span>` : ""}</div>
      <div><small>Yeni program / YK kararı</small><b>${prog.length}</b></div>
    </div>`;
  }

  function dailyChart(rows, W) {
    const byDay = new Map();
    const key = d => d.toISOString().slice(0, 10);
    const end = new Date(); end.setUTCHours(12, 0, 0, 0);
    for (let i = S.days - 1; i >= 0; i--) byDay.set(key(new Date(end - i * DAY)), { amount: 0, n: 0, cos: new Set() });
    for (const r of rows) {
      if (r.kind !== "tx" || !r.amount) continue;
      const o = byDay.get(key(r.date));
      if (o) { o.amount += r.amount; o.n++; o.cos.add(r.t); }
    }
    // hafta sonlarını (işlem yok) çıkar: sadece hafta içi günler
    const days = [...byDay.entries()].filter(([k]) => { const g = new Date(k + "T12:00:00Z").getUTCDay(); return g !== 0 && g !== 6; });
    const H = 160, padL = 58, padB = 20, padT = 10;
    const short = v => v >= 1e9 ? nf(v / 1e9, 1) + " mr" : v >= 1e6 ? nf(v / 1e6, v >= 1e8 ? 0 : 1) + " mn" : v >= 1e3 ? nf(v / 1e3, 0) + " bin" : nf(v);
    const max = Math.max(1, ...days.map(([, o]) => o.amount));
    const bw = (W - padL) / days.length;
    const gap = Math.min(2, bw * 0.2);
    const y = v => H - padB - (v / max) * (H - padB - padT);
    let bars = "";
    days.forEach(([k, o], i) => {
      const x = padL + i * bw + gap / 2, w = Math.max(1, bw - gap), top = y(o.amount), h = H - padB - top;
      const r = Math.min(4, w / 2, h);
      const d = new Date(k + "T12:00:00Z").toLocaleDateString("tr-TR", { day: "2-digit", month: "short" });
      const tip = `<b>${d}</b><br>${tl(o.amount)} · ${o.n} işlem · ${o.cos.size} şirket` + (o.cos.size ? `<br>${esc([...o.cos].slice(0, 8).join(", "))}${o.cos.size > 8 ? "…" : ""}` : "");
      // üstü yuvarlatılmış, tabana oturan çubuk
      const path = h > 0 ? `M${x},${H - padB} V${top + r} Q${x},${top} ${x + r},${top} H${x + w - r} Q${x + w},${top} ${x + w},${top + r} V${H - padB} Z` : "";
      bars += `<g class="bb-bar" data-tip="${esc(tip)}"><rect x="${x - gap / 2}" y="${padT}" width="${bw}" height="${H - padB - padT}" class="hit"/>${path ? `<path d="${path}"/>` : ""}</g>`;
    });
    const ticks = [0, 0.5, 1].map(f => `<line x1="${padL}" x2="${W}" y1="${y(max * f)}" y2="${y(max * f)}" class="grid"/><text x="${padL - 6}" y="${y(max * f) + 3}" text-anchor="end" class="ax">${f ? short(max * f) : "0"}</text>`).join("");
    const step = Math.ceil(days.length / Math.max(3, Math.floor(W / 80)));
    const xl = days.map(([k], i) => i % step ? "" : `<text x="${padL + i * bw + bw / 2}" y="${H - 5}" text-anchor="middle" class="ax">${new Date(k + "T12:00:00Z").toLocaleDateString("tr-TR", { day: "2-digit", month: "2-digit" })}</text>`).join("");
    return `<section class="panel bb-chart"><div class="panel-head"><h3>Günlük geri alım tutarı</h3><span class="hint">işlem tarihine göre · ₺</span></div>
      <svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Son ${S.days} günün günlük geri alım tutarları">${ticks}${bars}${xl}</svg></section>`;
  }

  const COLS = [
    ["t", "Hisse"], ["name", "Şirket"], ["n", "İşlem"], ["qty", "Toplam adet"], ["amount", "Tutar"],
    ["avg", "Ort. fiyat"], ["prem", "Güncel / ort."], ["own", "Sermaye payı"], ["last", "Son işlem"],
  ];
  function table(agg) {
    const w = watchSet();
    const k = S.sort, dir = S.dir;
    agg.sort((a, b) => {
      const va = a[k], vb = b[k];
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      return (typeof va === "string" ? va.localeCompare(vb, "tr") : va - vb) * dir;
    });
    const head = COLS.map(([c, l]) => `<th data-c="${c}" class="${c === k ? "on" : ""} ${["t", "name"].includes(c) ? "" : "num"}" aria-sort="${c === k ? (dir > 0 ? "ascending" : "descending") : "none"}">${l}${c === k ? (dir > 0 ? " ▲" : " ▼") : ""}</th>`).join("");
    const body = agg.map(o => {
      const open = S.open.has(o.t);
      const sub = open ? `<tr class="sub"><td colspan="${COLS.length}">${txList(o)}</td></tr>` : "";
      return `<tr class="co ${open ? "open" : ""} ${w.has(o.t) ? "mine" : ""}" data-t="${esc(o.t)}" tabindex="0" aria-expanded="${open}">
        <td class="tk">${esc(o.t)}${w.has(o.t) ? ` <span class="mine-dot" title="İzleme listende">●</span>` : ""}</td>
        <td class="nm" title="${esc(o.name)}">${esc(o.name)}</td>
        <td class="num">${o.n}${o.review || o.suspect ? ` <span class="rv" title="${[o.suspect ? o.suspect + " işlemde fiyat şüpheli (toplamlara katılmadı)" : "", o.review ? o.review + " bildirim elle kontrol istiyor" : ""].filter(Boolean).join(" · ")}">⚠</span>` : ""}</td>
        <td class="num">${lots(o.qty)}</td>
        <td class="num"><b>${tl(o.amount)}</b></td>
        <td class="num">${o.avg ? nf(o.avg, 2) : "—"}</td>
        <td class="num ${cls(o.prem)}" title="${o.px ? `Güncel ${nf(o.px, 2)} ₺` : "Fiyat sadece izleme listesindeki hisseler için"}">${o.prem == null ? "—" : pct(o.prem)}</td>
        <td class="num">${o.own == null ? "—" : "%" + nf(o.own, 2)}</td>
        <td class="num">${o.last ? o.last.toLocaleDateString("tr-TR", { day: "2-digit", month: "short" }) : "—"}</td>
      </tr>${sub}`;
    }).join("");
    return `<section class="panel bb-table"><div class="panel-head"><h3>Şirket bazında (${agg.length})</h3><span class="hint">satıra tıkla: işlemler · başlığa tıkla: sırala</span></div>
      <div class="tbl-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body || `<tr><td colspan="${COLS.length}" class="empty">Bu dönemde geri alım işlemi yok.</td></tr>`}</tbody></table></div></section>`;
  }
  function txList(o) {
    return `<table class="tx"><thead><tr><th>İşlem tarihi</th><th class="num">Fiyat</th><th class="num">Adet</th><th class="num">Tutar</th><th class="num">Sermaye payı</th><th>Bildirim</th></tr></thead><tbody>` +
      o.tx.map(r => `<tr><td>${r.date.toLocaleDateString("tr-TR", { day: "2-digit", month: "short", year: "numeric" })}</td>
        <td class="num ${r.suspect ? "rv" : ""}" title="${r.suspect ? "Fiyat şüpheli: şirketin diğer işlemlerinden çok farklı; KAP bildirimini kontrol et" : ""}">${r.price ? nf(r.price, 3) : "—"}${r.suspect ? " ⚠" : ""}</td><td class="num">${nf(r.qty)}</td><td class="num">${r.suspect ? "—" : tl(r.amount)}</td>
        <td class="num">${r.own == null ? "—" : "%" + nf(r.own, 2)}</td>
        <td>${r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener">KAP ${r.id}</a>` : r.id}${r.review ? ` <span class="rv" title="Ayrıştırma elle kontrol istiyor">⚠</span>` : ""}</td></tr>`).join("") +
      `</tbody></table>`;
  }
  function programs(rows) {
    const p = rows.filter(r => r.kind !== "tx").sort((a, b) => b.pub - a.pub).slice(0, 30);
    if (!p.length) return "";
    const w = watchSet();
    return `<section class="panel bb-prog"><div class="panel-head"><h3>Program başlatma, YK kararı ve diğer bildirimler</h3><span class="hint">${p.length} kayıt</span></div>
      <ul>${p.map(r => {
        const f = r.fields || {};
        const size = f["geri alıma konu azami pay miktarı (nominal tl)"] || f["geri alıma konu azami pay miktarı"];
        const dur = f["varsa geri alım programının uygulanacağı süre"];
        return `<li class="${w.has(r.t) ? "mine" : ""}"><span class="tk">${esc(r.t)}</span>
          <span class="pt ${r.kind}">${r.kind === "program" ? "Program" : r.kind === "end" ? "Tamamlandı" : "Diğer"}</span>
          <a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.type)}</a>
          ${size ? `<span class="meta">azami ${esc(size)} nominal</span>` : ""}${dur ? `<span class="meta">${esc(dur)}</span>` : ""}
          <time>${r.pub.toLocaleDateString("tr-TR", { day: "2-digit", month: "short" })}</time></li>`;
      }).join("")}</ul></section>`;
  }

  function render() {
    if (!S.loaded || $("#buybackView").hidden) return;     // gizliyken çizme: genişlik ölçülemez
    const rows = inPeriod();
    const agg = aggregate(rows);
    const W = Math.max(280, Math.round(($("#bbBody").getBoundingClientRect().width || 720) - 30));
    const fr = R()?.fmtTime ? R().fmtTime(S.updated.toISOString()) : S.updated.toLocaleString("tr-TR");
    $("#bbBody").innerHTML = `
      <p class="bb-src">Veri: <a href="https://github.com/gptrade/kap-geri-alim-takibi" target="_blank" rel="noopener">kap-geri-alim-takibi</a> · son bildirim ${fr} · ${S.rows.length} kayıt${S.suspect ? ` · <span class="rv">${S.suspect} işlemde fiyat şüpheli, toplamlara katılmadı</span>` : ""}</p>
      ${kpis(rows, agg)}
      ${dailyChart(rows, W)}
      ${table(agg)}
      ${programs(rows)}`;
    $$("#bbBody th[data-c]").forEach(th => th.onclick = () => {
      const c = th.dataset.c;
      S.dir = S.sort === c ? -S.dir : (["t", "name"].includes(c) ? 1 : -1);
      S.sort = c; render();
    });
    $$("#bbBody tr.co").forEach(tr => {
      const go = () => { const t = tr.dataset.t; S.open.has(t) ? S.open.delete(t) : S.open.add(t); render(); };
      tr.onclick = go;
      tr.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } };
    });
    $$("#bbBody .tx a, #bbBody .bb-prog a").forEach(a => a.onclick = e => e.stopPropagation());
  }

  // ─────────────────────────────── sekmeler
  function show(tab) {
    const bb = tab === "buybacks";
    document.body.classList.toggle("bb", bb);
    $("#signalsView").hidden = bb;
    $("#buybackView").hidden = !bb;
    $$(".tabs button").forEach(b => { const on = b.dataset.tab === tab; b.classList.toggle("on", on); b.setAttribute("aria-selected", on); });
    if (bb) { if (S.loaded) render(); else load(); } else dispatchEvent(new Event("resize"));   // sağ kolon yeniden görünür: balon haritası genişliğini yenile
    const h = bb ? "#geri-alim" : "";
    if (location.hash !== h) history.replaceState(null, "", h || location.pathname + location.search);
  }
  $$(".tabs button").forEach(b => b.onclick = () => show(b.dataset.tab));
  $$("#bbPeriod button").forEach(b => b.onclick = () => {
    S.days = +b.dataset.d; $$("#bbPeriod button").forEach(x => x.classList.toggle("on", x === b)); render();
  });
  $("#bbWatch").onchange = e => { S.watch = e.target.checked; render(); };
  let t; $("#bbQ").oninput = e => { clearTimeout(t); t = setTimeout(() => { S.q = e.target.value.trim(); render(); }, 150); };
  let rt; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => { if (!$("#buybackView").hidden) render(); }, 200); });
  if (location.hash === "#geri-alim") show("buybacks");
  else setTimeout(load, 1500);            // arka planda yükle: sekme rozeti için
})();
