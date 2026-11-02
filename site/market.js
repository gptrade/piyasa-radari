/* Lyra Radar — piyasa görselleri: piyasa şeridi, küresel risk rejimi kartı, BIST ısı haritası (treemap), endeks/sektör değerlemesi.
   Veri: data/piyasa.json (radar turu: son değer + eğilim), data/guc/cross.json (akşam: rejim + BIST karşılığı),
   data/guc/guc.json (akşam: hisse getirileri, piyasa değeri, endeks değerlemesi). Bugün ve Piyasa Gücü ekranları kullanır. */
(() => {
  "use strict";
  const sh = window.shell;
  const { esc, fmt } = sh;
  const M = { strip: null, cross: null, guc: null, loading: null };

  async function getJSON(p) {
    try { const r = await fetch(`${p}?t=${Date.now()}`, { cache: "no-store" }); return r.ok ? await r.json() : null; } catch { return null; }
  }
  function load(force = false) {
    if (M.loading && !force) return M.loading;
    M.loading = Promise.all([getJSON("data/piyasa.json"), getJSON("data/guc/cross.json"), getJSON("data/guc/guc.json")])
      .then(([a, b, c]) => { M.strip = a; M.cross = b; M.guc = c; dispatchEvent(new Event("radar:market")); return M; });
    return M.loading;
  }

  const pc = (v, d = 1) => v == null || !isFinite(v) ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${fmt.num(Math.abs(v) * 100, d)}%`;
  const sgn = v => v == null ? "" : v > 0 ? "up" : v < 0 ? "down" : "flat";
  const dlab = iso => { if (!iso) return ""; const [y, m, d] = iso.split("-"); return `${+d} ${["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"][+m - 1]}`; };

  // ─────────────────────────────── eğilim çizgisi
  function spark(vals, cls = "", w = 84, h = 26) {
    const v = (vals || []).filter(x => x != null);
    if (v.length < 2) return "";
    const lo = Math.min(...v), hi = Math.max(...v), r = hi - lo || 1;
    const pts = v.map((x, i) => `${(i / (v.length - 1) * (w - 2) + 1).toFixed(1)},${(h - 2 - (x - lo) / r * (h - 4)).toFixed(1)}`).join(" ");
    return `<svg class="mk-spark ${cls}" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true"><polyline points="${pts}"/></svg>`;
  }

  // ─────────────────────────────── piyasa şeridi
  function stripHTML(keys = null) {
    const d = M.strip;
    if (!d?.items?.length) return "";
    const items = keys ? d.items.filter(i => keys.includes(i.k)) : d.items;
    const val = i => i.k === "us10y" ? `%${fmt.num(i.last, 2)}` : `${i.unit === "$" ? "$" : ""}${fmt.num(i.last, i.dec)}${i.unit === "₺" ? " ₺" : ""}`;
    const chg = i => i.chg_kind === "bp" ? `${i.chg > 0 ? "+" : i.chg < 0 ? "−" : ""}${fmt.num(Math.abs(i.chg) * 100, 0)} bp` : pc(i.chg, 2);
    return `<section class="mk-strip" aria-label="Piyasalar">${items.map(i => {
      const m1 = i.m1 == null ? "" : i.chg_kind === "bp" ? `1 ay ${i.m1 > 0 ? "+" : ""}${fmt.num(i.m1 * 100, 0)} bp` : `1 ay ${pc(i.m1, 1)}`;
      const trend = i.spark?.length > 1 ? (i.spark.at(-1) >= i.spark[0] ? "up" : "down") : "";
      return `<div class="mk-tile" data-tip="${esc(`${i.label} · ${dlab(i.asof)} · ${m1} · çizgi: son 3 ay`)}">
        <span class="mk-l">${esc(i.label)}</span><span class="mk-v">${val(i)}</span>
        <span class="mk-c ${sgn(i.chg)}">${chg(i)}</span>${spark(i.spark, trend)}</div>`;
    }).join("")}</section>`;
  }

  // ─────────────────────────────── küresel risk rejimi
  const XST = { on: ["Risk iştahı yüksek", "up"], mixed: ["Karışık", "warn-t"], off: ["Risk iştahı düşük", "down"] };
  const COMP = [["spx", "S&P 500", 1], ["copper", "Bakır", 1], ["btc", "Bitcoin", 1], ["vix", "VIX (ters)", -1], ["dxy", "Dolar endeksi (ters)", -1], ["us10y", "ABD 10Y faiz (ters)", -1]];
  function crossCard(compact = false) {
    const c = M.cross;
    if (!c?.state) return "";
    const st = XST[c.state] || XST.mixed, t = c.tags || {};
    const bar = (lbl, v) => { const x = Math.max(-2.5, Math.min(2.5, v ?? 0)); const w = Math.abs(x) / 2.5 * 50;
      return `<div class="mk-cb"><span>${lbl}</span><span class="mk-cbt"><i class="${x >= 0 ? "pos" : "neg"}" style="${x >= 0 ? "left:50%" : `left:${50 - w}%`};width:${w}%"></i></span><b class="${sgn(v)}">${v == null ? "—" : fmt.num(v, 1)}</b></div>`; };
    const bt = c.backtest || {}, cur = bt[c.state] || {}, u = cur.xu100usd, tl = cur.xu100;
    const btRow = s => { const r = bt[s] || {}, a = r.xu100usd, b = r.xu100;
      return `<tr class="${s === c.state ? "is-sel" : ""}"><th scope="row">${XST[s][0]}</th><td class="num">${a ? pc(a.mean) : "—"}</td><td class="num">${a ? `%${fmt.num(a.hit * 100, 0)}` : "—"}</td><td class="num">${b ? pc(b.mean) : "—"}</td><td class="num t3">${a?.n ?? 0}</td></tr>`; };
    const tags = [
      t.dolar && `<span class="tag ${t.dolar === "güçleniyor" ? "down" : t.dolar === "zayıflıyor" ? "up" : "na"}">Dolar ${t.dolar}</span>`,
      t.faiz && `<span class="tag ${t.faiz === "yükseliyor" ? "down" : t.faiz === "düşüyor" ? "up" : "na"}">ABD faizi ${t.faiz}${c.us10y_d != null ? ` (${c.us10y_d > 0 ? "+" : ""}${fmt.num(c.us10y_d * 100, 0)} bp)` : ""}</span>`,
      t.altin && `<span class="tag na">Altın ${t.altin}</span>`,
      t.tl && `<span class="tag ${t.tl.fast ? "down" : "na"}" data-tip="USD/TRY son 20 iş günü; son 1 yılın en hızlı %20'lik diliminde ise 'hızlanıyor'">USD/TRY 1 ay ${pc(t.tl.m1, 1)}${t.tl.fast ? " · TL kaybı hızlanıyor" : ""}</span>`,
    ].filter(Boolean).join("");
    const head = `<div class="card-head"><h2 class="card-title" id="mkXT">Küresel risk rejimi · <span class="${st[1]}">${st[0]}</span></h2><span class="card-meta">${dlab(c.asof)}${c.since ? ` · rejim başlangıcı ${dlab(c.since)}` : ""}${compact ? ` · <a href="#piyasa-gucu/kuresel">Ayrıntı →</a>` : ""}</span></div>`;
    const btLine = u ? `<p class="t2 mk-bt">Bu rejimde BIST 100 sonraki 1 ayda <b>dolar bazında ort. ${pc(u.mean)}</b> (yükselen ay %${fmt.num(u.hit * 100, 0)}, TL bazında ${tl ? pc(tl.mean) : "—"}) · ${c.from?.slice(0, 4)}'den bu yana ${u.n} örnek ay</p>` : "";
    if (compact) return `<section class="card mk-x" data-tone="${c.state}" aria-labelledby="mkXT">${head}<div class="gc-sig">${tags}</div>${btLine}</section>`;
    return `<section class="card mk-x" data-tone="${c.state}" aria-labelledby="mkXT">${head}
      <p class="t2">Risk iştahı puanı <b class="${sgn(c.score)}">${fmt.num(c.score, 2)}</b> (≥ +0,5 yüksek, ≤ −0,5 düşük): altı küresel göstergenin 20 günlük değişiminin, son bir yıldaki olağan oynaklığına göre büyüklüğü.</p>
      <div class="res-cols"><div><p class="d-sub">Bileşenler (risk iştahına katkı)</p>${COMP.map(([k, l, w]) => bar(l, c.z?.[k] == null ? null : c.z[k] * w)).join("")}</div>
        <div><p class="d-sub">Diğer işaretler</p><div class="gc-sig">${tags}</div>
          <p class="d-sub">BIST karşılığı · rejim gününden sonraki 1 ay</p>
          <table class="fa-kv mk-btt"><thead><tr><th></th><th class="num">XU100 $</th><th class="num">yükselen</th><th class="num">XU100 ₺</th><th class="num">ay</th></tr></thead><tbody>${["on", "mixed", "off"].map(btRow).join("")}</tbody></table></div></div>
      <p class="t3 gc-foot">Geçmiş ortalama gelecek getirinin garantisi değildir; örtüşmesin diye her 21 iş gününden biri sayılır. ${window.radarMethod?.link("piyasa-gucu", "Yöntem") || ""}</p></section>`;
  }

  // ─────────────────────────────── ısı haritası (iki katmanlı squarified treemap)
  function squarify(items, x, y, w, h) {
    const out = [], tot = items.reduce((s, i) => s + i.v, 0);
    if (!tot || w <= 0 || h <= 0) return out;
    const sc = w * h / tot;
    let rest = items.map(i => ({ ...i, a: i.v * sc })).sort((a, b) => b.a - a.a);
    while (rest.length) {
      const short = Math.min(w, h);
      let row = [rest[0]], best = worst(row, short), k = 1;
      while (k < rest.length) { const nr = [...row, rest[k]], wv = worst(nr, short); if (wv > best) break; row = nr; best = wv; k++; }
      const ra = row.reduce((s, r) => s + r.a, 0), thick = ra / short;
      let off = 0;
      for (const r of row) {
        const len = r.a / thick;
        out.push(w >= h ? { ...r, x, y: y + off, w: thick, h: len } : { ...r, x: x + off, y, w: len, h: thick });
        off += len;
      }
      if (w >= h) { x += thick; w -= thick; } else { y += thick; h -= thick; }
      rest = rest.slice(k);
    }
    return out;
  }
  function worst(row, s) { const a = row.reduce((t, r) => t + r.a, 0), mx = Math.max(...row.map(r => r.a)), mn = Math.min(...row.map(r => r.a)); return Math.max(s * s * mx / (a * a), a * a / (s * s * mn)); }

  const PERK = { d1: ["1G", 0.04], w1: ["1H", 0.08], r1a: ["1A", 0.15], ytd: ["YBB", 0.5] };
  const SHORT = { "GAYRİMENKUL YATIRIM ORTAKLIKLARI": "GYO", "HOLDİNGLER VE YATIRIM ŞİRKETLERİ": "Holding", "KİMYA İLAÇ PETROL LASTİK VE PLASTİK ÜRÜNLER": "Kimya-petrol", "METAL EŞYA MAKİNE ELEKTRİKLİ CİHAZLAR VE ULAŞIM ARAÇLARI": "Metal eşya-makine", "GIDA, İÇECEK VE TÜTÜN": "Gıda-içecek", "ELEKTRİK GAZ VE BUHAR": "Elektrik", "TAŞ VE TOPRAĞA DAYALI SANAYİ": "Taş-toprak", "ULAŞTIRMA VE DEPOLAMA": "Ulaştırma", "TEKSTİL, GİYİM EŞYASI VE DERİ": "Tekstil", "BİLİŞİM": "Bilişim", "BANKALAR": "Bankalar", "ANA METAL SANAYİ": "Ana metal", "PERAKENDE TİCARET": "Perakende", "TOPTAN TİCARET": "Toptan", "SİGORTA ŞİRKETLERİ": "Sigorta", "İNŞAAT VE BAYINDIRLIK İŞLERİ": "İnşaat", "SAVUNMA": "Savunma", "TELEKOMÜNİKASYON": "Telekom", "MADENCİLİK VE TAŞ OCAKÇILIĞI": "Madencilik", "METAL CEVHERİ MADENCİLİĞİ": "Metal cevheri" };
  const short = n => SHORT[n] || n.split(/\s+/).slice(0, 2).join(" ").replace(/\s(VE|İLE)$/, "").toLocaleLowerCase("tr").replace(/(^|\s)\S/g, c => c.toLocaleUpperCase("tr"));
  function color(v, lim) {
    if (v == null) return "var(--surface-2)";
    const t = Math.min(1, Math.abs(v) / lim), p = Math.round(18 + t * 72);
    return `color-mix(in srgb, ${v >= 0 ? "var(--up)" : "var(--down)"} ${p}%, var(--surface-2))`;
  }
  function treemap(el, { per = "d1", sector = null, height = 520, maxStocks = 9999 } = {}) {
    const g = M.guc;
    if (!el || !g?.stocks) return;
    const W = Math.max(300, Math.round(el.getBoundingClientRect().width) || 900), H = height;
    const lim = PERK[per][1];
    const rows = g.stocks.filter(r => r.mcap > 0 && (!sector || r.sector === sector)).sort((a, b) => b.mcap - a.mcap).slice(0, maxStocks);
    const bySec = new Map();
    rows.forEach(r => { if (!bySec.has(r.sector)) bySec.set(r.sector, []); bySec.get(r.sector).push(r); });
    const secs = [...bySec].map(([name, xs]) => ({ name, xs, v: xs.reduce((s, r) => s + r.mcap, 0) }));
    const PAD = 1, HEAD = 15;
    let svg = "";
    for (const s of squarify(secs, 0, 0, W, H)) {
      const ret = s.xs.reduce((a, r) => a + (r[per] ?? 0) * r.mcap, 0) / s.v;
      const lbl = s.w > 60 && s.h > 30;
      const inner = squarify(s.xs.map(r => ({ ...r, v: r.mcap })), s.x + PAD, s.y + (lbl ? HEAD : PAD), s.w - 2 * PAD, s.h - (lbl ? HEAD : PAD) - PAD);
      svg += `<g class="tm-sec" data-sec="${esc(s.name)}"><rect class="tm-sbg" x="${s.x}" y="${s.y}" width="${s.w}" height="${s.h}"/>`;
      if (lbl) svg += `<text class="tm-sl" x="${s.x + 4}" y="${s.y + 11}">${esc(short(s.name))} <tspan class="${sgn(ret)}">${pc(ret, 1)}</tspan></text>`;
      for (const r of inner) {
        const v = r[per], fs = Math.max(8, Math.min(18, Math.sqrt(r.w * r.h) / 4.2));
        svg += `<g class="tm-c" data-tk="${esc(r.code)}"><rect x="${r.x + 0.5}" y="${r.y + 0.5}" width="${Math.max(0, r.w - 1)}" height="${Math.max(0, r.h - 1)}" fill="${color(v, lim)}"><title>${esc(`${r.code} · ${short(r.sector)}\n${PERK[per][0]} ${pc(v, 2)} · piyasa değeri ${fmt.num(r.mcap / 1e9, 1)} mr ₺`)}</title></rect>`;
        if (r.w > 34 && r.h > 18) svg += `<text class="tm-t" x="${r.x + r.w / 2}" y="${r.y + r.h / 2 + (r.h > 34 ? -2 : fs / 3)}" font-size="${fs}">${esc(r.code)}</text>`;
        if (r.w > 38 && r.h > 34) svg += `<text class="tm-v" x="${r.x + r.w / 2}" y="${r.y + r.h / 2 + fs * 0.9}" font-size="${Math.max(8, fs * 0.72)}">${pc(v, 1)}</text>`;
        svg += `</g>`;
      }
      svg += `</g>`;
    }
    el.innerHTML = `<svg class="tm-svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="BIST ısı haritası">${svg}</svg>`;
    el.querySelectorAll(".tm-c").forEach(n => n.addEventListener("click", () => window.radar?.openTicker?.(n.dataset.tk, n)));
  }
  function legend(per) {
    const lim = PERK[per][1];
    return `<span class="tm-leg">${[-1, -0.5, -0.2, 0, 0.2, 0.5, 1].map(t => `<i style="background:${color(t * lim, lim)}">${t === 0 ? "0" : pc(t * lim, 0)}</i>`).join("")}</span>`;
  }

  // ─────────────────────────────── değerleme tablosu
  function valuationTable(kind = "endeks", sort = "mcap") {
    const v = (M.guc?.valuation || []).filter(r => r.kind === kind);
    if (!v.length) return `<p class="t3">Değerleme verisi henüz hesaplanmadı.</p>`;
    const rows = kind === "sektor" ? [...v].sort((a, b) => (b[sort] ?? -1e9) - (a[sort] ?? -1e9)) : v;
    const tl = x => x >= 1e12 ? `${fmt.num(x / 1e12, 2)} tn` : `${fmt.num(x / 1e9, 1)} mr`;
    const bar = (x, mx) => `<span class="mk-vb"><i style="width:${Math.max(2, x / mx * 100)}%"></i></span>`;
    const mx = Math.max(...rows.map(r => r.mcap));
    return `<div class="tbl-scroll"><table class="tx ok-tbl mk-val"><thead><tr><th>${kind === "sektor" ? "Sektör" : "Endeks"}</th><th class="num">Şirket</th><th class="num">Piyasa değeri (₺)</th><th class="num">$</th><th class="num" data-tip="BIST Tüm piyasa değeri içindeki pay">Pay</th>
      <th class="num" data-tip="Σ piyasa değeri / Σ son 12 ay ana ortaklık net kârı (zarar edenler dahil)">F/K</th><th class="num" data-tip="Σ piyasa değeri / Σ ana ortaklık özkaynağı">PD/DD</th><th class="num" data-tip="Σ net kâr / Σ özkaynak (son 12 ay)">Özkaynak kârlılığı</th>
      <th class="num">1A</th><th class="num">3A</th><th class="num">YBB</th><th class="num">1Y</th></tr></thead><tbody>${rows.map(r => `<tr>
        <th scope="row">${esc(kind === "sektor" ? short(r.label) : r.label)}${kind === "sektor" ? `<span class="t3 ok-sub">${esc(r.label)}</span>` : ""}</th><td class="num">${r.n}</td>
        <td class="num">${tl(r.mcap)} ${bar(r.mcap, mx)}</td><td class="num">${r.mcap_usd ? `${fmt.num(r.mcap_usd / 1e9, 1)} mr` : "—"}</td><td class="num">%${fmt.num((r.share || 0) * 100, 1)}</td>
        <td class="num">${r.pe == null ? "—" : fmt.num(r.pe, 1)}</td><td class="num">${r.pb == null ? "—" : fmt.num(r.pb, 2)}</td><td class="num">${r.roe == null ? "—" : `%${fmt.num(r.roe * 100, 1)}`}</td>
        ${["1A", "3A", "YBB", "1Y"].map(k => `<td class="num ${sgn(r.chg?.[k])}">${pc(r.chg?.[k])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }

  window.radarMarket = { load, get data() { return M; }, stripHTML, crossCard, treemap, legend, valuationTable, spark, short, PERK };
  load();
})();
