/* Lyra Radar — piyasa görselleri: piyasa şeridi, küresel risk rejimi kartı, BIST ısı haritası (treemap), endeks/sektör değerlemesi.
   Veri: data/piyasa.json (radar turu: son değer + eğilim), data/guc/cross.json (akşam: rejim + BIST karşılığı),
   data/guc/guc.json (akşam: hisse getirileri, piyasa değeri, endeks değerlemesi). Bugün ve Piyasa Gücü ekranları kullanır. */
(() => {
  "use strict";
  const sh = window.shell;
  const { esc, fmt } = sh;
  const M = { strip: null, cross: null, guc: null, us: null, loading: null };

  async function getJSON(p) {
    try { const r = await fetch(`${p}?t=${Date.now()}`, { cache: "no-store" }); return r.ok ? await r.json() : null; } catch { return null; }
  }
  function load(force = false) {
    if (M.loading && !force) return M.loading;
    M.loading = Promise.all([getJSON("data/piyasa.json"), getJSON("data/guc/cross.json"), getJSON("data/guc/guc.json"), getJSON("data/us_map.json")])
      .then(([a, b, c, d]) => { M.strip = a; M.cross = b; M.guc = c; M.us = d; dispatchEvent(new Event("radar:market")); return M; });
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
  // TCMB ağırlıklı ortalama fonlama maliyeti: EVDS (data/macro.json, radar turu) → şerit kutusu
  function fundingItem() {
    const s = (window.radar?.state?.macro?.series || []).find(x => x.code === "TP.APIFON4");
    if (!s || s.last == null) return null;
    const h = (s.history || []).map(x => x[1]).filter(v => v != null);
    const iso = (s.date || "").split("-").reverse().join("-");
    const m1 = h.length > 22 ? s.last - h[h.length - 23] : null;
    return { k: "fon", label: "TCMB fonlama", unit: "%", dec: 2, last: s.last, chg: s.change, chg_kind: "bp", m1, asof: iso, spark: h.slice(-44), src: "TCMB EVDS · ağırlıklı ortalama fonlama maliyeti" };
  }
  // Mantıksal gruplar: Türkiye (kur, faiz, borsa, altın) · Küresel piyasalar · Emtia ve kripto
  const GROUPS = [["Türkiye", ["usdtry", "eurtry", "fon", "xu100", "xu100usd", "gram"]], ["Küresel", ["spx", "ndx", "dji", "vix", "us10y", "dxy"]], ["Emtia ve kripto", ["brent", "gold", "btc"]]];
  function stripHTML(keys = null, { groups = false } = {}) {
    const d = M.strip;
    if (!d?.items?.length) return "";
    const pool = [...d.items, fundingItem()].filter(Boolean);
    const items = keys ? pool.filter(i => keys.includes(i.k)) : d.items;
    const pct = i => i.k === "us10y" || i.k === "fon";
    const val = i => pct(i) ? `%${fmt.num(i.last, 2)}` : `${i.unit === "$" ? "$" : ""}${fmt.num(i.last, i.dec)}${i.unit === "₺" ? " ₺" : ""}`;
    const bp = v => `${v > 0 ? "+" : v < 0 ? "−" : ""}${fmt.num(Math.abs(v) * 100, 0)} bp`;
    const chg = i => i.chg == null ? "—" : i.chg_kind === "bp" ? bp(i.chg) : pc(i.chg, 2);
    const tile = i => {
      const m1 = i.m1 == null ? "" : i.chg_kind === "bp" ? `1 ay ${bp(i.m1)}` : `1 ay ${pc(i.m1, 1)}`;
      const trend = i.spark?.length > 1 ? (i.spark.at(-1) >= i.spark[0] ? "up" : "down") : "";
      const fut = ["brent", "gold", "copper", "gram"].includes(i.k) ? " · vadeli işlem fiyatı (yakın kontrat): ay sonu kontrat devrinde tek günlük sıçrama olabilir" : "";
      const cc = sgn(i.chg);
      return `<div class="mk-tile" data-tip="${esc(`${i.label} · ${dlab(i.asof)} · ${m1} · çizgi: son 3 ay${fut}${i.src ? ` · ${i.src}` : ""}`)}">
        <span class="mk-l">${esc(i.label)}</span><span class="mk-v">${val(i)}</span>
        <span class="mk-c ${cc}">${chg(i)}</span>${spark(i.spark, trend)}</div>`;
    };
    if (groups) {
      const by = new Map(items.map(i => [i.k, i]));
      return `<section class="mk-strip mk-groups" aria-label="Piyasalar">${GROUPS.map(([g, ks]) => { const xs = ks.map(k => by.get(k)).filter(Boolean);
        return xs.length ? `<div class="mk-grp" style="--n:${xs.length}"><h3 class="mk-gh">${esc(g)}</h3><div class="mk-gt">${xs.map(tile).join("")}</div></div>` : ""; }).join("")}</section>`;
    }
    return `<section class="mk-strip" aria-label="Piyasalar">${items.map(i => {
      const m1 = i.m1 == null ? "" : i.chg_kind === "bp" ? `1 ay ${i.m1 > 0 ? "+" : ""}${fmt.num(i.m1 * 100, 0)} bp` : `1 ay ${pc(i.m1, 1)}`;
      const trend = i.spark?.length > 1 ? (i.spark.at(-1) >= i.spark[0] ? "up" : "down") : "";
      const fut = ["brent", "gold", "copper", "gram"].includes(i.k) ? " · vadeli işlem fiyatı (yakın kontrat): ay sonu kontrat devrinde tek günlük sıçrama olabilir" : "";
      return `<div class="mk-tile" data-tip="${esc(`${i.label} · ${dlab(i.asof)} · ${m1} · çizgi: son 3 ay${fut}`)}">
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
  const US_SEC = { "Information Technology": "Teknoloji", "Communication Services": "İletişim", "Consumer Discretionary": "Tüketici (döngüsel)", "Consumer Staples": "Temel tüketim",
    "Health Care": "Sağlık", "Financials": "Finans", "Industrials": "Sanayi", "Energy": "Enerji", "Materials": "Malzeme", "Real Estate": "Gayrimenkul", "Utilities": "Kamu hizmetleri" };
  const short = n => US_SEC[n] || SHORT[n] || n.split(/\s+/).slice(0, 2).join(" ").replace(/\s(VE|İLE)$/, "").toLocaleLowerCase("tr").replace(/(^|\s)\S/g, c => c.toLocaleUpperCase("tr"));
  // |değişim| < %0,05 (işlem görmeyen ya da yatay) nötr gri: sıfır yeşile boyanmasın
  const FLAT = 0.0005;
  function color(v, lim) {
    if (v == null) return "var(--surface-2)";
    if (Math.abs(v) < FLAT) return "color-mix(in srgb, var(--text-3) 22%, var(--surface-2))";
    const t = Math.min(1, Math.abs(v) / lim), p = Math.round(22 + t * 68);
    return `color-mix(in srgb, ${v >= 0 ? "var(--up)" : "var(--down)"} ${p}%, var(--surface-2))`;
  }
  // Halka açıklığı çok düşük, pratikte işlem görmeyen hisseler (QNBTR, ENPRA…): günlük işlem hacmi (20 gün medyanı)
  // piyasa değerinin %0,01'inden azsa "piyasa değeri" boyutunda haritayı domine etmesin diye dışarıda kalır.
  const THIN = 1e-4;
  const thin = r => r.tv != null && r.mcap > 0 && r.tv / r.mcap < THIN;
  function treemap(el, { per = "d1", sector = null, height = 520, maxStocks = 9999, src = "bist", size = "mcap" } = {}) {
    const us = src === "us" || src === "sp" || src === "ndx", ix = src === "ndx" ? "ndx" : "sp", g = us ? M.us : M.guc;
    if (!el || !g?.stocks) { if (el) el.innerHTML = `<p class="t3">${us ? "ABD ısı haritası verisi henüz oluşmadı; ilk radar turundan sonra gelir." : "Isı haritası verisi yok."}</p>`; return; }
    const W = Math.max(300, Math.round(el.getBoundingClientRect().width) || 900), H = height;
    const lim = PERK[per][1];
    const byTv = !us && size === "tv", sz = r => byTv ? r.tv : r.mcap;
    const base = g.stocks.filter(r => r.mcap > 0 && (!sector || r.sector === sector) && (!us || (r.ix || ["sp"]).includes(ix)));
    const out = us || byTv ? [] : base.filter(thin).sort((a, b) => b.mcap - a.mcap);
    const rows = base.filter(r => sz(r) > 0 && !out.includes(r)).sort((a, b) => sz(b) - sz(a)).slice(0, maxStocks);
    const bySec = new Map();
    rows.forEach(r => { if (!bySec.has(r.sector)) bySec.set(r.sector, []); bySec.get(r.sector).push(r); });
    const secs = [...bySec].map(([name, xs]) => ({ name, xs, v: xs.reduce((s, r) => s + sz(r), 0), mc: xs.reduce((s, r) => s + r.mcap, 0) }));
    const secRet = new Map();
    for (const [name] of bySec) { const xs = base.filter(r => r.sector === name), mc = xs.reduce((a, r) => a + r.mcap, 0); secRet.set(name, xs.reduce((a, r) => a + (r[per] ?? 0) * r.mcap, 0) / mc); }
    const PAD = 1, HEAD = 15;
    let svg = "";
    for (const s of squarify(secs, 0, 0, W, H)) {
      const ret = secRet.get(s.name);      // sektör getirisi her zaman tüm hisselerle, piyasa değeri ağırlıklı (gizlenen sığ hisseler dahil)
      const lbl = s.w > 60 && s.h > 30;
      const inner = squarify(s.xs.map(r => ({ ...r, v: sz(r) })), s.x + PAD, s.y + (lbl ? HEAD : PAD), s.w - 2 * PAD, s.h - (lbl ? HEAD : PAD) - PAD);
      svg += `<g class="tm-sec" data-sec="${esc(s.name)}"><rect class="tm-sbg" x="${s.x}" y="${s.y}" width="${s.w}" height="${s.h}"/>`;
      if (lbl) svg += `<text class="tm-sl" x="${s.x + 4}" y="${s.y + 11}">${esc(short(s.name))} <tspan class="${sgn(ret)}">${pc(ret, 1)}</tspan></text>`;
      for (const r of inner) {
        const v = r[per], fs = Math.max(8, Math.min(18, Math.sqrt(r.w * r.h) / 4.2));
        svg += `<g class="tm-c" data-tk="${esc(r.code)}"><rect x="${r.x + 0.5}" y="${r.y + 0.5}" width="${Math.max(0, r.w - 1)}" height="${Math.max(0, r.h - 1)}" fill="${color(v, lim)}"><title>${esc(`${r.code}${r.name ? " · " + r.name : ""} · ${short(r.sector)}\n${PERK[per][0]} ${pc(v, 2)} · piyasa değeri ${us ? `${fmt.num(r.mcap / 1e9, 0)} mr $` : `${fmt.num(r.mcap / 1e9, 1)} mr ₺`}${!us && r.tv != null ? ` · günlük işlem ${fmt.num(r.tv / 1e6, r.tv < 1e7 ? 1 : 0)} mn ₺` : ""}`)}</title></rect>`;
        if (r.w > 34 && r.h > 18) svg += `<text class="tm-t" x="${r.x + r.w / 2}" y="${r.y + r.h / 2 + (r.h > 34 ? -2 : fs / 3)}" font-size="${fs}">${esc(r.code)}</text>`;
        if (r.w > 38 && r.h > 34) svg += `<text class="tm-v" x="${r.x + r.w / 2}" y="${r.y + r.h / 2 + fs * 0.9}" font-size="${Math.max(8, fs * 0.72)}">${pc(v, 1)}</text>`;
        svg += `</g>`;
      }
      svg += `</g>`;
    }
    const note = out.length ? `<p class="tm-ex t3">Çok sığ işlem gördüğü için bu boyutta gösterilmeyen (günlük işlem hacmi piyasa değerinin %0,01'inden az; halka açıklık çok düşük): ${out.slice(0, 10).map(r => `<button type="button" class="tm-exb" data-tk="${esc(r.code)}">${esc(r.code)}</button> <span>${pc(r[per], 1)}</span>`).join(" · ")}${out.length > 10 ? ` ve ${out.length - 10} hisse` : ""}</p>` : "";
    el.innerHTML = `<svg class="tm-svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${us ? (ix === "ndx" ? "Nasdaq-100" : "S&P 500") : "BIST"} ısı haritası">${svg}</svg>${note}`;
    el.querySelectorAll(".tm-exb").forEach(n => n.addEventListener("click", () => window.radar?.openTicker?.(n.dataset.tk, n)));
    el.querySelectorAll(".tm-c").forEach(n => n.addEventListener("click", () => us ? window.open(`https://finance.yahoo.com/quote/${n.dataset.tk.replace(".", "-")}/`, "_blank", "noopener") : window.radar?.openTicker?.(n.dataset.tk, n)));
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

  window.radarMarket = { load, get data() { return M; }, GROUPS, stripHTML, crossCard, treemap, legend, valuationTable, spark, short, PERK };
  load();
})();
