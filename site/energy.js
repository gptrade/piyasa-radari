/* Piyasa Radarı — Enerji: Türkiye elektrik üretim şirketlerinin kurulu güç envanteri.
   Veri: data/enerji/kurulu_guc.json (enerji.yml). Santral, konum ve sahiplik: Global Energy Monitor (Integrated Power + Ownership
   Tracker, CC BY 4.0); Türkiye bağlamı: EPİAŞ Şeffaflık (YEKDEM); yatırım bildirimleri: KAP.
   Grup MW'ı pay oranına göredir (ortaklık payı × ünite gücü); konsolide = %50+ payla kontrol edilen ünitelerin tam gücü.
   Türk gruplarının yurt dışındaki santralleri ayrı tutulur, Türkiye toplamlarına katılmaz.
   Alt sekmeler: #enerji (genel bakış) · #enerji/harita · #enerji/gruplar · #enerji/santraller · #enerji/yatirimlar */
(() => {
  "use strict";
  const sh = window.shell;
  const { $, $$, esc, fmt, fold } = sh;
  const SRC = "data/enerji/kurulu_guc.json";
  const PAGE = 25, UPAGE = 50;
  const KINDS = { all: "Tümü", listed: "Borsada", private: "Borsa dışı", kamu: "Kamu" };
  const TABS = [["", "Genel bakış"], ["harita", "Harita"], ["gruplar", "Gruplar"], ["santraller", "Santraller"], ["yatirimlar", "Yatırımlar"], ["degerleme", "Değerleme"]];
  const PIPE = new Set(["construction", "pre-construction", "announced", "pre-permit", "permitted"]);
  const RENEW = ["hidro", "ruzgar", "gunes", "jeotermal", "diger"];

  const S = { doc: null, loaded: false, loading: false, error: null, missing: false,
    q: "", kind: "all", src: "", kapType: "", kapLimit: 15, sort: "total", dir: -1, open: new Set(), limit: PAGE, recLimit: 12, pipeLimit: 12,
    scope: "tr", st: "op", usort: "mw", udir: -1, ulimit: UPAGE, group: "", mapView: "units", focus: null, year: null };
  const Y0 = 1980;                                                 // zaman çubuğunun başı (öncesi ilk karede birlikte görünür)

  // ─────────────────────────────── birimler
  const mw = v => v == null ? "—" : fmt.num(v, v >= 100 ? 0 : 1);
  const gw = v => v == null ? "—" : fmt.num(v / 1000, 1) + " GW";
  const pct = (v, d = 1) => v == null ? "—" : "%" + fmt.num(v * 100, d);
  const color = s => `var(--en-${s})`;
  const sum = o => Object.values(o || {}).reduce((a, b) => a + b, 0);
  const tab = () => TABS.some(([k]) => k === sh.param) ? sh.param : "";

  async function load(force = false) {
    if (S.loading || (S.loaded && !force)) return;
    S.loading = true; S.error = null; S.missing = false;
    if (!S.loaded) renderLoading();
    try {
      const r = await fetch(`${SRC}?t=${Date.now()}`, { cache: "no-store" });
      if (r.status === 404) { S.missing = true; throw new Error("veri yok"); }
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      S.doc = prepare(await r.json());
      S.loaded = true;
      if (Map_.map) Map_.reset();
      sh.setUpdated("enerji", new Date(S.doc.generated), { label: "Enerji verisi", staleMin: 60 * 24 * 9 });
    } catch (e) {
      S.error = e.message || "veri okunamadı";
    } finally { S.loading = false; }
    S.loaded ? render() : renderError();
  }

  function prepare(d) {
    const nat = d.national.total || 1;
    d.top10 = d.groups.slice(0, 10).reduce((s, g) => s + g.total, 0) / nat;
    d.owners = d.units.map(() => []);                       // ünite → [[grup, pay]]
    d.groups.forEach((g, i) => {
      g.code = g.ticker || g.parent || ""; g.rank = i + 1;
      g.abroad = g.abroad || {}; g.abroad_total = g.abroad_total || 0; g.abroad_pipe = g.abroad_pipe || 0; g.countries = g.countries || [];
      g.units.forEach(([u, s]) => d.owners[u].push([g, s]));
    });
    d.byKey = new Map(d.groups.map(g => [g.key, g]));
    d.units.forEach((u, i) => {
      u.i = i;
      u.ab = !!u.cn;
      u.q = fold([u.n, u.en, u.o, u.pa, u.p, u.ci, u.cn, ...d.owners[i].map(([g]) => g.name + " " + g.code)].filter(Boolean).join(" "));
    });
    d.abroadN = d.units.filter(u => u.ab && u.st === "operating").length;
    d.countryList = [...new Set(d.units.filter(u => u.ab).map(u => u.cn))];
    return d;
  }
  const kindOf = g => g.kind === "kamu" ? "kamu" : g.ticker || g.parent ? "listed" : "private";
  const ownerLabel = (i, n = 2) => {
    const os = S.doc.owners[i].slice().sort((a, b) => b[1] - a[1]);
    if (!os.length) return `<span class="meta">sahip bilgisi yok</span>`;
    return os.slice(0, n).map(([g, s]) =>
      `${esc(g.name)}${g.ticker ? ` <a href="#hisse/${esc(g.ticker)}" class="en-code">${esc(g.ticker)}</a>` : g.parent ? ` <a href="#hisse/${esc(g.parent)}" class="en-code parent">↳ ${esc(g.parent)}</a>` : ""}${s < 0.999 ? ` <span class="meta">${pct(s, 0)}</span>` : ""}`).join(" · ") +
      (os.length > n ? ` <span class="meta">+${os.length - n}</span>` : "");
  };
  const place = u => u.ab ? `${esc(u.cn)}${u.p ? ` <span class="meta">${esc(u.p)}</span>` : ""}` : esc(u.p || "");

  // ─────────────────────────────── süzme
  function filtered() {
    const d = S.doc, q = fold(S.q);
    let rows = d.groups.filter(g => S.kind === "all" || kindOf(g) === S.kind);
    rows.forEach(g => {
      g.srcMw = S.src ? g.src[S.src] || 0 : g.total; g.srcPipe = S.src ? g.pipe[S.src] || 0 : g.pipe_total;
      g.srcAb = S.src ? g.abroad[S.src] || 0 : g.abroad_total;
    });
    if (S.src) rows = rows.filter(g => g.srcMw > 0 || g.srcPipe > 0 || g.srcAb > 0);
    if (q) rows = rows.filter(g => fold(g.name).includes(q) || fold(g.code).includes(q) ||
      g.entities.some(n => fold(n).includes(q)) || g.units.some(([u]) => d.units[u].q.includes(q)));
    const k = S.sort === "total" ? "srcMw" : S.sort === "pipe_total" ? "srcPipe" : S.sort === "abroad_total" ? "srcAb" : S.sort;
    return rows.sort((a, b) => {
      const va = a[k], vb = b[k];
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      return (typeof va === "string" ? va.localeCompare(vb, "tr") : va - vb) * S.dir;
    });
  }
  const stOk = u => S.st === "all" || (S.st === "op" ? u.st === "operating" : PIPE.has(u.st));
  const scopeOk = u => S.scope === "all" || (S.scope === "ab" ? u.ab : !u.ab);
  const kindOk = u => S.kind === "all" || S.doc.owners[u.i].some(([g]) => kindOf(g) === S.kind);
  function unitsFiltered({ group = true, st = true } = {}) {
    const d = S.doc, q = fold(S.q), g = group && S.group ? d.byKey.get(S.group) : null;
    const only = g ? new Set(g.units.map(([i]) => i)) : null;
    return d.units.filter(u => (!only || only.has(u.i)) && (!S.src || u.s === S.src) && (!st || stOk(u)) && scopeOk(u) && kindOk(u) && (!q || u.q.includes(q)));
  }

  // ─────────────────────────────── ortak parçalar
  function mixBar(src, total, { h = 10, on = "" } = {}) {
    const d = S.doc;
    if (!total) return "";
    const ks = d.sources.filter(s => src[s] > 0);
    return `<span class="en-mix" style="height:${h}px" role="img" aria-label="${esc(ks.map(s => `${d.source_names[s]} ${pct(src[s] / total, 0)}`).join(", "))}">${ks.map(s =>
      `<span class="${on && on !== s ? "off" : ""}" style="width:${(src[s] / total * 100).toFixed(2)}%;background:${color(s)}" data-tip="${esc(`${d.source_names[s]}: ${mw(src[s])} MW (${pct(src[s] / total)})`)}"></span>`).join("")}</span>`;
  }
  function legend(src, total, on = "") {
    const d = S.doc;
    return `<div class="en-legend">${d.sources.filter(s => src[s] > 0).map(s =>
      `<span class="${on && on !== s ? "off" : on === s ? "on" : ""}"><i style="background:${color(s)}"></i>${d.source_names[s]} <b>${gw(src[s])}</b> <em>${pct(src[s] / total)}</em></span>`).join("")}</div>`;
  }
  const srcDot = s => `<i class="en-dot" style="background:${color(s)}"></i>${esc(S.doc.source_names[s] || s)}`;
  const stTag = u => u.st === "operating" ? "" : ` <span class="tag ${u.st === "construction" ? "up" : ""}">${esc(S.doc.status_names[u.st] || u.st)}</span>`;
  const seg = (id, label, opts, cur) => `<div class="seg en-seg" role="radiogroup" aria-label="${label}" id="${id}">${opts.map(([k, l, n, tip]) =>
    `<button type="button" role="radio" data-v="${k}" aria-checked="${cur === k}"${n === 0 && cur !== k ? ` disabled aria-disabled="true"` : ""}${tip ? ` data-tip="${esc(tip)}"` : ""}>${l}${n != null ? ` <span class="n">${fmt.int(n)}</span>` : ""}</button>`).join("")}</div>`;
  // Kapsam düğmelerindeki sayılar o anki süzgeçlere (grup, kaynak, durum, arama) göre: seçili grubun yurt dışı santrali yoksa 0 ve pasif
  const scopeCount = sc => { const keep = S.scope; S.scope = sc; const n = unitsFiltered().length; S.scope = keep; return n; };
  const scopeOpts = labels => { const g = S.group && S.doc.byKey.get(S.group);
    return labels.map(([k, l]) => { const n = scopeCount(k);
      return [k, l, n, n ? "" : g ? `${g.name}: bu kapsamda santral yok` : "Bu süzgeçlerle santral yok"]; }); };
  function emptyNote() {
    const n = unitsFiltered().length;
    if (n) return "";
    const g = S.group && S.doc.byKey.get(S.group);
    const where = S.scope === "ab" ? "yurt dışında" : S.scope === "tr" ? "Türkiye'de" : "";
    const st = S.st === "op" ? "işletmede" : S.st === "pipe" ? "yatırım hattında" : "";
    return `<div class="en-map-empty" role="status"><b>${g ? esc(g.name) + " için " : ""}${[where, st].filter(Boolean).join(" ")} santral yok</b>
      <span>${g && S.scope === "ab" ? "Bu grubun GEM verisinde Türkiye dışında santrali bulunmuyor." : "Süzgeçleri değiştir."}</span>
      ${S.scope !== "tr" && scopeCount("tr") ? `<button type="button" class="link-btn" data-scope="tr">Türkiye'yi göster</button>` : ""}</div>`;
  }
  function groupChip() {
    const g = S.group && S.doc.byKey.get(S.group);
    return g ? `<div class="en-chip-row"><span class="en-gchip">Grup: <b>${esc(g.name)}</b><button type="button" class="en-x" id="enGroupClear" aria-label="Grup süzgecini kaldır">×</button></span></div>` : "";
  }

  // ─────────────────────────────── Genel bakış
  function kpis() {
    const d = S.doc, n = d.national, src = S.src;
    const k = (label, value, sub = "", tip = "") => `<div class="kpi" ${tip ? `data-tip="${esc(tip)}"` : ""}><span class="kpi-label">${label}</span><span class="kpi-value">${value}</span>${sub ? `<span class="kpi-sub">${sub}</span>` : ""}</div>`;
    if (src) {                                                     // kaynak seçiliyse tüm göstergeler o kaynağa göre
      const nm = d.source_names[src], tot = n.src[src] || 0, gs = d.groups.filter(g => g.src[src] > 0).sort((a, b) => b.src[src] - a.src[src]);
      const listed = gs.filter(g => g.ticker || g.parent).reduce((a, g) => a + g.src[src], 0);
      const top10 = gs.slice(0, 10).reduce((a, g) => a + g.src[src], 0);
      const rec = d.units.filter(u => !u.ab && u.s === src && u.st === "operating" && (u.y || 0) >= d.year - 2).reduce((a, u) => a + u.mw, 0);
      const ab = d.units.filter(u => u.ab && u.s === src && u.st === "operating");
      const big = gs.find(g => g.kind !== "kamu");
      return `<div class="kpi-grid">
        ${k(`${esc(nm)} kurulu güç`, gw(tot), `Türkiye toplamının ${pct(tot / (n.total || 1))}`)}
        ${k("Son 3 yılda eklenen", "+" + gw(rec), `${d.year - 2}–${d.year} başlangıçlı`)}
        ${k("Borsa şirketlerinin payı", pct(listed / (tot || 1)), "pay oranıyla")}
        ${k("İlk 10 grubun payı", pct(top10 / (tot || 1)))}
        ${k("Yatırım hattı", gw(n.pipe[src] || 0), "yapım ve planlama")}
        ${k("Yurt dışı yatırımlar", gw(ab.reduce((a, u) => a + u.mw, 0)), ab.length ? `${new Set(ab.map(u => u.cn)).size} ülke` : "yok")}
        ${k(`En büyük özel ${esc(nm.toLocaleLowerCase("tr"))} grubu`, big ? esc(big.name) : "—", big ? `${gw(big.src[src])} · ${pct(big.src[src] / (tot || 1))}` : "")}
      </div>`;
    }
    const ren = RENEW.reduce((s, k) => s + (n.src[k] || 0), 0);
    const big = d.groups.find(g => g.kind !== "kamu");
    return `<div class="kpi-grid">
      ${k("İşletmedeki kurulu güç", gw(n.total), "Türkiye, izlenen santraller", "Global Energy Monitor Integrated Power Tracker'daki Türkiye'de işletmedeki üniteler (güneş ≥1 MW). Lisanssız/çatı güneşin çoğu ve eşik altı küçük santraller dahil değil.")}
      ${k("Yenilenebilir payı", pct(ren / (n.total || 1)))}
      ${k("Borsa şirketlerinin payı", pct(d.listed_share), "pay oranıyla", "Borsadaki şirketlerin ve borsadaki ortağa bağlı santral şirketlerinin, ortaklık payları oranında kapasitesi ÷ izlenen toplam")}
      ${k("İlk 10 grubun payı", pct(d.top10))}
      ${k("Yatırım hattı", gw(n.pipe_total), "yapım ve planlama", "Türkiye'de yapım, izin/finansman ve duyurulmuş aşamadaki üniteler")}
      ${k("Yurt dışı yatırımlar", gw(d.abroad_total || 0), `${d.countryList.length} ülke · Türk sahipli`, "Sahibi ya da ana ortağı Türkiye'de kayıtlı şirket olan, Türkiye dışında işletmedeki santraller (tam ünite gücü). Türkiye toplamına katılmaz.")}
      ${k("En büyük özel grup", big ? esc(big.name) : "—", big ? `${gw(big.total)} · ${pct(big.share)}` : "")}
    </div>`;
  }
  function sourceCards() {
    const d = S.doc, n = d.national, year = d.year;
    const tr = d.units.filter(u => !u.ab);
    const cards = d.sources.filter(s => n.src[s] || n.pipe[s]).sort((a, b) => (n.src[b] || 0) - (n.src[a] || 0)).map(s => {
      const us = tr.filter(u => u.s === s);
      const op = us.filter(u => u.st === "operating");
      const rec = op.filter(u => (u.y || 0) >= year - 2).reduce((a, u) => a + u.mw, 0);
      const top = d.groups.filter(g => g.src[s] > 0).sort((a, b) => b.src[s] - a.src[s]).slice(0, 3);
      const on = S.src === s;
      return `<button type="button" class="en-sc ${on ? "on" : ""} ${S.src && !on ? "dim" : ""}" data-s="${s}" aria-pressed="${on}" style="--c:${color(s)}">
        <span class="en-sc-h"><i></i>${esc(d.source_names[s])}<span class="en-sc-p">${pct((n.src[s] || 0) / (n.total || 1), 0)}</span></span>
        <span class="en-sc-v">${gw(n.src[s] || 0)}</span>
        <span class="en-sc-bar" aria-hidden="true"><span style="width:${((n.src[s] || 0) / (n.total || 1) * 100).toFixed(1)}%"></span></span>
        <span class="en-sc-m"><span>${fmt.int(op.length)} ünite</span><span>yatırım hattı <b>${gw(n.pipe[s] || 0)}</b></span><span>son 3 yıl <b>+${gw(rec)}</b></span></span>
        ${top.length ? `<span class="en-sc-t">${top.map(g => `<span><span class="en-sc-tn">${esc(g.name)}</span><b>${gw(g.src[s])}</b></span>`).join("")}</span>` : ""}
      </button>`;
    }).join("");
    return `<section aria-labelledby="enScT"><div class="en-sec-h"><h2 class="card-title" id="enScT">Kaynaklar</h2><span class="card-meta">karta tıkla: tüm sekmeyi o kaynağa süz${S.src ? ` · <button type="button" class="link-btn" id="enSrcClear">Süzgeci kaldır</button>` : ""}</span></div>
      <div class="en-sc-grid">${cards}</div></section>`;
  }
  function national() {
    const d = S.doc, n = d.national, e = d.epias;
    const ctx = e ? (() => {
      const lic = sum(e.yekdem_licensed), un = sum(e.yekdem_unlicensed);
      return `<p class="en-ctx">EPİAŞ YEKDEM (${esc(fmt.date(e.period + "T12:00:00Z", { month: "long", year: "numeric" }))}): lisanslı ${gw(lic)}, <b>lisanssız ${gw(un)}</b> (güneş ${gw(e.yekdem_unlicensed.gunes)}). Lisanssız santrallerin çoğu bu envanterde sahibiyle yer almıyor.</p>`;
    })() : "";
    return `<section class="card" aria-labelledby="enNatT">
      <div class="card-head"><h2 class="card-title" id="enNatT">Türkiye kaynak dağılımı (işletmede)</h2><span class="card-meta">${gw(n.total)} · sahibi bilinmeyen ${gw(n.unowned)}</span></div>
      <div class="${S.src ? "en-focus" : ""}" style="--on:${S.src ? color(S.src) : "transparent"}">${mixBar(n.src, n.total, { h: 18, on: S.src })}${legend(n.src, n.total, S.src)}</div>${ctx}</section>`;
  }
  function opVsPipe() {
    const d = S.doc, n = d.national;
    const ks = d.sources.filter(s => n.src[s] || n.pipe[s]);
    const max = Math.max(...ks.map(s => Math.max(n.src[s] || 0, n.pipe[s] || 0)), 1);
    const row = s => `<div class="en-hb ${S.src && S.src !== s ? "dim" : ""}"><span class="en-hb-l">${srcDot(s)}</span>
      <span class="en-hb-bars"><span class="en-hb-b op" style="width:${((n.src[s] || 0) / max * 100).toFixed(2)}%;background:${color(s)}" data-tip="${esc(`${d.source_names[s]} işletmede: ${mw(n.src[s] || 0)} MW`)}"></span><span class="en-hb-v">${gw(n.src[s] || 0)}</span></span>
      <span class="en-hb-bars"><span class="en-hb-b pipe" style="width:${((n.pipe[s] || 0) / max * 100).toFixed(2)}%;--c:${color(s)}" data-tip="${esc(`${d.source_names[s]} yatırım hattı: ${mw(n.pipe[s] || 0)} MW`)}"></span><span class="en-hb-v">${n.pipe[s] ? gw(n.pipe[s]) : "—"}</span></span></div>`;
    return `<section class="card" aria-labelledby="enOpT"><div class="card-head"><h2 class="card-title" id="enOpT">İşletmede ve yatırım hattında</h2>
      <span class="card-meta en-hb-key"><span><i class="op"></i>işletmede</span><span><i class="pipe"></i>yapım + planlama</span></span></div>
      <div class="en-hb-grid"><span></span><span class="en-hb-h">İşletmede</span><span class="en-hb-h">Yatırım hattı</span>${ks.map(row).join("")}</div></section>`;
  }
  function abroadCard() {
    const d = S.doc, src = S.src;
    const ab = g => src ? g.abroad[src] || 0 : g.abroad_total;
    const abp = g => src ? d.units.filter(u => u.ab && u.s === src && PIPE.has(u.st) && d.owners[u.i].some(([x]) => x === g)).reduce((a, u) => a + u.mw * (d.owners[u.i].find(([x]) => x === g)[1]), 0) : g.abroad_pipe;
    const gs = d.groups.map(g => [g, ab(g), abp(g)]).filter(([, a, p]) => a + p > 0.5).sort((a, b) => (b[1] + b[2]) - (a[1] + a[2]));
    const us = d.units.filter(u => u.ab && u.st === "operating" && (!src || u.s === src));
    const head = `<div class="card-head"><h2 class="card-title" id="enAbT">Türk gruplarının yurt dışı santralleri${src ? ` · ${esc(d.source_names[src])}` : ""}</h2>`;
    if (!gs.length) return src ? `<section class="card" aria-labelledby="enAbT">${head}</div><p class="meta">${esc(d.source_names[src])} kaynağında Türk gruplarının yurt dışında santrali yok.</p></section>` : "";
    const byC = {}; us.forEach(u => { byC[u.cn] = (byC[u.cn] || 0) + u.mw; });
    const cs = Object.entries(byC).sort((a, b) => b[1] - a[1]);
    const ctry = g => { const c = [...new Set(g.units.map(([i]) => d.units[i]).filter(u => u.ab && (!src || u.s === src)).map(u => u.cn))];
      return c.length > 4 ? `<span data-tip="${esc(c.join(", "))}">${c.slice(0, 4).map(esc).join(", ")} +${c.length - 4} ülke</span>` : c.map(esc).join(", "); };
    return `<section class="card card-flush" aria-labelledby="enAbT">${head}
      <span class="card-meta">${gw(us.reduce((a, u) => a + u.mw, 0))} işletmede · ${cs.length} ülke · Türkiye toplamına katılmaz · <a class="link-btn" href="#enerji/harita" data-abroad="1">Haritada gör →</a></span></div>
      <div class="en-ab"><div class="tbl-scroll"><table class="tbl en-add"><thead><tr><th scope="col">Grup</th><th scope="col" class="num">İşletmede (MW)</th><th scope="col" class="num">Yatırım hattı (MW)</th><th scope="col">Kaynak</th></tr></thead><tbody>
      ${gs.slice(0, 12).map(([g, a, p]) => `<tr><td class="en-ab-g"><span class="en-ab-n">${esc(g.name)}</span>${g.code ? ` <a href="#hisse/${esc(g.code)}" class="en-code">${esc(g.code)}</a>` : ""}<span class="en-ab-cn">${ctry(g)}</span></td><td class="num"><b>${a ? mw(a) : "—"}</b></td>
        <td class="num">${p ? mw(p) : "—"}</td><td class="en-mixc">${a ? mixBar(src ? { [src]: a } : g.abroad, a) : `<span class="meta">yalnız yatırım hattı</span>`}</td></tr>`).join("")}
      </tbody></table></div>
      <div class="en-ab-c"><h3 class="en-h3">Ülkelere göre (işletmede)</h3>${cs.length ? cs.slice(0, 10).map(([c, v]) => `<div class="en-ab-r"><span>${esc(c)}</span><span class="en-ab-b"><span style="width:${(v / cs[0][1] * 100).toFixed(1)}%"></span></span><b>${mw(v)}</b></div>`).join("") : `<p class="meta">İşletmede santral yok; yalnız yatırım hattında.</p>`}</div></div></section>`;
  }
  function overview() {
    const d = S.doc;
    return `${kpis()}${sourceCards()}<div class="en-2col">${national()}${opVsPipe()}</div>${abroadCard()}
      <p class="en-note">Santraller, konumlar ve sahiplik <b>Global Energy Monitor</b> Integrated Power ve Ownership izleyicilerinden gelir (yılda yaklaşık iki kez güncellenir; aktarım ${esc(d.gem.imported || "")}). Grup kapasitesi <b>pay oranına göredir</b>: ortak girişimlerde her ortağa payı kadar MW yazılır. Yurt dışı santraller yalnız sahibi ya da ana ortağı Türkiye'de kayıtlı bir şirketse alınır ve Türkiye toplamlarına katılmaz. Kapsam dışı: 1 MW altı güneş ve izleyici eşiğinin altındaki küçük santraller.</p>`;
  }

  // ─────────────────────────────── Harita (Leaflet + kendi taban haritamız)
  // Taban harita: Natural Earth ülke ve il sınırları (kamu malı), siteyle birlikte sunulur — harici karo sunucusu ya da API anahtarı yok.
  const hex = c => { c = (c || "").trim(); const m = c.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
    if (m) { let h = m[1]; if (h.length === 3) h = [...h].map(x => x + x).join(""); return [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16)); }
    const r = c.match(/rgba?\(([^)]+)\)/); return r ? r[1].split(/[ ,]+/).slice(0, 3).map(Number) : [128, 128, 128]; };
  const mix = (a, b, t) => { const x = hex(a), y = hex(b); return `rgb(${x.map((v, i) => Math.round(v + (y[i] - v) * t)).join(",")})`; };
  const Map_ = {
    map: null, base: null, prov: null, geo: null, layer: null, markers: [], loading: null, fitted: "",
    async geodata() {
      if (this.geo) return this.geo;
      const get = async f => { const r = await fetch(`vendor/harita/${f}?v=1`); if (!r.ok) throw new Error("harita sınırları yüklenemedi"); return r.json(); };
      const [world, il] = await Promise.all([get("world.geojson"), get("tr_il.geojson")]);
      return (this.geo = { world, il });
    },
    lib() {
      if (window.L) return Promise.resolve();
      return this.loading ||= new Promise((ok, no) => {
        const css = document.createElement("link"); css.rel = "stylesheet"; css.href = "vendor/leaflet/leaflet.css?v=1.9.4"; document.head.append(css);
        const js = document.createElement("script"); js.src = "vendor/leaflet/leaflet.js?v=1.9.4"; js.onload = ok; js.onerror = () => no(new Error("harita kütüphanesi yüklenemedi")); document.head.append(js);
      });
    },
    colors() {
      const v = n => sh.cssVar(n);
      return { sea: v("--surface-2") || "#eef0f2", land: v("--surface") || "#fff", line: v("--border-strong") || "#bbb", soft: v("--border") || "#ddd",
        tr: mix(v("--surface") || "#fff", v("--accent") || "#36c", sh.isDark() ? 0.10 : 0.06), acc: v("--accent") || "#36c" };
    },
    drawBase() {
      const m = this.map, c = this.colors(), g = this.geo;
      m.getContainer().style.background = c.sea;
      this.base?.remove();
      this.base = L.layerGroup([
        L.geoJSON(g.world, { pane: "base", interactive: false, style: f => ({ color: c.line, weight: 0.6, fillColor: f.properties.iso === "TR" ? c.tr : c.land, fillOpacity: 1 }) }),
        L.geoJSON(g.il, { pane: "base", interactive: false, style: { color: c.soft, weight: 0.7, fill: false } }),
      ]).addTo(m);
    },
    reset() { this.layer?.remove(); this.layer = null; this.prov?.remove(); this.prov = null; this.markers = []; this.fitted = ""; },
    async mount(el) {
      await Promise.all([this.lib(), this.geodata()]);
      if (this.map && this.map.getContainer() !== el) { this.map.remove(); this.map = null; this.reset(); }
      if (!this.map) {
        this.map = L.map(el, { preferCanvas: true, zoomSnap: 0.5, minZoom: 2, maxZoom: 12, worldCopyJump: false, maxBounds: [[-70, -200], [85, 200]], attributionControl: true })
          .fitBounds([[35.8, 25.6], [42.2, 44.8]]);
        this.map.attributionControl.setPrefix(false);
        this.map.attributionControl.addAttribution('Sınırlar: <a href="https://www.naturalearthdata.com" target="_blank" rel="noopener">Natural Earth</a> · santraller: GEM (CC BY 4.0)');
        this.map.createPane("base").style.zIndex = 250;
        this.map.createPane("prov").style.zIndex = 350;
        this.drawBase();
        this.map.on("zoomend", () => this.rescale());
      } else this.map.invalidateSize();
      this.draw();
    },
    retheme() { if (!this.map) return; this.drawBase(); this.draw(); },
    // daire boyutu yakınlaştırmayla büyür (z 6 = Türkiye geneli); dar ekranda Türkiye ~z5 olduğundan küçük kalır
    zk() { return Math.max(0.55, Math.pow(2, ((this.map?.getZoom() ?? 6) - 6) * 0.4)); },
    radius(v) { return Math.min(30, Math.max(1.8, (1.2 + Math.sqrt(v) / 2.6) * this.zk())); },
    rescale() { this.markers.forEach((mk, i) => mk && mk.setRadius(this.radius(S.doc.units[i].mw))); },
    draw() {
      const d = S.doc, m = this.map;
      if (!m) return;
      this.layer?.remove(); this.prov?.remove(); this.prov = null;
      this.layer = L.featureGroup().addTo(m);
      this.markers = [];
      const css = Object.fromEntries(d.sources.map(s => [s, sh.cssVar(`--en-${s}`) || "#888"]));
      const ring = sh.cssVar("--surface") || "#fff";
      let us;
      if (S.year != null) {                                        // zaman makinesi: o yıla kadar devreye girenler (+ sonrası için planlananlar)
        const now = d.year;
        us = unitsFiltered({ st: false }).filter(u => u.la != null && u.y && u.y <= S.year &&
          (u.st === "operating" || (S.year > now && PIPE.has(u.st) && u.y > now)));
      } else us = unitsFiltered().filter(u => u.la != null && u.lo != null);
      if (S.mapView === "prov" && S.scope === "tr") {
        const P = {};
        us.filter(u => !u.ab).forEach(u => { const p = P[fold(u.p || "")] ||= { p: u.p || "bilinmiyor", mw: 0, n: 0, src: {} };
          p.mw += u.mw; p.n++; p.src[u.s] = (p.src[u.s] || 0) + u.mw; });
        const c = this.colors(), max = Math.max(...Object.values(P).map(p => p.mw), 1);
        const lv = v => v ? Math.sqrt(v / max) : 0;                             // karekök ölçek: büyük iller öne çıkar, küçükler yine ayırt edilir
        const fill = v => v ? mix(c.land, c.acc, 0.08 + 0.92 * lv(v)) : c.land;
        this.prov = L.geoJSON(this.geo.il, { pane: "prov", style: f => { const p = P[fold(f.properties.il)]; return { color: c.line, weight: 0.8, fillColor: fill(p?.mw), fillOpacity: 1 }; },
          onEachFeature: (f, lyr) => { const p = P[fold(f.properties.il)] || { p: f.properties.il, mw: 0, n: 0, src: {} };
            lyr.bindTooltip(`${f.properties.il}: ${p.mw ? mw(p.mw) + " MW" : "kayıt yok"}`, { sticky: true });
            lyr.bindPopup(() => `<div class="en-pop"><b class="en-pop-n">${esc(f.properties.il)}</b><div class="en-pop-k">${mw(p.mw)} MW · ${fmt.int(p.n)} ünite · Türkiye payı ${pct(p.mw / (S.doc.national.total || 1))}</div>${p.mw ? mixBar(p.src, p.mw) + legend(p.src, p.mw) : ""}</div>`, { maxWidth: 320 });
            lyr.on("mouseover", () => lyr.setStyle({ weight: 2, color: c.acc })); lyr.on("mouseout", () => this.prov.resetStyle(lyr)); } }).addTo(m);
        const steps = [0.02, 0.1, 0.35, 1].map(t => Math.round(max * t));
        $("#enProvLeg") && ($("#enProvLeg").innerHTML = `<span class="en-cho">${steps.map(v => `<span><i style="background:${fill(v)}"></i>${v >= 1000 ? fmt.num(v / 1000, 1) + " GW" : fmt.int(v) + " MW"}</span>`).join("")}</span>`);
      } else {
        const fresh = S.year != null ? sh.cssVar("--text") || "#111" : null;
        us.sort((a, b) => b.mw - a.mw).forEach(u => {
          const pipe = u.st !== "operating", c = css[u.s], isNew = fresh && u.y === S.year;
          const mk = L.circleMarker([u.la, u.lo], { radius: this.radius(u.mw) * (isNew ? 1.25 : 1), color: isNew ? fresh : pipe ? c : ring, weight: isNew ? 2 : pipe ? 2 : 1, fillColor: c, fillOpacity: pipe ? 0.08 : 0.78, opacity: 1 })
            .bindPopup(() => popup(u), { maxWidth: 360, minWidth: 260 })
            .bindTooltip(`${u.n} · ${mw(u.mw)} MW`, { direction: "top", offset: [0, -4] });
          mk.addTo(this.layer); this.markers[u.i] = mk;
        });
      }
      const key = `${S.scope}|${S.group}|${S.src}|${S.q}|${S.mapView}`;
      if (key !== this.fitted) {
        this.fitted = key;
        if (S.group || S.q || S.scope !== "tr") {
          const b = this.layer.getBounds();
          if (b.isValid()) m.fitBounds(b.pad(0.15), { maxZoom: S.group ? 8 : 9 });
        } else if (S.scope === "tr") m.fitBounds([[35.8, 25.6], [42.2, 44.8]]);
        else m.setView([30, 25], 3);
      }
      if (S.mapView !== "prov" && $("#enProvLeg")) $("#enProvLeg").innerHTML = "";
      $("#enMapN") && ($("#enMapN").textContent = `${fmt.int(us.length)} ünite · ${gw(us.reduce((a, u) => a + u.mw, 0))}`);
      yearPanel(us);
    },
    open(i) {
      const mk = this.markers[i];
      if (!mk) return;
      this.map.setView(mk.getLatLng(), Math.max(this.map.getZoom(), 9));
      mk.openPopup();
    },
  };
  const TECH = [[/conventional storage/i, "barajlı"], [/run-of-river/i, "nehir tipi"], [/pumped storage/i, "pompaj depolamalı"], [/assumed pv|^pv$|photovoltaic/i, "fotovoltaik (PV)"],
    [/onshore/i, "karasal"], [/offshore/i, "deniz üstü"], [/combined cycle/i, "kombine çevrim"], [/gas turbine/i, "gaz türbini"], [/steam turbine/i, "buhar türbini"],
    [/internal combustion/i, "içten yanmalı motor"], [/ultra-supercritical/i, "ultra süperkritik"], [/supercritical/i, "süperkritik"], [/subcritical/i, "subkritik"],
    [/^cfb$|circulating fluidized/i, "dolaşımlı akışkan yatak"], [/flash steam/i, "flaş buhar"], [/binary cycle/i, "ikili çevrim"], [/pressurized water reactor/i, "basınçlı su reaktörü"],
    [/fossil gas: natural gas/i, "doğalgaz"], [/fossil liquids: fuel oil/i, "fuel oil"], [/coal: lignite/i, "linyit"], [/coal: bituminous/i, "taşkömürü"], [/coal: unknown/i, "kömür"]];
  const techTr = t => TECH.reduce((s, [rx, tr]) => s.replace(rx, tr), String(t));
  function popup(u) {
    const d = S.doc, os = d.owners[u.i].slice().sort((a, b) => b[1] - a[1]);
    const keys = new Set(os.map(([g]) => g.key));
    const tok = fold(u.n).split(/\s+/).filter(t => t.length > 3 && !["SANTRALI", "ENERJI", "SANTRAL"].includes(t));
    const kap = (d.kap || []).filter(r => keys.has(r.group) && tok.some(t => fold(r.plant || "").includes(t))).slice(0, 3);
    const row = (k, v) => v ? `<tr><th>${k}</th><td>${v}</td></tr>` : "";
    return `<div class="en-pop">
      <b class="en-pop-n">${esc(u.n)}</b>${u.en && fold(u.en) !== fold(u.n) ? `<div class="en-pop-en">${esc(u.en)}</div>` : ""}
      <div class="en-pop-k">${srcDot(u.s)} · <b>${mw(u.mw)} MW</b> · ${esc(d.status_names[u.st] || u.st)}${u.y ? ` · ${u.y}` : ""}</div>
      <table class="en-pop-t">
        ${row("Konum", [u.ci, u.p, u.cn].filter(Boolean).map(esc).join(", ") + (u.acc && u.acc !== "exact" ? ` <span class="meta">(yaklaşık)</span>` : ""))}
        ${row("Sahipler", os.length ? os.map(([g, s]) => `${esc(g.name)}${g.code ? ` <a href="#hisse/${esc(g.code)}" class="en-code">${g.ticker ? "" : "↳ "}${esc(g.code)}</a>` : ""} <span class="meta">${pct(s, s < 1 ? 1 : 0)}</span>`).join("<br>") : `<span class="meta">bilinmiyor</span>`)}
        ${row("GEM sahip", u.o && !u.path ? esc(u.o) : "")}
        ${row("Ana ortak", u.pa ? esc(u.pa) : "")}
        ${row("Zincir", u.path ? esc(u.path) : "")}
        ${row("Teknoloji", u.tech ? esc(techTr(u.tech)) : "")}
        ${row("Lisans / kimlik", u.lic ? esc(u.lic) : "")}
      </table>
      ${kap.length ? `<div class="en-pop-kap"><b>KAP</b>${kap.map(r => `<a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(fmt.date(r.date + "T12:00:00Z", { day: "numeric", month: "short", year: "2-digit" }))} · ${esc(d.kap_types[r.type] || r.type)}${r.mw ? ` · ${mw(r.mw)} MW` : ""} ↗</a>`).join("")}</div>` : ""}
      <div class="en-pop-f">${u.u ? `<a href="${esc(u.u)}" target="_blank" rel="noopener">GEM.wiki ↗</a>` : ""}${os[0] ? `<button type="button" class="link-btn" data-grp="${esc(os[0][0].key)}">${esc(os[0][0].name)} santralleri</button>` : ""}</div></div>`;
  }
  // ─────────────────────────────── zaman makinesi
  const Play = { t: null };
  function timeBar() {
    const d = S.doc, max = d.year + 5, y = S.year ?? d.year;
    return `<div class="en-time ${S.year != null ? "on" : ""}">
      <button type="button" class="btn-sm en-play" id="enPlay" aria-pressed="${!!Play.t}" aria-label="${Play.t ? "Durdur" : "Oynat"}">${Play.t ? "❚❚ Durdur" : "▶ Zamanda oynat"}</button>
      <input type="range" id="enYear" min="${Y0}" max="${max}" step="1" value="${y}" aria-label="Yıl" aria-valuetext="${S.year == null ? "bugün" : S.year}">
      <span class="en-time-y" id="enYearL">${S.year == null ? "Bugün" : S.year}${S.year > d.year ? ` <span class="tag">plan</span>` : ""}</span>
      ${S.year != null ? `<button type="button" class="link-btn" id="enYearOff">Bugüne dön</button>` : `<span class="meta">${Y0}'den ${max}'e santrallerin devreye girişi</span>`}
    </div>`;
  }
  function yearPanel(us) {
    const box = $("#enYr"); if (!box) return;
    if (S.year == null) { box.hidden = true; return; }
    const d = S.doc, op = us.filter(u => u.st === "operating"), by = {}; op.forEach(u => { by[u.s] = (by[u.s] || 0) + u.mw; });
    const tot = sum(by), plan = us.filter(u => u.st !== "operating").reduce((a, u) => a + u.mw, 0);
    const add = us.filter(u => u.y === S.year).reduce((a, u) => a + u.mw, 0);
    const noY = unitsFiltered({ st: false }).filter(u => u.st === "operating" && !u.y).reduce((a, u) => a + u.mw, 0);
    const ren = RENEW.reduce((a, k) => a + (by[k] || 0), 0);
    box.hidden = false;
    box.innerHTML = `<b class="en-yr-y">${S.year}</b><span class="en-yr-v">${gw(tot)}</span><span class="meta">işletmede · yenilenebilir ${pct(ren / (tot || 1), 0)}</span>
      ${mixBar(by, tot, { h: 8 })}<span class="en-yr-a">${add ? `bu yıl +${mw(add)} MW${S.year > d.year ? " (planlanan)" : ""}` : "bu yıl yeni santral yok"}${plan ? ` · toplam planlanan ${gw(plan)}` : ""}</span>
      ${noY > 1 ? `<span class="meta" style="font-size:var(--fs-2xs)">başlangıç yılı bilinmeyen ${gw(noY)} dahil değil</span>` : ""}`;
  }
  function setYear(y) {
    const d = S.doc;
    S.year = y;
    if (y == null) { stopPlay(); return render(); }
    if ($(".en-time:not(.on)") || $("#enSt")) return render();       // ilk geçiş: kontrolleri yeniden kur
    $("#enYear").value = y; $("#enYear").setAttribute("aria-valuetext", y);
    $("#enYearL").innerHTML = `${y}${y > d.year ? ` <span class="tag">plan</span>` : ""}`;
    Map_.draw();
  }
  function stopPlay() { clearInterval(Play.t); Play.t = null; const b = $("#enPlay"); if (b) { b.textContent = "▶ Zamanda oynat"; b.setAttribute("aria-pressed", "false"); } }
  function togglePlay() {
    if (Play.t) return stopPlay();
    const max = S.doc.year + 5;
    let y = S.year == null || S.year >= max ? Y0 : S.year;
    setYear(y);
    Play.t = setInterval(() => { if (sh.route !== "enerji" || tab() !== "harita") return stopPlay(); y++; if (y > max) return stopPlay(); setYear(y); }, 550);
    const b = $("#enPlay"); if (b) { b.textContent = "❚❚ Durdur"; b.setAttribute("aria-pressed", "true"); }
  }
  function mapTab() {
    const d = S.doc;
    return `${groupChip()}<section class="card card-flush en-mapcard" aria-labelledby="enMapT">
      <div class="card-head"><h2 class="card-title" id="enMapT">Santral haritası</h2><span class="card-meta" id="enMapN"></span></div>
      <div class="en-map-ctl">
        ${seg("enScope", "Kapsam", scopeOpts([["tr", "Türkiye"], ["ab", "Yurt dışı yatırımlar"], ["all", "Dünya"]]), S.scope)}
        ${S.year == null ? seg("enSt", "Durum", [["op", "İşletmede"], ["pipe", "Yatırım hattı"], ["all", "Tümü"]], S.st) : ""}
        ${S.scope === "tr" ? seg("enView", "Görünüm", [["units", "Santraller"], ["prov", "İl toplamı"]], S.mapView) : ""}
      </div>
      ${timeBar()}
      <div class="en-map-wrap"><div id="enMapEmpty">${S.year == null ? emptyNote() : ""}</div><div class="en-yr" id="enYr" ${S.year == null ? "hidden" : ""}></div><div id="enMap" class="en-map" role="region" aria-label="Santral haritası; ayrıntı için Santraller sekmesindeki tabloyu kullan"></div></div>
      <div class="en-map-leg">${d.sources.filter(s => d.national.src[s] || d.national.pipe[s]).map(s => `<span>${srcDot(s)}</span>`).join("")}
        <span class="en-leg-sz"><i style="width:7px;height:7px"></i><i style="width:14px;height:14px"></i><i style="width:24px;height:24px"></i>boyut = MW</span><span><i class="en-ring"></i>içi boş = yapım/planlama</span><span id="enProvLeg"></span></div>
    </section>
    <p class="en-note">Taban harita: Natural Earth ülke ve il sınırları (kamu malı), sitenin kendi sunucusundan; harici harita servisi ya da anahtar kullanılmaz. “İl toplamı” görünümünde renk vurgulandıkça ildeki kurulu güç artar. Konumlar GEM'in verdiği koordinatlardır; “yaklaşık” işaretli santraller ilçe ya da il merkezine yerleştirilmiştir. Daire alanı kurulu güçle orantılıdır. Santrale tıkla: sahipler, paylar, sahiplik zinciri, lisans ve ilgili KAP bildirimleri.</p>`;
  }

  // ─────────────────────────────── Gruplar
  function squarify(items, W, H) {
    const out = []; let x = 0, y = 0, w = W, h = H, rest = items.slice();
    const worst = (row, side) => { const s = row.reduce((a, b) => a + b.a, 0), mx = Math.max(...row.map(z => z.a)), mn = Math.min(...row.map(z => z.a));
      return Math.max(side * side * mx / (s * s), (s * s) / (side * side * mn)); };
    while (rest.length) {
      const side = Math.min(w, h); let row = [rest[0]], i = 1;
      while (i < rest.length && worst([...row, rest[i]], side) <= worst(row, side)) row.push(rest[i++]);
      const s = row.reduce((a, b) => a + b.a, 0);
      if (w >= h) { const cw = s / h; let cy = y; row.forEach(z => { const ch = z.a / cw; out.push({ ...z, x, y: cy, w: cw, h: ch }); cy += ch; }); x += cw; w -= cw; }
      else { const rh = s / w; let cx = x; row.forEach(z => { const c = z.a / rh; out.push({ ...z, x: cx, y, w: c, h: rh }); cx += c; }); y += rh; h -= rh; }
      rest = rest.slice(i);
    }
    return out;
  }
  function treemap(rows) {
    const d = S.doc;
    const top = rows.filter(g => g.srcMw > 0).sort((a, b) => b.srcMw - a.srcMw).slice(0, 30);
    if (top.length < 3) return "";
    const W = 1000, H = 400, tot = top.reduce((a, g) => a + g.srcMw, 0);
    const rest = rows.filter(g => g.srcMw > 0).reduce((a, g) => a + g.srcMw, 0) - tot;
    const rects = squarify(top.map(g => ({ g, a: g.srcMw / tot * W * H })), W, H);
    const nat = S.src ? d.national.src[S.src] : d.national.total;
    return `<section class="card" aria-labelledby="enTmT"><div class="card-head"><h2 class="card-title" id="enTmT">En büyük 30 grup${S.src ? ` · ${esc(d.source_names[S.src])}` : ""}</h2>
      <span class="card-meta">alan = pay oranıyla işletmedeki MW · renk = ağırlıklı kaynak · kalan ${fmt.int(rows.filter(g => g.srcMw > 0).length - top.length)} grup ${gw(rest)}</span></div>
      <div class="en-tm" role="list">${rects.map(r => {
        const g = r.g, srcs = S.src ? { [S.src]: g.srcMw } : g.src, main = Object.entries(srcs).sort((a, b) => b[1] - a[1])[0][0];
        const small = r.w < 90 || r.h < 46;
        return `<button type="button" role="listitem" class="en-tm-i ${small ? "sm" : ""}" data-k="${esc(g.key)}" style="left:${r.x / W * 100}%;top:${r.y / H * 100}%;width:${r.w / W * 100}%;height:${r.h / H * 100}%;--c:${color(main)}"
          data-tip="${esc(`<b>${esc(g.name)}</b><br>${mw(g.srcMw)} MW · Türkiye payı ${pct(g.srcMw / (nat || 1), 1)}${g.abroad_total ? `<br>yurt dışı ${mw(g.abroad_total)} MW` : ""}`)}">
          <span class="en-tm-n">${esc(g.name)}</span>${small ? "" : `<span class="en-tm-v">${gw(g.srcMw)} · ${pct(g.srcMw / (nat || 1), 1)}</span>`}
          ${!S.src && r.h > 70 && r.w > 110 ? `<span class="en-tm-mix">${mixBar(g.src, g.total, { h: 5 })}</span>` : ""}</button>`; }).join("")}</div></section>`;
  }
  function table(rows) {
    const d = S.doc;
    const COLS = [["rank", "#", 1], ["name", "Grup / şirket"], ["code", "Kod"], ["total", S.src ? `${d.source_names[S.src]} (MW)` : "Türkiye (MW)", 1], ["share", "Türkiye payı", 1],
      ["mix", "Kaynak dağılımı"], ["renew", "Yenilenebilir", 1], ["cons", "Konsolide (MW)", 1], ["pipe_total", "Yatırım hattı (MW)", 1], ["abroad_total", "Yurt dışı (MW)", 1], ["kap_added", "KAP: GEM sonrası (MW)", 1], ["n", "Ünite", 1]];
    const TIPS = { total: "Ortaklık payı oranında Türkiye'de işletmedeki kurulu güç", share: "Grubun kapasitesi ÷ izlenen Türkiye toplamı", cons: "%50 ve üzeri payla kontrol edilen ünitelerin tam gücü",
      pipe_total: "Türkiye'de yapım, izin/finansman ve duyurulmuş aşamadaki üniteler (pay oranıyla)", abroad_total: "Türkiye dışında işletmedeki santraller (pay oranıyla); Türkiye toplamına katılmaz",
      kap_added: "GEM verisinin tarihinden sonra KAP'ta bildirilen devreye alma ve kapasite artışları (MWe; yalnız MWp verilmişse MWp)", n: "Türkiye'de işletmedeki ünite / faz sayısı", code: "Borsa kodu; santral şirketi borsada değilse borsadaki ortağın kodu (↳)" };
    const head = COLS.map(([c, l, num]) => c === "mix" || c === "rank" ? `<th scope="col" class="${num ? "num" : ""}">${l}</th>` :
      `<th scope="col" class="${num ? "num" : ""}" aria-sort="${c === S.sort ? (S.dir > 0 ? "ascending" : "descending") : "none"}"><button type="button" class="th-sort" data-c="${c}" ${TIPS[c] ? `data-tip="${esc(TIPS[c])}"` : ""}>${l}<span class="arr" aria-hidden="true">${c === S.sort ? (S.dir > 0 ? "▲" : "▼") : "▼"}</span></button></th>`).join("");
    const shown = rows.slice(0, S.limit);
    const natSrc = S.src ? d.national.src[S.src] : d.national.total;
    const body = shown.map(g => {
      const open = S.open.has(g.key);
      const code = g.ticker ? `<a href="#hisse/${esc(g.ticker)}" class="en-code" data-tip="Temel analiz">${esc(g.ticker)}</a>` :
        g.parent ? `<a href="#hisse/${esc(g.parent)}" class="en-code parent" data-tip="Borsadaki ortak">↳ ${esc(g.parent)}</a>` : "";
      const tag = g.kind === "kamu" ? ` <span class="tag na">kamu</span>` : g.auto ? ` <span class="tag" data-tip="Grup listesinde yok; sahibin kendi adıyla gösteriliyor">eşleşmedi</span>` : "";
      return `<tr class="row ${open ? "open" : ""}" data-k="${esc(g.key)}" tabindex="0" aria-expanded="${open}">
        <td class="num en-rank">${g.rank}</td>
        <td class="en-nm"><span>${esc(g.name)}</span>${tag}</td>
        <td>${code}</td>
        <td class="num"><b>${g.srcMw ? mw(g.srcMw) : "—"}</b></td>
        <td class="num">${natSrc && g.srcMw ? pct(g.srcMw / natSrc, 2) : "—"}</td>
        <td class="en-mixc">${mixBar(g.src, g.total)}</td>
        <td class="num">${pct(g.renew, 0)}</td>
        <td class="num">${g.cons ? mw(g.cons) : "—"}</td>
        <td class="num">${g.srcPipe ? mw(g.srcPipe) : "—"}</td>
        <td class="num">${g.srcAb ? `<span data-tip="${esc(g.countries.join(", "))}">${mw(g.srcAb)}</span>` : g.abroad_pipe && !S.src ? `<span class="meta" data-tip="Yurt dışında yapım/planlama aşamasında">(${mw(g.abroad_pipe)})</span>` : "—"}</td>
        <td class="num">${g.kap_added ? `<span class="up" data-tip="${esc(`KAP'ta GEM sonrası devreye alınan: ${mw(g.kap_added)} MW${g.kap_pipe ? ` · KAP'ta lisans/ÇED/YEKA aşamasında: ${mw(g.kap_pipe)} MW` : ""}`)}">+${mw(g.kap_added)}</span>` : g.kap_pipe ? `<span class="meta" data-tip="KAP'ta lisans/önlisans/ÇED/YEKA aşamasındaki projeler">(${mw(g.kap_pipe)})</span>` : "—"}</td>
        <td class="num">${g.n}</td>
      </tr>${open ? `<tr class="drawer"><td colspan="${COLS.length}">${drawer(g)}</td></tr>` : ""}`;
    }).join("");
    const total = rows.length;
    return `<section class="card card-flush" aria-labelledby="enTblT">
      <div class="card-head"><h2 class="card-title" id="enTblT">Gruplar ve şirketler (${fmt.int(total)})</h2><span class="card-meta">satıra tıkla: santraller · başlığa tıkla: sırala</span></div>
      <div class="tbl-scroll en-scroll"><table class="tbl en-tbl"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>
      ${total > shown.length || S.limit > PAGE ? `<div class="tbl-foot"><span>${fmt.int(shown.length)} / ${fmt.int(total)} gösteriliyor</span>
        <span>${total > shown.length ? `<button type="button" class="link-btn" id="enMore">${Math.min(PAGE, total - shown.length)} daha</button> · <button type="button" class="link-btn" id="enAll">Tümü</button>` : `<button type="button" class="link-btn" id="enLess">İlk ${PAGE} satıra dön</button>`}</span></div>` : ""}
      ${total ? "" : sh.stateHTML({ kind: "empty", title: "Eşleşen grup yok", msg: "Aramayı ya da filtreleri değiştir." })}</div></section>`;
  }
  function unitRow(i, share) {
    const d = S.doc, u = d.units[i];
    return `<tr><td>${u.la != null ? `<button type="button" class="link-btn en-ulink" data-u="${i}" data-tip="Haritada göster">${esc(u.n)}</button>` : esc(u.n)}${stTag(u)}</td>
      <td>${srcDot(u.s)}</td><td class="num">${mw(u.mw)}</td>
      <td class="num">${share == null ? "" : pct(share, share < 1 ? 1 : 0)}</td><td class="num">${u.y || "—"}</td><td>${place(u)}</td></tr>`;
  }
  // ─────────────────────────────── sahiplik ağacı (GEM sahiplik zinciri + sahip/ana ortak alanları)
  const OT_SKIP = /natural person|small shareholder|individual investor|gerçek kişi/i;
  const otNorm = n => fold(n).replace(/\b(A S|AS|A Ş|ANONIM SIRKETI|SANAYI VE TICARET|SAN VE TIC|SAN TIC|LTD STI|LIMITED SIRKETI|LTD|INC|NV|JSC|LLC)\b/g, "").replace(/\s+/g, " ").trim();
  const otPart = s => { const m = String(s).trim().match(/^(.*?)\s*\[([\d.]+)%\]\s*$/); return m ? [m[1].trim(), +m[2] / 100] : [String(s).trim(), null]; };
  const otList = s => String(s || "").split(";").map(x => x.trim()).filter(Boolean).map(otPart);
  function ownTree(g) {
    // Grup → santrali doğrudan tutan şirketler (adı farklı yazılmış aynı şirket birleştirilir) → santraller.
    // Şirketin üstündeki ortaklar (zincirdeki önceki halkalar ya da GEM "ana ortak" alanı) şirket kartında "↑" ile gösterilir.
    const d = S.doc, C = new Map();
    const keyOf = n => { const k = otNorm(n) || fold(n);
      for (const [k2, c] of C) { const [a, b] = k.length < k2.length ? [k, k2] : [k2, k];
        if (a.split(" ").length >= 2 && (b === a || b.startsWith(a + " "))) { if (k.length > k2.length) { C.delete(k2); C.set(k, c); return k; } return k2; } }
      return k; };
    const company = n => { const k = keyOf(n); let c = C.get(k); if (!c) C.set(k, c = { name: n, up: new Map(), leaves: [] }); else if (n.length > c.name.length) c.name = n; return c; };
    for (const u of g.units.map(([i]) => d.units[i]).filter(u => !S.src || u.s === S.src)) {
      const all = otList(u.o);
      let links;                                                    // [[şirket, santraldeki payı, [[üst ortak, pay]...]]]
      if (u.path) { const parts = u.path.split("->").map(otPart), pl = parts.pop(), chain = parts.filter(([n]) => !OT_SKIP.test(n));
        if (!chain.length) continue;
        const [cn] = chain[chain.length - 1];
        links = [[cn, pl[1], chain.slice(0, -1).map(([n], j) => [n, chain[j + 1][1]])]]; }
      else { const pars = otList(u.pa);
        links = (all.length ? all : pars.slice(0, 1)).map(([n, pct]) => [n, pct, pars.filter(([pn]) => otNorm(pn) !== otNorm(n))]); }
      for (const [cn, pct, ups] of links) {
        const c = company(cn);
        ups.forEach(([n, x]) => { if (!c.up.has(fold(n))) c.up.set(fold(n), [n, x]); });
        c.leaves.push({ u, pct, co: all.filter(([n]) => otNorm(n) !== otNorm(cn)) });
      }
    }
    if (!C.size) return "";
    const pctTag = p => p != null && p < 0.9995 ? `<span class="en-ot-p">%${fmt.num(p * 100, p < 0.1 ? 1 : 0)}</span>` : "";
    const plants = ls => { const P = new Map();
      ls.forEach(l => { const base = l.u.n.replace(/\s+(\d+|[IVX]+|CC|ST|GT|Unit \d+|Faz \d+)$/i, "").trim(), k = fold(base) + "|" + (l.u.cn || "");
        const p = P.get(k) || P.set(k, { n: base, mw: 0, nu: 0, s: l.u.s, st: l.u.st, ab: l.u.ab, cn: l.u.cn, p: l.u.p, pct: l.pct, co: l.co, i: l.u.i }).get(k);
        p.mw += l.u.mw; p.nu++; if (l.u.st === "operating") p.st = "operating"; });
      return [...P.values()].sort((a, b) => b.mw - a.mw); };
    const cs = [...C.values()].map(c => ({ ...c, ps: plants(c.leaves), mw: c.leaves.reduce((a, l) => a + l.u.mw, 0),
      src: c.leaves.reduce((o, l) => (o[l.u.s] = (o[l.u.s] || 0) + l.u.mw, o), {}) })).sort((a, b) => b.mw - a.mw);
    const LIM = 12, tot = cs.reduce((a, c) => a + c.mw, 0);
    const plantLi = p => `<li class="en-ot-l"><button type="button" class="en-ot-plant" data-u="${p.i}" data-tip="Haritada göster">
        <i class="en-dot" style="background:${color(p.s)}"></i><span class="en-ot-name">${esc(p.n)}</span>${pctTag(p.pct)}<span class="en-ot-mw">${mw(p.mw)} MW${p.nu > 1 ? ` · ${p.nu} ünite` : ""}</span>
        <span class="meta">${p.ab ? esc(p.cn) : esc(p.p || "")}${p.st !== "operating" ? " · " + esc(S.doc.status_names[p.st] || p.st) : ""}</span></button>
        ${p.co.length ? `<span class="en-ot-co">ortak: ${p.co.map(([n, x]) => `${esc(n)}${x != null ? ` %${fmt.num(x * 100, 0)}` : ""}`).join(" · ")}</span>` : ""}</li>`;
    return `<details class="en-ot" open><summary class="en-h3">Sahiplik ağacı <span class="meta">grup → santrali tutan şirketler → santraller · yüzdeler ortaklık payı · ↑ = şirketin ortakları · “ortak” = santraldeki diğer pay sahipleri</span></summary>
      <ul class="en-ot-root"><li class="en-ot-n"><div class="en-ot-h en-ot-g"><span class="en-ot-name"><b>${esc(g.name)}</b></span>${g.code ? `<span class="en-code">${esc(g.code)}</span>` : ""}<span class="en-ot-mw">${mw(tot)} MW · ${cs.length} şirket</span></div>
      <ul>${cs.map(c => `<li class="en-ot-n"><div class="en-ot-h"><span class="en-ot-name">${esc(c.name)}</span><span class="en-ot-mw">${mw(c.mw)} MW</span><span class="en-ot-mix">${mixBar(c.src, c.mw, { h: 5 })}</span></div>
        ${c.up.size ? `<div class="en-ot-up">↑ ${[...c.up.values()].map(([n, x]) => `${esc(n)}${x != null ? ` <span class="en-ot-p">%${fmt.num(x * 100, x < 0.1 ? 1 : 0)}</span>` : ""}`).join(" · ")}</div>` : ""}
        <ul>${c.ps.slice(0, LIM).map(plantLi).join("")}${c.ps.length > LIM ? `<li class="en-ot-l meta">+${c.ps.length - LIM} santral daha</li>` : ""}</ul></li>`).join("")}</ul></li></ul></details>`;
  }
  function drawer(g) {
    const d = S.doc;
    const us = g.units.filter(([i]) => !S.src || d.units[i].s === S.src);
    const home = us.filter(([i]) => !d.units[i].ab), ab = us.filter(([i]) => d.units[i].ab);
    const ents = g.entities.length > 1 || g.auto ? `<p class="meta en-ents">Sahiplik zincirinde eşleşen şirketler: ${g.entities.map(esc).join(" · ")}</p>` : "";
    const ke = (d.kap || []).filter(r => r.group === g.key).slice(0, 15);
    const kapT = ke.length ? `<h3 class="en-h3" style="margin-top:var(--s-3)">KAP bildirimleri</h3><table class="tx"><thead><tr><th>Tarih</th><th>Olay</th><th>Santral</th><th class="num">MW</th><th>Not</th></tr></thead><tbody>${ke.map(kapRow).join("")}</tbody></table>` : "";
    const tbl = (title, list) => list.length ? `<h3 class="en-h3" style="margin-top:var(--s-3)">${title}</h3><table class="tx"><thead><tr><th>Santral / ünite</th><th>Kaynak</th><th class="num">MW</th><th class="num">Pay</th><th class="num">Başlangıç</th><th>${title.includes("Yurt") ? "Ülke" : "İl"}</th></tr></thead><tbody>
      ${list.slice(0, 80).map(([i, s]) => unitRow(i, s)).join("")}</tbody></table>${list.length > 80 ? `<p class="meta">+${list.length - 80} ünite daha (CSV'de tamamı)</p>` : ""}` : "";
    return `<div class="en-drawer1"><div class="en-dr-act"><button type="button" class="btn-sm" data-grp="${esc(g.key)}">Haritada göster</button><button type="button" class="btn-sm" data-grpu="${esc(g.key)}">Santral tablosunda aç</button></div>
      ${ents}${ownTree(g)}${kapT}${tbl("Türkiye'deki santraller (GEM)", home)}${tbl("Yurt dışı santraller (GEM)", ab)}</div>`;
  }
  const groupsTab = () => { const rows = filtered(); return `${treemap(rows)}${table(rows)}`; };

  // ─────────────────────────────── Santraller
  function unitsTab() {
    const d = S.doc, all = unitsFiltered();
    const k = S.usort, dir = S.udir;
    all.sort((a, b) => { const va = a[k], vb = b[k]; if (va == null && vb == null) return 0; if (va == null) return 1; if (vb == null) return -1;
      return (typeof va === "string" ? va.localeCompare(vb, "tr") : va - vb) * dir; });
    const shown = all.slice(0, S.ulimit), tot = all.reduce((a, u) => a + u.mw, 0);
    const bySrc = {}; all.forEach(u => { bySrc[u.s] = (bySrc[u.s] || 0) + u.mw; });
    const th = (c, l, num) => `<th scope="col" class="${num ? "num" : ""}" aria-sort="${c === k ? (dir > 0 ? "ascending" : "descending") : "none"}"><button type="button" class="th-sort" data-uc="${c}">${l}<span class="arr" aria-hidden="true">${c === k ? (dir > 0 ? "▲" : "▼") : "▼"}</span></button></th>`;
    return `${groupChip()}<section class="card card-flush" aria-labelledby="enUT">
      <div class="card-head"><h2 class="card-title" id="enUT">Santraller ve üniteler (${fmt.int(all.length)})</h2><span class="card-meta">${mw(tot)} MW · satıra tıkla: haritada aç</span></div>
      <div class="en-map-ctl">${seg("enScope", "Kapsam", scopeOpts([["tr", "Türkiye"], ["ab", "Yurt dışı"], ["all", "Tümü"]]), S.scope)}${seg("enSt", "Durum", [["op", "İşletmede"], ["pipe", "Yatırım hattı"], ["all", "Tümü"]], S.st)}</div>
      <div style="padding:0 var(--s-4) var(--s-3)">${mixBar(bySrc, tot)}</div>
      <div class="tbl-scroll en-scroll"><table class="tbl en-add en-units"><thead><tr>${th("n", "Santral / ünite")}<th scope="col">Sahipler</th>${th("s", "Kaynak")}${th("mw", "MW", 1)}${th("st", "Durum")}${th("y", "Başlangıç", 1)}${th("p", "İl / ülke")}</tr></thead><tbody>
      ${shown.map(u => `<tr class="row" data-u="${u.i}" tabindex="0"><td class="en-nm"><span>${esc(u.n)}</span></td><td class="en-own">${ownerLabel(u.i)}</td><td>${srcDot(u.s)}</td>
        <td class="num"><b>${mw(u.mw)}</b></td><td>${esc(d.status_names[u.st] || u.st)}</td><td class="num">${u.y || "—"}</td><td>${place(u)}</td></tr>`).join("")}
      </tbody></table>
      ${all.length > shown.length ? `<div class="tbl-foot"><span>${fmt.int(shown.length)} / ${fmt.int(all.length)}</span><button type="button" class="link-btn" id="enUMore">${UPAGE} daha</button></div>` : ""}
      ${all.length ? "" : sh.stateHTML({ kind: "empty", title: "Eşleşen santral yok", msg: "Aramayı ya da filtreleri değiştir." })}</div></section>`;
  }

  // ─────────────────────────────── Yatırımlar
  function timeline() {
    const d = S.doc, y0 = 2000, y1 = d.year, y2 = d.year + 5;
    const kinds = d.sources.filter(s => !S.src || s === S.src);
    const Y = {};
    for (let y = y0; y <= y2; y++) Y[y] = {};
    let before = 0, noYear = 0;
    d.units.filter(u => !u.ab && (!S.src || u.s === S.src) && kindOk(u)).forEach(u => {
      if (u.st === "operating") { if (!u.y) return; if (u.y < y0) { before += u.mw; return; } if (u.y <= y1) Y[u.y][u.s] = (Y[u.y][u.s] || 0) + u.mw; }
      else if (PIPE.has(u.st)) { if (u.y && u.y > y1 && u.y <= y2) Y[u.y][u.s] = (Y[u.y][u.s] || 0) + u.mw; else noYear += u.mw; }
    });
    const max = Math.max(...Object.values(Y).map(sum), 1);
    const step = max > 8000 ? 2000 : max > 4000 ? 1000 : max > 2000 ? 500 : max > 800 ? 200 : 100;
    const ticks = []; for (let t = 0; t <= max; t += step) ticks.push(t);
    const top = ticks[ticks.length - 1] < max ? ticks[ticks.length - 1] + step : ticks[ticks.length - 1];
    if (ticks[ticks.length - 1] < top) ticks.push(top);
    const cols = Object.entries(Y).map(([y, o]) => {
      const t = sum(o), plan = +y > y1;
      const tip = `<b>${y}${plan ? " · planlanan" : ""}</b> — ${mw(t)} MW` + kinds.filter(s => o[s]).map(s => `<br>${d.source_names[s]}: ${mw(o[s])}`).join("");
      return `<div class="en-tl-c ${plan ? "plan" : ""}" data-tip="${esc(tip)}"><div class="en-tl-s" style="height:${(t / top * 100).toFixed(2)}%">${kinds.filter(s => o[s]).map(s =>
        `<span style="flex:${o[s]};background:${color(s)}"></span>`).join("")}</div><span class="en-tl-x">${+y % 5 === 0 || +y === y1 + 1 ? y : ""}</span></div>`;
    }).join("");
    return `<section class="card" aria-labelledby="enTlT"><div class="card-head"><h2 class="card-title" id="enTlT">Yıllara göre devreye giren kapasite${S.src ? ` · ${esc(d.source_names[S.src])}` : ""}</h2>
      <span class="card-meta">Türkiye · başlangıç yılına göre MW · ${y1 + 1}–${y2}: yapım/planlamadaki projelerin hedef yılı</span></div>
      <div class="en-tl"><div class="en-tl-y">${ticks.slice().reverse().map(t => `<span>${fmt.num(t / 1000, t % 1000 ? 1 : 0)} GW</span>`).join("")}</div>
        <div class="en-tl-p">${ticks.map(t => `<i style="bottom:calc(18px + (100% - 18px) * ${(t / top).toFixed(4)})"></i>`).join("")}<div class="en-tl-cols">${cols}</div></div></div>
      <div class="en-legend">${kinds.filter(s => d.national.src[s] || d.national.pipe[s]).map(s => `<span><i style="background:${color(s)}"></i>${esc(d.source_names[s])}</span>`).join("")}<span><i class="en-plan-i"></i>planlanan</span></div>
      <p class="en-ctx">${y0} öncesi işletmede ${gw(before)}; hedef yılı belli olmayan yatırım hattı ${gw(noYear)} (grafikte yok). Başlangıç yılı bilinmeyen santraller dahil değil.</p></section>`;
  }
  function kapRow(r) {
    const d = S.doc;
    return `<tr><td class="en-date">${r.date ? fmt.date(r.date + "T12:00:00Z", { day: "numeric", month: "short", year: "2-digit" }) : "—"}</td>
      <td><span class="tag ${["devreye_alma", "kapasite_artisi"].includes(r.type) ? "up" : ""}">${esc(d.kap_types[r.type] || r.type)}</span>${r.after_gem && ["devreye_alma", "kapasite_artisi"].includes(r.type) ? ` <span class="meta" data-tip="GEM verisinin tarihinden sonra">yeni</span>` : ""}</td>
      <td>${r.src ? `<i class="en-dot" style="background:${color(r.src)}"></i>` : ""}${esc(r.plant || "")}${r.prov ? ` <span class="meta">${esc(r.prov)}</span>` : ""}${r.tr ? "" : ` <span class="tag">yurt dışı</span>`}</td>
      <td class="num">${kapMw(r)}${r.storage ? ` <span class="meta">+${mw(r.storage)} depolama</span>` : ""}</td>
      <td class="en-note-c"><a href="${esc(r.url)}" target="_blank" rel="noopener" data-tip="${esc(r.note || "")}">${esc((r.note || "KAP").slice(0, 90))}${(r.note || "").length > 90 ? "…" : ""} ↗</a>${r.rule ? ` <span class="meta" data-tip="AI kullanılamadı; kurallarla çıkarıldı, kontrol et">⚑</span>` : ""}</td></tr>`;
  }
  const kapMw = r => r.mw ? mw(r.mw) + (r.mwp ? ` <span class="meta">(${mw(r.mwp)} MWp)</span>` : "") : r.mwp ? mw(r.mwp) + ` <span class="meta">MWp</span>` : "—";
  function kapCard() {
    const d = S.doc;
    if (!(d.kap || []).length) return "";
    const rows = d.kap.filter(r => (!S.src || r.src === S.src) && (!S.kapType || r.type === S.kapType));
    const counts = {}; d.kap.forEach(r => { counts[r.type] = (counts[r.type] || 0) + 1; });
    const shown = rows.slice(0, S.kapLimit);
    const chips = [["", "Tümü", d.kap.length], ...Object.keys(d.kap_types).filter(k => counts[k]).map(k => [k, d.kap_types[k], counts[k]])]
      .map(([k, l, n]) => `<button type="button" role="radio" data-t="${k}" aria-checked="${S.kapType === k}">${esc(l)} <span class="n">${n}</span></button>`).join("");
    return `<section class="card card-flush" aria-labelledby="enKapT">
      <div class="card-head"><h2 class="card-title" id="enKapT">KAP'ta enerji yatırım bildirimleri</h2><span class="card-meta">borsa şirketleri · lisans, ÇED, YEKA, devreye alma${d.kap_updated ? " · " + fmt.dt(d.kap_updated) : ""}</span></div>
      <div style="padding:0 var(--s-4) var(--s-3)"><div class="seg en-seg" role="radiogroup" aria-label="Olay türü" id="enKapSeg">${chips}</div></div>
      <div class="tbl-scroll"><table class="tbl en-add"><thead><tr><th scope="col">Tarih</th><th scope="col">Şirket</th><th scope="col">Olay</th><th scope="col">Santral</th><th scope="col" class="num">MW</th><th scope="col">Bildirim</th></tr></thead><tbody>
      ${shown.map(r => { const g = d.byKey.get(r.group); const tk = (r.tickers || [])[0];
        return kapRow(r).replace("<td><span class=\"tag", `<td class="en-nm"><span>${esc(g ? g.name : (r.company || ""))}</span>${tk ? ` <a href="#hisse/${esc(tk)}" class="en-code">${esc(tk)}</a>` : ""}</td><td><span class="tag`); }).join("")}
      </tbody></table>
      ${rows.length > shown.length ? `<div class="tbl-foot"><span>${shown.length} / ${rows.length}</span><button type="button" class="link-btn" id="enKapMore">Daha fazla</button></div>` : ""}
      ${rows.length ? "" : sh.stateHTML({ kind: "empty", title: "Bu süzgeçte bildirim yok", compact: true })}</div></section>`;
  }
  function newPlants() {
    const d = S.doc, np = (d.epias?.new_plants || []).filter(n => !S.src || n.src === S.src);
    if (!np.length) return "";
    return `<section class="card card-flush" aria-labelledby="enNpT"><div class="card-head"><h2 class="card-title" id="enNpT">EPİAŞ'ta yeni görünen santraller</h2>
      <span class="card-meta">lisanslı santral listesine eklenenler · son 7 günün en yüksek saatlik üretimi</span></div>
      <div class="tbl-scroll"><table class="tbl en-add"><thead><tr><th scope="col">İlk görülme</th><th scope="col">Santral</th><th scope="col">Kaynak</th><th scope="col" class="num">En yüksek saatlik üretim (MW)</th><th scope="col" class="num">7 günlük üretim (MWh)</th></tr></thead><tbody>
      ${np.slice(0, 30).map(n => `<tr><td class="en-date">${esc(fmt.date(n.first_seen + "T12:00:00Z", { day: "numeric", month: "short", year: "2-digit" }))}</td><td>${esc(n.name)}</td>
        <td>${n.src ? srcDot(n.src) : `<span class="meta">üretim yok</span>`}</td>
        <td class="num">${n.peak_mw ? mw(n.peak_mw) : "—"}</td><td class="num">${n.mwh_7d ? fmt.int(n.mwh_7d) : "—"}</td></tr>`).join("")}</tbody></table></div></section>`;
  }
  function unitList(id, title, rows, limit, moreId, meta) {
    if (!rows.length) return "";
    const d = S.doc, shown = rows.slice(0, limit);
    const bySrc = {}; rows.forEach(r => { bySrc[r.s] = (bySrc[r.s] || 0) + r.mw; });
    const tot = sum(bySrc);
    return `<section class="card card-flush" aria-labelledby="${id}">
      <div class="card-head"><h2 class="card-title" id="${id}">${title}</h2><span class="card-meta">${fmt.num(tot, 0)} MW · ${fmt.int(rows.length)} ünite${meta ? " · " + meta : ""}</span></div>
      <div style="padding:0 var(--s-4) var(--s-3)">${mixBar(bySrc, tot)}</div>
      <div class="tbl-scroll"><table class="tbl en-add"><thead><tr><th scope="col">Santral / ünite</th><th scope="col">Sahip</th><th scope="col">Kaynak</th><th scope="col" class="num">MW</th><th scope="col">${rows[0].st ? "Aşama" : "Yıl"}</th><th scope="col">İl</th></tr></thead><tbody>
      ${shown.map(r => `<tr class="row" data-u="${r.i}" tabindex="0"><td class="en-nm"><span>${esc(r.n)}</span></td><td class="en-own">${ownerLabel(r.i)}</td><td>${srcDot(r.s)}</td>
        <td class="num"><b>${mw(r.mw)}</b></td><td>${r.st ? esc(d.status_names[r.st] || r.st) + (r.y ? ` · ${r.y}` : "") : r.y || "—"}</td><td>${esc(r.p || "")}</td></tr>`).join("")}
      </tbody></table>
      ${rows.length > shown.length ? `<div class="tbl-foot"><span>${shown.length} / ${rows.length}</span><button type="button" class="link-btn" id="${moreId}">Daha fazla</button></div>` : ""}</div></section>`;
  }
  function investTab() {
    const d = S.doc, bySrc = r => !S.src || r.s === S.src;
    return `${timeline()}${kapCard()}${newPlants()}
      ${unitList("enPipeT", "Yapım ve planlama aşamasındakiler", d.pipeline.filter(bySrc), S.pipeLimit, "enPipeMore", "büyükten küçüğe")}
      ${unitList("enRecT", `Son yıllarda devreye girenler (${d.year - 2}–${d.year})`, d.recent.filter(bySrc), S.recLimit, "enRecMore", "başlangıç yılına göre")}
      <p class="en-note"><b>KAP bildirimleri</b> borsa şirketlerinin lisans, ÇED, YEKA, yatırım kararı ve devreye alma açıklamalarıdır; bildirimler ücretsiz bir AI modeliyle okunur, kesin değer için bildirime bak. GEM verisinin tarihinden (${esc(Object.entries(d.gem.asof || {}).map(([k, v]) => `${d.source_names[k] || k} ${v.slice(0, 7)}`).join(", "))}) sonraki devreye almalar Gruplar sekmesindeki KAP sütununa yansır.</p>`;
  }

  // ─────────────────────────────── Değerleme (borsa şirketleri: firma değeri ÷ MW)
  // Piyasa değeri ve firma değeri temel analiz verisinden (data/fin/_screen.json). MW = Türkiye + yurt dışı işletmedeki kapasite,
  // ortaklık payıyla. Firma değeri santral dışı işleri de içerir (dağıtım, ticaret, inşaat …); bu yüzden varsayılan yalnız elektrik sektörü.
  const V = { screen: null, loading: false, err: null, y: "ev", all: false, sort: "evmw", dir: 1, scope: "all", mix: "" };
  // Ağırlıklı kaynak süzgeci: şirketin seçili kapsamdaki kapasitesinin en az yarısı o kaynakta (ya da kaynak grubunda)
  const MIXES = { ren: ["Yenilenebilir ağırlıklı", RENEW], term: ["Termik ağırlıklı", ["dogalgaz", "komur"]] };
  async function loadScreen() {
    if (V.screen || V.loading) return;
    V.loading = true;
    try {
      const r = await fetch(`data/fin/_screen.json?t=${Date.now()}`, { cache: "no-store" }); if (!r.ok) throw new Error(`HTTP ${r.status}`); V.screen = await r.json();
      if (!usdTry()) { const m = await fetch("data/macro.json", { cache: "no-store" }).then(x => x.ok ? x.json() : null).catch(() => null);
        V.usd = (m?.series || []).find(x => x.code === "TP.DK.USD.A.YTL")?.last || null; }
    }
    catch (e) { V.err = e.message || "temel analiz verisi okunamadı"; }
    finally { V.loading = false; }
    if (tab() === "degerleme") render();
  }
  const usdTry = () => (window.radar?.state?.macro?.series || []).find(x => x.code === "TP.DK.USD.A.YTL")?.last || V.usd || null;
  const relTxt = v => v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}%${fmt.num(Math.abs(v) * 100, 0)}`;
  function valRows() {
    const by = new Map((V.screen?.rows || []).map(r => [r.code, r]));
    const mix = V.mix || S.src;
    const rows = S.doc.groups.filter(g => g.ticker && by.has(g.ticker)).map(g => {
      const f = by.get(g.ticker);
      const src = {};
      if (V.scope !== "ab") for (const [k, v] of Object.entries(g.src || {})) src[k] = (src[k] || 0) + v;
      if (V.scope !== "tr") for (const [k, v] of Object.entries(g.abroad || {})) src[k] = (src[k] || 0) + v;
      const mwT = sum(src);
      const keys = mix ? (MIXES[mix]?.[1] || [mix]) : null, share = keys && mwT ? keys.reduce((a, k) => a + (src[k] || 0), 0) / mwT : null;
      const ev = f.v?.ev || null, mc = f.mcap || f.v?.mcap || null;
      const ren = mwT ? RENEW.reduce((a, k) => a + (src[k] || 0), 0) / mwT : null;
      return { g, f, src, share, code: g.ticker, name: g.name, mw: mwT, tr: g.total, ab: g.abroad_total,
        pipe: (V.scope !== "ab" ? g.pipe_total : 0) + (V.scope !== "tr" ? g.abroad_pipe || 0 : 0), renew: ren,
        mc, ev, pure: /ELEKTR/i.test(f.sector || ""), evmw: ev && mwT ? ev / mwT : null, mcmw: mc && mwT ? mc / mwT : null, sector: f.sector };
    }).filter(r => r.mw >= 5 && (V.all || r.pure) && (r[V.y] != null) && (!mix || r.share >= 0.5));
    const k = V.y === "ev" ? "evmw" : "mcmw", vals = rows.map(r => r[k]).filter(Boolean).sort((a, b) => a - b);
    const med = vals.length ? vals[Math.floor(vals.length / 2)] : null;
    rows.forEach(r => { r.rel = med && r[k] ? r[k] / med - 1 : null; });
    return { rows, med, k };
  }
  function valChart(rows, med, k) {
    if (rows.length < 3) return `<p class="meta">Grafik için yeterli şirket yok.</p>`;
    const W = 960, H = 440, P = { l: 92, r: 60, t: 16, b: 46 };
    const xs = rows.map(r => r.mw), ys = rows.map(r => r[V.y]);
    const lx = v => Math.log10(v), x0 = Math.floor(lx(Math.min(...xs))), x1 = Math.ceil(lx(Math.max(...xs)));
    const y0 = Math.floor(lx(Math.min(...ys))), y1 = Math.ceil(lx(Math.max(...ys)));
    const X = v => P.l + (lx(v) - x0) / (x1 - x0) * (W - P.l - P.r), Yp = v => H - P.b - (lx(v) - y0) / (y1 - y0) * (H - P.t - P.b);
    const tick = (a, b) => { const t = []; for (let e = a; e <= b; e++) for (const m of [1, 2, 5]) { const v = m * 10 ** e; if (lx(v) >= a - 1e-9 && lx(v) <= b + 1e-9) t.push(v); } return t; };
    const fmtTL = v => v >= 1e9 ? fmt.num(v / 1e9, v >= 1e10 ? 0 : 1) + " mr ₺" : fmt.num(v / 1e6, 0) + " mn ₺";
    const fmtMW = v => v >= 1000 ? fmt.num(v / 1000, 0) + " GW" : fmt.int(v) + " MW";
    const grid = tick(x0, x1).map(v => `<line x1="${X(v)}" x2="${X(v)}" y1="${P.t}" y2="${H - P.b}" class="g"/><text x="${X(v)}" y="${H - P.b + 16}" text-anchor="middle">${fmtMW(v)}</text>`).join("") +
      tick(y0, y1).map(v => `<line x1="${P.l}" x2="${W - P.r}" y1="${Yp(v)}" y2="${Yp(v)}" class="g"/><text x="${P.l - 6}" y="${Yp(v) + 4}" text-anchor="end">${fmtTL(v)}</text>`).join("");
    // medyan değer/MW çizgisi: y = med · x (log-log'da 45°)
    const mx0 = 10 ** x0, mx1 = 10 ** x1;
    const line = med ? (() => { const pts = [mx0, mx1].map(x => [x, med * x]).map(([x, y]) => [X(x), Yp(Math.min(Math.max(y, 10 ** y0), 10 ** y1))]);
      return `<line x1="${pts[0][0]}" y1="${pts[0][1]}" x2="${pts[1][0]}" y2="${pts[1][1]}" class="med"/>`; })() : "";
    const ramp = r => r == null ? "var(--text-3)" : r >= 0.66 ? "var(--en-v3)" : r >= 0.33 ? "var(--en-v2)" : "var(--en-v1)";
    const pmax = Math.max(...rows.map(r => r.pipe), 1);
    const dots = rows.slice().sort((a, b) => b.pipe - a.pipe).map(r => {
      const cx = X(r.mw), cy = Yp(r[V.y]), rad = 6 + Math.sqrt(r.pipe / pmax) * 16;
      const tip = `<b>${esc(r.name)} (${esc(r.code)})</b><br>${mw(r.mw)} MW (Türkiye ${mw(r.tr)}${r.ab ? `, yurt dışı ${mw(r.ab)}` : ""})<br>${V.y === "ev" ? "Firma değeri" : "Piyasa değeri"} ${fmtTL(r[V.y])}<br>${V.y === "ev" ? "FD" : "PD"}/MW ${fmt.num(r[k] / 1e6, 1)} mn ₺${r.rel != null ? ` · medyana göre ${relTxt(r.rel)}` : ""}${r.mw < 60 ? "<br>⚠ küçük kapasite: GEM lisanssız/küçük santralleri izlemiyor, MW eksik olabilir" : ""}<br>yenilenebilir ${pct(r.renew, 0)} · yatırım hattı ${mw(r.pipe)} MW`;
      return `<g class="dot" data-tip="${esc(tip)}"><a href="#hisse/${esc(r.code)}"><circle cx="${cx}" cy="${cy}" r="${rad}" fill="${ramp(r.renew)}"/><circle cx="${cx}" cy="${cy}" r="${Math.max(rad, 12)}" class="hit"/></a>
        <text x="${cx + rad + 4}" y="${cy + 4}" class="lbl">${esc(r.code)}</text></g>`; }).join("");
    return `<svg viewBox="0 0 ${W} ${H}" class="en-val-svg" role="img" aria-label="Borsa enerji şirketleri: kurulu güç ve ${V.y === "ev" ? "firma" : "piyasa"} değeri, logaritmik eksen">
      ${grid}${line}${dots}
      <text x="${(W + P.l) / 2}" y="${H - 6}" text-anchor="middle" class="ax">Kurulu güç (işletmede, pay oranıyla; log)</text>
      <text x="14" y="${(H - P.b) / 2}" text-anchor="middle" class="ax" transform="rotate(-90 14 ${(H - P.b) / 2})">${V.y === "ev" ? "Firma değeri" : "Piyasa değeri"} (log)</text>
    </svg>`;
  }
  function valTab() {
    if (!V.screen) { loadScreen(); return V.err ? sh.stateHTML({ kind: "error", title: "Temel analiz verisi yüklenemedi", msg: esc(V.err) }) :
      `<div class="card"><div class="skeleton sk-line w40"></div><div class="skeleton" style="height:320px;margin-top:12px"></div></div>`; }
    const { rows, med, k } = valRows(), usd = usdTry();
    const sk = V.sort, dir = V.dir;
    const sorted = rows.slice().sort((a, b) => { const va = a[sk], vb = b[sk]; if (va == null) return 1; if (vb == null) return -1; return (typeof va === "string" ? va.localeCompare(vb, "tr") : va - vb) * dir; });
    const th = (c, l, num, tip) => `<th scope="col" class="${num ? "num" : ""}" aria-sort="${c === sk ? (dir > 0 ? "ascending" : "descending") : "none"}"><button type="button" class="th-sort" data-vc="${c}" ${tip ? `data-tip="${esc(tip)}"` : ""}>${l}<span class="arr" aria-hidden="true">${c === sk ? (dir > 0 ? "▲" : "▼") : "▼"}</span></button></th>`;
    const L = V.y === "ev" ? "FD" : "PD";
    return `<section class="card" aria-labelledby="enValT"><div class="card-head"><h2 class="card-title" id="enValT">Borsa enerji şirketleri: megavat başına değer</h2>
      <span class="card-meta">${rows.length} şirket${(V.mix || S.src) ? ` · ${esc(MIXES[V.mix || S.src]?.[0] || S.doc.source_names[V.mix || S.src] + " ağırlıklı (%50+)")}` : ""} · ${esc(V.screen.updated ? "fiyatlar " + fmt.dt(V.screen.updated) : "")}${med ? ` · kesikli çizgi: medyan ${V.y === "ev" ? "FD" : "PD"}/MW ${fmt.num(med / 1e6, 1)} mn ₺ — üstü pahalı, altı ucuz` : ""}</span></div>
      <div class="en-map-ctl" style="padding:0 0 var(--s-3)">${seg("enValY", "Değer", [["ev", "Firma değeri"], ["mc", "Piyasa değeri"]], V.y === "ev" ? "ev" : "mc")}
        ${seg("enValS", "Kapsam", [["all", "Yurt içi + yurt dışı"], ["tr", "Yurt içi"], ["ab", "Yurt dışı"]], V.scope)}
        <label class="switch"><input type="checkbox" id="enValAll" ${V.all ? "checked" : ""}> Holding ve sanayi şirketlerini de göster</label></div>
      <div class="en-map-ctl" style="padding:0 0 var(--s-3)">${seg("enValM", "Ağırlıklı kaynak", [["", "Tüm kaynaklar"], ...Object.entries(MIXES).map(([k, [l]]) => [k, l]),
        ...S.doc.sources.filter(x => S.doc.national.src[x]).map(x => [x, esc(S.doc.source_names[x])])], V.mix || S.src)}</div>
      ${V.scope !== "all" ? `<p class="meta en-val-warn">Firma değeri şirketin tamamını kapsar; ${V.scope === "tr" ? "yalnız yurt içi MW'a bölmek yurt dışı santralleri olan şirketlerde (ör. AKSEN) oranı yüksek gösterir" : "yalnız yurt dışı MW'a bölmek, yurt içi santralleri de olan şirketlerde oranı çok yüksek gösterir"}.</p>` : ""}
      <div class="en-val-wrap">${valChart(rows, med, k)}</div>
      <div class="en-legend"><span><i style="background:var(--en-v1)"></i>yenilenebilir &lt; %33</span><span><i style="background:var(--en-v2)"></i>%33–66</span><span><i style="background:var(--en-v3)"></i>&gt; %66</span><span class="meta">daire büyüklüğü = yatırım hattı · balona tıkla: temel analiz</span></div></section>
    <section class="card card-flush" aria-labelledby="enValTT"><div class="card-head"><h2 class="card-title" id="enValTT">${L}/MW sıralaması</h2><span class="card-meta">ucuzdan pahalıya · medyan ${med ? fmt.num(med / 1e6, 1) + " mn ₺/MW" : "—"}${usd && med ? ` (≈ ${fmt.num(med / usd / 1e6, 2)} mn $/MW)` : ""}</span></div>
      <div class="tbl-scroll"><table class="tbl en-add"><thead><tr>${th("code", "Şirket")}${th("mw", "Kurulu güç (MW)", 1, `${V.scope === "tr" ? "Yurt içi" : V.scope === "ab" ? "Yurt dışı" : "Yurt içi + yurt dışı"}, işletmede, ortaklık payıyla`)}<th scope="col">Kaynak dağılımı</th>${th("renew", "Yenilenebilir", 1)}${th("pipe", "Yatırım hattı (MW)", 1)}
        ${th("mc", "Piyasa değeri", 1)}${th("ev", "Firma değeri", 1, "Piyasa değeri + net borç + azınlık payları")}${th(k, `${L}/MW (mn ₺)`, 1)}<th scope="col" class="num">${L}/MW (mn $)</th>${th("rel", "Medyana göre", 1)}</tr></thead><tbody>
      ${sorted.map(r => `<tr><td class="en-nm"><a href="#hisse/${esc(r.code)}" class="en-code">${esc(r.code)}</a> <span>${esc(r.name)}</span>${r.mw < 60 ? ` <span class="tag warn" data-tip="GEM 1 MW altı güneşi ve lisanssız santrallerin çoğunu izlemiyor; bu şirketin kapasitesi eksik görünebilir, oran şişkin olabilir">kapsam eksik olabilir</span>` : ""}${r.pure ? "" : ` <span class="tag" data-tip="${esc(r.sector || "")}: firma değerinin büyük kısmı enerji dışı işlerden">enerji dışı ağırlıklı</span>`}</td>
        <td class="num">${mw(r.mw)}${V.scope === "all" && r.ab ? ` <span class="meta" data-tip="yurt dışı ${mw(r.ab)} MW">*</span>` : ""}</td><td class="en-mixc">${mixBar(r.src, r.mw)}</td><td class="num">${pct(r.renew, 0)}</td><td class="num">${r.pipe ? mw(r.pipe) : "—"}</td>
        <td class="num">${r.mc ? fmt.num(r.mc / 1e9, 1) + " mr" : "—"}</td><td class="num">${r.ev ? fmt.num(r.ev / 1e9, 1) + " mr" : "—"}</td>
        <td class="num"><b>${r[k] ? fmt.num(r[k] / 1e6, 1) : "—"}</b></td><td class="num">${usd && r[k] ? fmt.num(r[k] / usd / 1e6, 2) : "—"}</td>
        <td class="num ${r.rel == null ? "" : r.rel < 0 ? "up" : "down"}">${relTxt(r.rel)}</td></tr>`).join("")}
      </tbody></table></div></section>
    <p class="en-note"><b>Nasıl okunur:</b> megavat başına değer düşükse piyasa şirketin santrallerine daha az değer biçiyor demektir. Bu tek başına ucuzluk değildir: kaynak türü (yenilenebilir/YEKDEM gelirleri, kömür), santral yaşı, borç, lisans süresi ve enerji dışı işler değeri etkiler. Firma değeri = piyasa değeri + net borç + azınlık payları (temel analiz sekmesindeki son bilanço). Kurulu güç GEM verisinden, ortaklık payıyla; GEM'in izlemediği küçük santraller ve lisanssız güneş dahil değil. Kod: şirketin kendi borsa kodu; borsadaki ortağı olan santral şirketleri (↳) burada yok.</p>`;
  }

  // ─────────────────────────────── ana çizim
  function render() {
    if (sh.route !== "enerji") return;
    const body = $("#enBody");
    if (!S.loaded) return S.error ? renderError() : renderLoading();
    const d = S.doc, t = tab();
    $("#enSrcSel").innerHTML = `<option value="">Tüm kaynaklar</option>` + d.sources.filter(s => d.national.src[s] || d.national.pipe[s]).map(s => `<option value="${s}" ${S.src === s ? "selected" : ""}>${d.source_names[s]}</option>`).join("");
    $("#enQ").placeholder = t === "harita" || t === "santraller" ? "Santral, şirket, il ya da ülke ara…" : "Grup, şirket, santral ya da kod ara…";
    const newer = (d.gem.newer || []);
    $("#enSrcLine").innerHTML = (newer.length ? `<span class="tag warn" data-tip="${esc(newer.map(n => `${n.tracker}: ${n.release}`).join(", "))}">GEM'de yeni sürüm var</span> ` : "") + `Kaynak: <a href="https://globalenergymonitor.org" target="_blank" rel="noopener">Global Energy Monitor</a> Integrated Power ve Ownership izleyicileri (CC BY 4.0, aktarım ${esc(d.gem.imported || "")})${d.epias ? ` · <a href="https://seffaflik.epias.com.tr" target="_blank" rel="noopener">EPİAŞ Şeffaflık</a> (YEKDEM)` : ""}${(d.kap || []).length ? ` · KAP bildirimleri` : ""} · ${fmt.int(d.units.length)} ünite · ${fmt.int(d.groups.length)} sahip/grup`;
    $("#enTabs").innerHTML = TABS.map(([k, l]) => `<a role="tab" href="#enerji${k ? "/" + k : ""}" aria-selected="${t === k}" ${t === k ? `aria-current="page"` : ""}>${l}</a>`).join("");
    const sc = $(".en-scroll")?.scrollTop || 0;
    const keepMap = t === "harita" && $("#enMap") && Map_.map && $("#enBody").dataset.tab === "harita";
    if (keepMap) {                                                   // haritayı yeniden kurma: yalnız işaretleri ve kontrolleri yenile
      const ctl = $(".en-map-ctl"), tmp = document.createElement("div"); tmp.innerHTML = mapTab();
      ctl.replaceWith(tmp.querySelector(".en-map-ctl"));
      $("#enMapEmpty").innerHTML = S.year == null ? emptyNote() : "";
      const tb = $(".en-time"), ntb = tmp.querySelector(".en-time"); if (tb && ntb) tb.replaceWith(ntb);
      const chip = $("#enBody .en-chip-row"), nchip = tmp.querySelector(".en-chip-row");
      if (chip) chip.remove(); if (nchip) $(".en-mapcard").before(nchip);
      Map_.draw();
    } else {
      body.dataset.tab = t;
      body.innerHTML = `<div class="view" style="gap:var(--s-4)">${t === "harita" ? mapTab() : t === "gruplar" ? groupsTab() : t === "santraller" ? unitsTab() : t === "yatirimlar" ? investTab() : t === "degerleme" ? valTab() : overview()}</div>`;
      if (t === "harita") Map_.mount($("#enMap")).then(() => S.focus != null && (Map_.open(S.focus), S.focus = null))
        .catch(e => { $("#enMap").innerHTML = sh.stateHTML({ kind: "error", title: "Harita yüklenemedi", msg: esc(e.message) }); });
    }
    if ($(".en-scroll")) $(".en-scroll").scrollTop = sc;
    bind();
  }
  function bind() {
    $("#enMore")?.addEventListener("click", () => { S.limit += PAGE; render(); });
    $("#enAll")?.addEventListener("click", () => { S.limit = 1e9; render(); });
    $("#enLess")?.addEventListener("click", () => { S.limit = PAGE; render(); $("#enTblT")?.scrollIntoView({ block: "start" }); });
    $("#enUMore")?.addEventListener("click", () => { S.ulimit += UPAGE; render(); });
    $("#enRecMore")?.addEventListener("click", () => { S.recLimit += 30; render(); });
    $("#enPipeMore")?.addEventListener("click", () => { S.pipeLimit += 30; render(); });
    $("#enKapMore")?.addEventListener("click", () => { S.kapLimit += 30; render(); });
    $("#enSrcClear")?.addEventListener("click", () => setSrc(""));
    $("#enPlay")?.addEventListener("click", togglePlay);
    $("#enYear")?.addEventListener("input", e => { stopPlay(); setYear(+e.target.value); });
    $("#enYearOff")?.addEventListener("click", () => setYear(null));
    $("#enValAll")?.addEventListener("change", e => { V.all = e.target.checked; render(); });
    segBindV();
    $("#enGroupClear")?.addEventListener("click", () => { S.group = ""; S.ulimit = UPAGE; render(); });
    $$("#enKapSeg button").forEach(b => b.onclick = () => { S.kapType = b.dataset.t; S.kapLimit = 15; render(); $(`#enKapSeg button[data-t="${b.dataset.t}"]`)?.focus(); });
    const segBind = (id, fn) => { const el = $("#" + id); if (!el) return; sh.radioKeys?.(el); $$(`#${id} button`).forEach(b => b.onclick = () => { fn(b.dataset.v); S.ulimit = UPAGE; render(); $(`#${id} button[data-v="${b.dataset.v}"]`)?.focus(); }); };
    segBind("enScope", v => { S.scope = v; });
    segBind("enSt", v => { S.st = v; });
    segBind("enView", v => { S.mapView = v; });
    $$("#enBody .th-sort[data-vc]").forEach(b => b.onclick = () => { const c = b.dataset.vc; V.dir = V.sort === c ? -V.dir : (c === "code" ? 1 : c === "mw" || c === "pipe" || c === "mc" || c === "ev" || c === "renew" ? -1 : 1); V.sort = c; render(); $(`#enBody .th-sort[data-vc="${c}"]`)?.focus(); });
    $$("#enBody .th-sort[data-c]").forEach(b => b.onclick = () => {
      const c = b.dataset.c;
      S.dir = S.sort === c ? -S.dir : (["name", "code"].includes(c) ? 1 : -1); S.sort = c; S.limit = PAGE;
      render(); $(`#enBody .th-sort[data-c="${c}"]`)?.focus();
    });
    $$("#enBody .th-sort[data-uc]").forEach(b => b.onclick = () => {
      const c = b.dataset.uc;
      S.udir = S.usort === c ? -S.udir : (["n", "s", "st", "p"].includes(c) ? 1 : -1); S.usort = c; S.ulimit = UPAGE;
      render(); $(`#enBody .th-sort[data-uc="${c}"]`)?.focus();
    });
  }
  function segBindV() {
    $$("#enValY button").forEach(b => b.onclick = () => { V.y = b.dataset.v === "ev" ? "ev" : "mc"; if (V.sort === "evmw" || V.sort === "mcmw") V.sort = V.y + "mw"; render(); });
    $$("#enValS button").forEach(b => b.onclick = () => { V.scope = b.dataset.v; render(); });
    $$("#enValM button").forEach(b => b.onclick = () => { const v = b.dataset.v; V.mix = MIXES[v] ? v : ""; S.src = MIXES[v] ? "" : v; render(); });
  }
  function setSrc(s) { S.src = s; S.limit = PAGE; S.recLimit = 12; S.pipeLimit = 12; S.ulimit = UPAGE; render(); }
  function showOnMap({ unit = null, group = "" } = {}) {
    if (group) { S.group = group; S.st = "all"; S.mapView = "units"; const g = S.doc.byKey.get(group); S.scope = g && !g.total && g.abroad_total ? "ab" : g && g.abroad_total ? "all" : "tr"; }
    if (unit != null) { const u = S.doc.units[unit]; S.scope = u.ab ? "ab" : "tr"; if (!stOk(u)) S.st = "all"; if (S.src && u.s !== S.src) S.src = ""; S.focus = unit; S.mapView = "units"; }
    if (tab() === "harita") { render(); if (S.focus != null) { Map_.open(S.focus); S.focus = null; } }
    else sh.go("enerji", { param: "harita" });
  }
  function renderLoading() {
    $("#enSrcLine").innerHTML = `<span class="skeleton sk-line w40" style="display:inline-block;width:320px"></span>`;
    $("#enBody").dataset.tab = "";
    $("#enBody").innerHTML = `<div class="view" style="gap:var(--s-4)" aria-busy="true" aria-label="Enerji verisi yükleniyor">
      <div class="kpi-grid">${Array.from({ length: 6 }, () => `<div class="kpi"><div class="skeleton sk-line w60"></div><div class="skeleton sk-line lg w40"></div></div>`).join("")}</div>
      <div class="card"><div class="skeleton sk-line w40"></div><div class="skeleton" style="height:18px;margin-top:12px"></div></div>
      <div class="card card-flush"><table class="tbl"><tbody>${sh.skeletonRows(8, 8)}</tbody></table></div></div>`;
  }
  function renderError() {
    $("#enSrcLine").textContent = "";
    $("#enBody").dataset.tab = "";
    $("#enBody").innerHTML = S.missing ? sh.stateHTML({ kind: "info", title: "Enerji verisi henüz oluşmadı", msg: "Kurulu güç envanteri ilk çalıştırmadan sonra burada görünecek." }) :
      sh.stateHTML({ kind: "error", title: "Enerji verisi yüklenemedi", msg: esc(S.error), action: "Tekrar dene", actionId: "enRetry" });
    $("#enRetry")?.addEventListener("click", () => load(true));
  }
  function toggle(tr) {
    const k = tr.dataset.k;
    S.open.has(k) ? S.open.delete(k) : S.open.add(k);
    render();
    $(`#enBody tr.row[data-k="${CSS.escape(k)}"]`)?.focus();
  }

  // ─────────────────────────────── dışa aktarma
  function exportGroups() {
    const ex = window.radarExport, d = S.doc;
    const rows = filtered().map(g => ({ grup: g.name, kod: g.ticker || "", borsadaki_ortak: g.parent || "", tur: kindOf(g), eslesmedi: g.auto ? "evet" : "",
      kurulu_guc_mw_pay_orani: g.total, konsolide_mw: g.cons, turkiye_payi: g.share, ...Object.fromEntries(d.sources.map(s => [`${s}_mw`, g.src[s] || 0])),
      yenilenebilir_payi: g.renew ?? "", yatirim_hatti_mw: g.pipe_total, yurt_disi_mw: g.abroad_total, yurt_disi_yatirim_hatti_mw: g.abroad_pipe, ulkeler: g.countries.join("; "), unite: g.n }));
    ex.download(`enerji_gruplar_${ex.stamp()}.csv`, ex.toCSV(rows), "text/csv;charset=utf-8");
  }
  function exportUnits(list) {
    const ex = window.radarExport, d = S.doc;
    const rows = (list || d.units).map(u => ({ santral: u.n, santral_en: u.en || "", kaynak: d.source_names[u.s], mw: u.mw, durum: d.status_names[u.st] || u.st, baslangic: u.y || "",
      il: u.p || "", ulke: u.cn || "Türkiye", enlem: u.la ?? "", boylam: u.lo ?? "",
      sahipler: d.owners[u.i].map(([g, s]) => `${g.name}${g.ticker ? ` (${g.ticker})` : ""} ${Math.round(s * 1000) / 10}%`).join("; "), gem_sahip: u.o || "", ana_ortak: u.pa || "", lisans: u.lic || "", gem: u.u || "" }));
    ex.download(`enerji_santraller_${ex.stamp()}.csv`, ex.toCSV(rows), "text/csv;charset=utf-8");
  }

  // ─────────────────────────────── bağla
  $$("#enKind button").forEach(b => b.onclick = () => {
    S.kind = b.dataset.k; S.limit = PAGE; S.ulimit = UPAGE; $$("#enKind button").forEach(x => x.setAttribute("aria-checked", String(x === b))); render();
  });
  sh.radioKeys($("#enKind"));
  $("#enSrcSel").onchange = e => setSrc(e.target.value);
  // ─────────────────────────────── arama: yazarken kısa liste (gruplar + santraller)
  const Sug = { items: [], i: -1 };
  const hl = (txt, q) => { const f = fold(txt), k = f.indexOf(q); return k < 0 || !q ? esc(txt) : esc(txt.slice(0, k)) + "<mark>" + esc(txt.slice(k, k + q.length)) + "</mark>" + esc(txt.slice(k + q.length)); };
  function suggest(raw) {
    const box = $("#enSug"), inp = $("#enQ"), q = fold(raw);
    if (!S.loaded || q.length < 2) return closeSug();
    const d = S.doc;
    // Puan: kod tam eşleşme > ad başı > kelime başı > adda geçiyor > sahiplik zincirindeki şirket adında geçiyor
    const score = g => { const nm = fold(g.name), cd = fold(g.code);
      return cd === q ? 5 : nm.startsWith(q) ? 4 : nm.split(" ").some(w => w.startsWith(q)) ? 3 : nm.includes(q) || cd.startsWith(q) ? 2 : g.entities.some(n => fold(n).includes(q)) ? 1 : 0; };
    const listed = g => !!(g.ticker || g.parent);
    const hit = d.groups.map(g => [g, score(g)]).filter(([, sc]) => sc);
    const ord = (a, b) => b[1] - a[1] || (b[0].total + b[0].abroad_total) - (a[0].total + a[0].abroad_total);
    const gl = hit.filter(([g]) => listed(g)).sort((a, b) => (b[0].total + b[0].abroad_total) - (a[0].total + a[0].abroad_total) || b[1] - a[1]).slice(0, 25).map(([g]) => g);
    const go = hit.filter(([g]) => !listed(g)).sort(ord).slice(0, gl.length ? 5 : 8).map(([g]) => g);
    const more = hit.length - gl.length - go.length;
    const gs = [...gl, ...go];
    const us = d.units.filter(u => fold(u.n).includes(q) || fold(u.en || "").includes(q)).sort((a, b) => b.mw - a.mw).slice(0, 6);
    Sug.items = [...gs.map(g => ({ g })), ...us.map(u => ({ u }))]; Sug.i = -1;
    if (!Sug.items.length) { box.innerHTML = `<div class="en-sug-e">Eşleşen grup ya da santral yok</div>`; box.hidden = false; inp.setAttribute("aria-expanded", "true"); return; }
    let k = 0;
    const gRow = g => `<div class="en-sug-i" role="option" id="enSug${k}" data-n="${k++}">
        <span class="en-sug-n">${hl(g.name, q)}${g.code ? ` <span class="en-code">${esc(g.code)}</span>` : ""}${g.kind === "kamu" ? ` <span class="tag na">kamu</span>` : ""}${!fold(g.name).includes(q) && !fold(g.code).includes(q) ? (n => n ? ` <span class="en-sug-e2">↳ ${hl(n, q)}</span>` : "")(g.entities.find(n => fold(n).includes(q))) : ""}</span>
        <span class="en-sug-m">${g.total ? gw(g.total) : ""}${g.abroad_total ? `${g.total ? " · " : ""}yurt dışı ${gw(g.abroad_total)}` : ""}${!g.total && !g.abroad_total && g.pipe_total ? `yatırım hattı ${gw(g.pipe_total)}` : ""}</span>
        <span class="en-sug-x">${mixBar(g.total ? g.src : g.abroad, g.total || g.abroad_total, { h: 4 })}</span></div>`;
    box.innerHTML = (gl.length ? `<div class="en-sug-h">Borsa şirketleri (${gl.length})</div>` + gl.map(gRow).join("") : "") +
      (go.length ? `<div class="en-sug-h">${gl.length ? "Diğer şirketler" : "Gruplar ve şirketler"}</div>` + go.map(gRow).join("") : "") +
      (more > 0 ? `<button type="button" class="en-sug-all" data-all="1">+${fmt.int(more)} şirket daha · Gruplar sekmesinde tümünü gör</button>` : "") +
      (us.length ? `<div class="en-sug-h">Santraller</div>` + us.map(u => `<div class="en-sug-i" role="option" id="enSug${k}" data-n="${k++}">
        <span class="en-sug-n"><i class="en-dot" style="background:${color(u.s)}"></i>${hl(u.n, q)}</span>
        <span class="en-sug-m">${mw(u.mw)} MW · ${u.ab ? esc(u.cn) : esc(u.p || "")}${u.st !== "operating" ? " · " + esc(d.status_names[u.st] || u.st) : ""}</span></div>`).join("") : "") +
      `<div class="en-sug-f">Enter: “${esc(raw)}” ile süz · ↑↓ seç · Esc kapat</div>`;
    box.hidden = false; inp.setAttribute("aria-expanded", "true");
  }
  function closeSug() { const box = $("#enSug"); box.hidden = true; box.innerHTML = ""; Sug.items = []; Sug.i = -1; $("#enQ").setAttribute("aria-expanded", "false"); $("#enQ").removeAttribute("aria-activedescendant"); }
  function pickSug(n) {
    const it = Sug.items[n]; if (!it) return;
    closeSug(); $("#enQ").value = ""; S.q = "";
    if (it.u) return showOnMap({ unit: it.u.i });
    const g = it.g, tb = tab();
    if (tb === "gruplar") { S.open.add(g.key); const i = filtered().findIndex(x => x.key === g.key); if (i >= S.limit) S.limit = i + 1; render();
      $(`#enBody tr.row[data-k="${CSS.escape(g.key)}"]`)?.scrollIntoView({ block: "center" }); return; }
    if (tb === "santraller") { S.group = g.key; S.st = "all"; S.scope = "all"; S.ulimit = UPAGE; return render(); }
    showOnMap({ group: g.key });
  }
  function moveSug(dx) {
    if (!Sug.items.length) return;
    Sug.i = (Sug.i + dx + Sug.items.length) % Sug.items.length;
    $$("#enSug .en-sug-i").forEach((el, i) => el.classList.toggle("on", i === Sug.i));
    const el = $(`#enSug${Sug.i}`); el?.scrollIntoView({ block: "nearest" }); $("#enQ").setAttribute("aria-activedescendant", `enSug${Sug.i}`);
  }
  let t; $("#enQ").oninput = e => { const v = e.target.value.trim(); suggest(v); clearTimeout(t); t = setTimeout(() => { S.q = v; S.limit = PAGE; S.ulimit = UPAGE; render(); }, 250); };
  $("#enQ").addEventListener("keydown", e => {
    if ($("#enSug").hidden) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); moveSug(e.key === "ArrowDown" ? 1 : -1); }
    else if (e.key === "Enter") { e.preventDefault(); Sug.i >= 0 ? pickSug(Sug.i) : closeSug(); }
    else if (e.key === "Escape") { e.preventDefault(); closeSug(); }
  });
  $("#enQ").addEventListener("focus", e => { if (e.target.value.trim().length >= 2) suggest(e.target.value.trim()); });
  $("#enSug").addEventListener("mousedown", e => {
    const it = e.target.closest(".en-sug-i");
    if (it) { e.preventDefault(); return pickSug(+it.dataset.n); }
    if (e.target.closest("[data-all]")) { e.preventDefault(); closeSug(); S.q = $("#enQ").value.trim(); S.limit = PAGE; tab() === "gruplar" ? render() : sh.go("enerji", { param: "gruplar" }); }
  });
  document.addEventListener("mousedown", e => { if (!e.target.closest("#enSug, #enQ")) closeSug(); });
  $("#enBody").addEventListener("click", e => {
    const sc = e.target.closest(".en-sc");
    if (sc) return setSrc(S.src === sc.dataset.s ? "" : sc.dataset.s);
    const tm = e.target.closest(".en-tm-i");
    if (tm) { S.open.add(tm.dataset.k); const rows = filtered(); const i = rows.findIndex(g => g.key === tm.dataset.k); if (i >= S.limit) S.limit = i + 1;
      render(); $(`#enBody tr.row[data-k="${CSS.escape(tm.dataset.k)}"]`)?.scrollIntoView({ block: "center" }); return; }
    const gb = e.target.closest("[data-grp]");
    if (gb) { e.preventDefault(); return showOnMap({ group: gb.dataset.grp }); }
    const gu = e.target.closest("[data-grpu]");
    if (gu) { S.group = gu.dataset.grpu; S.st = "all"; S.scope = "all"; S.ulimit = UPAGE; return sh.go("enerji", { param: "santraller" }); }
    const sb = e.target.closest("[data-scope]");
    if (sb) { S.scope = sb.dataset.scope; return render(); }
    const ab = e.target.closest("[data-abroad]");
    if (ab) { e.preventDefault(); S.scope = "ab"; S.group = ""; return sh.go("enerji", { param: "harita" }); }
    const ul = e.target.closest(".en-ulink, .en-ot-plant");
    if (ul) return showOnMap({ unit: +ul.dataset.u });
    const ur = e.target.closest("tr.row[data-u]");
    if (ur && !e.target.closest("a, button")) { const u = S.doc.units[+ur.dataset.u]; if (u.la != null) showOnMap({ unit: u.i }); return; }
    const tr = e.target.closest("tr.row[data-k]");
    if (tr && !e.target.closest("a, button")) toggle(tr);
  });
  $("#enBody").addEventListener("keydown", e => {
    const tr = e.target.closest("tr.row");
    if (!tr || e.target !== tr) return;
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); tr.dataset.u != null ? showOnMap({ unit: +tr.dataset.u }) : toggle(tr); }
    else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const rows = $$("#enBody tr.row"), i = rows.indexOf(tr);
      rows[i + (e.key === "ArrowDown" ? 1 : -1)]?.focus();
    }
  });
  // harita açılır pencerelerindeki "… santralleri" düğmesi (Leaflet pencereleri #enBody içinde, ama olay yine de yakalansın)
  document.addEventListener("click", e => {
    const gb = e.target.closest(".leaflet-popup [data-grp]");
    if (gb && !e.target.closest("#enBody")) { e.preventDefault(); showOnMap({ group: gb.dataset.grp }); }
  });
  addEventListener("themechange", () => { if (sh.route === "enerji" && S.loaded) { tab() === "harita" ? Map_.retheme() : render(); } });

  sh.register("enerji", {
    onShow() { S.loaded ? render() : load(); },
    async refresh() { await load(true); },
    exports() {
      const has = S.loaded;
      return [{ label: "Gruplar (CSV)", hint: "filtreye göre", run: exportGroups, disabled: !has },
        { label: "Santraller (CSV)", hint: "süzgece göre: konum, sahipler ve paylar", run: () => exportUnits(unitsFiltered()), disabled: !has },
        { label: "Tüm santraller (CSV)", hint: "Türkiye ve yurt dışı, tüm durumlar", run: () => exportUnits(), disabled: !has }];
    },
    exportInfo: () => S.loaded ? `${KINDS[S.kind]}${S.src ? " · " + S.doc.source_names[S.src] : ""}${S.q ? ` · arama “${S.q}”` : ""}` : "",
    exportNote: "Enerji verisi henüz yüklenmedi",
  });
})();
