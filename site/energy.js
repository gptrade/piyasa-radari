/* Piyasa Radarı — Enerji: Türkiye elektrik üretim şirketlerinin kurulu güç envanteri.
   Veri: data/enerji/kurulu_guc.json (enerji.yml). Santral ve sahiplik: Global Energy Monitor izleyicileri (CC BY 4.0);
   Türkiye bağlamı: EPİAŞ Şeffaflık Platformu (YEKDEM lisanslı/lisanssız kurulu güç).
   Grup MW'ı pay oranına göredir (ortaklık payı × ünite gücü); konsolide = %50+ payla kontrol edilen ünitelerin tam gücü. */
(() => {
  "use strict";
  const sh = window.shell;
  const { $, $$, esc, fmt } = sh;
  const SRC = "data/enerji/kurulu_guc.json";
  const PAGE = 25;
  const KINDS = { all: "Tümü", listed: "Borsada", private: "Borsa dışı", kamu: "Kamu" };

  const S = { doc: null, loaded: false, loading: false, error: null, missing: false,
    q: "", kind: "all", src: "", kapType: "", kapLimit: 15, sort: "total", dir: -1, open: new Set(), limit: PAGE, recLimit: 12, pipeLimit: 12 };

  // ─────────────────────────────── birimler
  const mw = v => v == null ? "—" : fmt.num(v, v >= 100 ? 0 : 1);
  const gw = v => v == null ? "—" : fmt.num(v / 1000, 1) + " GW";
  const pct = (v, d = 1) => v == null ? "—" : "%" + fmt.num(v * 100, d);
  const color = s => `var(--en-${s})`;
  const sum = o => Object.values(o || {}).reduce((a, b) => a + b, 0);

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
    d.groups.forEach((g, i) => { g.code = g.ticker || g.parent || ""; g.rank = i + 1; g.units.forEach(([u, s]) => d.owners[u].push([g, s])); });
    return d;
  }
  const kindOf = g => g.kind === "kamu" ? "kamu" : g.ticker || g.parent ? "listed" : "private";
  const ownerLabel = i => {
    const os = S.doc.owners[i];
    if (!os.length) return `<span class="meta">sahip bilgisi yok</span>`;
    return os.sort((a, b) => b[1] - a[1]).slice(0, 2).map(([g, s]) =>
      `${esc(g.name)}${g.ticker ? ` <a href="#hisse/${esc(g.ticker)}" class="en-code">${esc(g.ticker)}</a>` : ""}${s < 0.999 ? ` <span class="meta">${pct(s, 0)}</span>` : ""}`).join(" · ");
  };

  // ─────────────────────────────── süzme
  function filtered() {
    const d = S.doc, q = S.q.toLocaleLowerCase("tr");
    let rows = d.groups.filter(g => S.kind === "all" || kindOf(g) === S.kind);
    rows.forEach(g => { g.srcMw = S.src ? g.src[S.src] || 0 : g.total; g.srcPipe = S.src ? g.pipe[S.src] || 0 : g.pipe_total; });
    if (S.src) rows = rows.filter(g => g.srcMw > 0 || g.srcPipe > 0);
    if (q) rows = rows.filter(g => g.name.toLocaleLowerCase("tr").includes(q) || g.code.toLocaleLowerCase("tr").includes(q) ||
      g.entities.some(n => n.toLocaleLowerCase("tr").includes(q)) || g.units.some(([u]) => d.units[u].n.toLocaleLowerCase("tr").includes(q)));
    const k = S.sort === "total" ? "srcMw" : S.sort === "pipe_total" ? "srcPipe" : S.sort;
    return rows.sort((a, b) => {
      const va = a[k], vb = b[k];
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      return (typeof va === "string" ? va.localeCompare(vb, "tr") : va - vb) * S.dir;
    });
  }

  // ─────────────────────────────── çizim parçaları
  function mixBar(src, total, { h = 10 } = {}) {
    const d = S.doc;
    if (!total) return "";
    const ks = d.sources.filter(s => src[s] > 0);
    return `<span class="en-mix" style="height:${h}px" role="img" aria-label="${esc(ks.map(s => `${d.source_names[s]} ${pct(src[s] / total, 0)}`).join(", "))}">${ks.map(s =>
      `<span style="width:${(src[s] / total * 100).toFixed(2)}%;background:${color(s)}" data-tip="${esc(`${d.source_names[s]}: ${mw(src[s])} MW (${pct(src[s] / total)})`)}"></span>`).join("")}</span>`;
  }
  function legend(src, total) {
    const d = S.doc;
    return `<div class="en-legend">${d.sources.filter(s => src[s] > 0).map(s =>
      `<span><i style="background:${color(s)}"></i>${d.source_names[s]} <b>${gw(src[s])}</b> <em>${pct(src[s] / total)}</em></span>`).join("")}</div>`;
  }
  function kpis() {
    const d = S.doc, n = d.national;
    const ren = ["hidro", "ruzgar", "gunes", "jeotermal", "diger"].reduce((s, k) => s + (n.src[k] || 0), 0);
    const big = d.groups.find(g => g.kind !== "kamu");
    const k = (label, value, sub = "", tip = "") => `<div class="kpi" ${tip ? `data-tip="${esc(tip)}"` : ""}><span class="kpi-label">${label}</span><span class="kpi-value">${value}</span>${sub ? `<span class="kpi-sub">${sub}</span>` : ""}</div>`;
    return `<div class="kpi-grid">
      ${k("İşletmedeki kurulu güç", gw(n.total), "izlenen santraller", "Global Energy Monitor izleyicilerindeki işletmedeki üniteler: güneş ≥1 MW, rüzgâr, hidro, kömür, doğalgaz, biyoenerji. Jeotermal ve 1 MW altı çatı/dağıtık güneş dahil değil.")}
      ${k("Yenilenebilir payı", pct(ren / (n.total || 1)))}
      ${k("Borsa şirketlerinin payı", pct(d.listed_share), "pay oranıyla", "Borsadaki şirketlerin ve borsadaki ortağa bağlı santral şirketlerinin, ortaklık payları oranında kapasitesi ÷ izlenen toplam")}
      ${k("İlk 10 grubun payı", pct(d.top10))}
      ${k("Yatırım hattı", gw(n.pipe_total), "yapım ve planlama", "Yapım, izin/finansman ve duyurulmuş aşamadaki üniteler")}
      ${k("En büyük özel grup", big ? esc(big.name) : "—", big ? `${gw(big.total)} · ${pct(big.share)}` : "")}
    </div>`;
  }
  function national() {
    const d = S.doc, n = d.national, e = d.epias;
    const ctx = e ? (() => {
      const lic = sum(e.yekdem_licensed), un = sum(e.yekdem_unlicensed);
      return `<p class="en-ctx">EPİAŞ YEKDEM (${esc(fmt.date(e.period + "T12:00:00Z", { month: "long", year: "numeric" }))}): lisanslı ${gw(lic)}, <b>lisanssız ${gw(un)}</b> (güneş ${gw(e.yekdem_unlicensed.gunes)}). Lisanssız santrallerin çoğu bu envanterde sahibiyle yer almıyor.</p>`;
    })() : "";
    return `<section class="card" aria-labelledby="enNatT">
      <div class="card-head"><h2 class="card-title" id="enNatT">Türkiye kaynak dağılımı (işletmede)</h2><span class="card-meta">${gw(n.total)} · sahibi bilinmeyen ${gw(n.unowned)}</span></div>
      ${mixBar(n.src, n.total, { h: 18 })}${legend(n.src, n.total)}${ctx}</section>`;
  }

  function table(rows) {
    const d = S.doc;
    const COLS = [["rank", "#", 1], ["name", "Grup / şirket"], ["code", "Kod"], ["total", S.src ? `${d.source_names[S.src]} (MW)` : "Kurulu güç (MW)", 1], ["share", "Türkiye payı", 1],
      ["mix", "Kaynak dağılımı"], ["renew", "Yenilenebilir", 1], ["cons", "Konsolide (MW)", 1], ["pipe_total", "Yatırım hattı (MW)", 1], ["kap_added", "KAP: GEM sonrası (MW)", 1], ["n", "Ünite", 1]];
    const TIPS = { total: "Ortaklık payı oranında işletmedeki kurulu güç", share: "Grubun kapasitesi ÷ izlenen Türkiye toplamı", cons: "%50 ve üzeri payla kontrol edilen ünitelerin tam gücü",
      pipe_total: "Yapım, izin/finansman ve duyurulmuş aşamadaki üniteler (pay oranıyla)", kap_added: "GEM verisinin tarihinden sonra KAP'ta bildirilen devreye alma ve kapasite artışları (MWe; yalnız MWp verilmişse MWp)", n: "İşletmedeki ünite / faz sayısı", code: "Borsa kodu; santral şirketi borsada değilse borsadaki ortağın kodu (↳)" };
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
    const st = u.st === "operating" ? "" : ` <span class="tag ${u.st === "construction" ? "up" : ""}">${esc(d.status_names[u.st] || u.st)}</span>`;
    return `<tr><td>${u.u ? `<a href="${esc(u.u)}" target="_blank" rel="noopener">${esc(u.n)}</a>` : esc(u.n)}${st}</td>
      <td><i class="en-dot" style="background:${color(u.s)}"></i>${esc(d.source_names[u.s])}</td><td class="num">${mw(u.mw)}</td>
      <td class="num">${share == null ? "" : pct(share, share < 1 ? 1 : 0)}</td><td class="num">${u.y || "—"}</td><td>${esc(u.p || "")}</td></tr>`;
  }
  function drawer(g) {
    const us = g.units.filter(([i]) => !S.src || S.doc.units[i].s === S.src);
    const ents = g.entities.length > 1 || g.auto ? `<p class="meta en-ents">Sahiplik zincirinde eşleşen şirketler: ${g.entities.map(esc).join(" · ")}</p>` : "";
    const ke = (S.doc.kap || []).filter(r => r.group === g.key).slice(0, 15);
    const kapT = ke.length ? `<h3 class="en-h3" style="margin-top:var(--s-3)">KAP bildirimleri</h3><table class="tx"><thead><tr><th>Tarih</th><th>Olay</th><th>Santral</th><th class="num">MW</th><th>Not</th></tr></thead><tbody>${ke.map(kapRow).join("")}</tbody></table>` : "";
    return `<div class="en-drawer1">${ents}${kapT}<h3 class="en-h3" style="margin-top:var(--s-3)">Santraller (GEM)</h3><table class="tx"><thead><tr><th>Santral / ünite</th><th>Kaynak</th><th class="num">MW</th><th class="num">Pay</th><th class="num">Başlangıç</th><th>İl</th></tr></thead><tbody>
      ${us.slice(0, 80).map(([i, s]) => unitRow(i, s)).join("")}</tbody></table>${us.length > 80 ? `<p class="meta">+${us.length - 80} ünite daha (CSV'de tamamı)</p>` : ""}</div>`;
  }
  const kapMw = r => r.mw ? mw(r.mw) + (r.mwp ? ` <span class="meta">(${mw(r.mwp)} MWp)</span>` : "") : r.mwp ? mw(r.mwp) + ` <span class="meta">MWp</span>` : "—";
  function kapRow(r) {
    const d = S.doc;
    return `<tr><td class="en-date">${r.date ? fmt.date(r.date + "T12:00:00Z", { day: "numeric", month: "short", year: "2-digit" }) : "—"}</td>
      <td><span class="tag ${["devreye_alma", "kapasite_artisi"].includes(r.type) ? "up" : ""}">${esc(d.kap_types[r.type] || r.type)}</span>${r.after_gem && ["devreye_alma", "kapasite_artisi"].includes(r.type) ? ` <span class="meta" data-tip="GEM verisinin tarihinden sonra">yeni</span>` : ""}</td>
      <td><i class="en-dot" style="background:${color(r.src)}"></i>${esc(r.plant || "")}${r.prov ? ` <span class="meta">${esc(r.prov)}</span>` : ""}${r.tr ? "" : ` <span class="tag">yurt dışı</span>`}</td>
      <td class="num">${kapMw(r)}${r.storage ? ` <span class="meta">+${mw(r.storage)} depolama</span>` : ""}</td>
      <td class="en-note-c"><a href="${esc(r.url)}" target="_blank" rel="noopener" data-tip="${esc(r.note || "")}">${esc((r.note || "KAP").slice(0, 90))}${(r.note || "").length > 90 ? "…" : ""} ↗</a>${r.rule ? ` <span class="meta" data-tip="AI kullanılamadı; kurallarla çıkarıldı, kontrol et">⚑</span>` : ""}</td></tr>`;
  }
  function kapCard() {
    const d = S.doc;
    let rows = (d.kap || []).filter(r => (!S.src || r.src === S.src) && (!S.kapType || r.type === S.kapType));
    if (!(d.kap || []).length) return "";
    const counts = {}; (d.kap || []).forEach(r => { counts[r.type] = (counts[r.type] || 0) + 1; });
    const gname = new Map(d.groups.map(g => [g.key, g]));
    const shown = rows.slice(0, S.kapLimit);
    const chips = [["", "Tümü", d.kap.length], ...Object.keys(d.kap_types).filter(k => counts[k]).map(k => [k, d.kap_types[k], counts[k]])]
      .map(([k, l, n]) => `<button type="button" role="radio" data-t="${k}" aria-checked="${S.kapType === k}">${esc(l)} <span class="n">${n}</span></button>`).join("");
    return `<section class="card card-flush" aria-labelledby="enKapT">
      <div class="card-head"><h2 class="card-title" id="enKapT">KAP'ta enerji yatırım bildirimleri</h2><span class="card-meta">borsa şirketleri · lisans, ÇED, YEKA, devreye alma${d.kap_updated ? " · " + fmt.dt(d.kap_updated) : ""}</span></div>
      <div style="padding:0 var(--s-4) var(--s-3)"><div class="seg en-seg" role="radiogroup" aria-label="Olay türü" id="enKapSeg">${chips}</div></div>
      <div class="tbl-scroll"><table class="tbl en-add"><thead><tr><th scope="col">Tarih</th><th scope="col">Şirket</th><th scope="col">Olay</th><th scope="col">Santral</th><th scope="col" class="num">MW</th><th scope="col">Bildirim</th></tr></thead><tbody>
      ${shown.map(r => { const g = gname.get(r.group); const tk = (r.tickers || [])[0];
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
        <td>${n.src ? `<i class="en-dot" style="background:${color(n.src)}"></i>${esc(d.source_names[n.src] || n.src)}` : `<span class="meta">üretim yok</span>`}</td>
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
      ${shown.map(r => `<tr><td class="en-nm"><span>${esc(r.n)}</span></td><td class="en-own">${ownerLabel(r.i)}</td><td><i class="en-dot" style="background:${color(r.s)}"></i>${esc(d.source_names[r.s])}</td>
        <td class="num"><b>${mw(r.mw)}</b></td><td>${r.st ? esc(d.status_names[r.st] || r.st) + (r.y ? ` · ${r.y}` : "") : r.y || "—"}</td><td>${esc(r.p || "")}</td></tr>`).join("")}
      </tbody></table>
      ${rows.length > shown.length ? `<div class="tbl-foot"><span>${shown.length} / ${rows.length}</span><button type="button" class="link-btn" id="${moreId}">Daha fazla</button></div>` : ""}</div></section>`;
  }

  // ─────────────────────────────── ana çizim
  function render() {
    if (sh.route !== "enerji") return;
    const body = $("#enBody");
    if (!S.loaded) return S.error ? renderError() : renderLoading();
    const d = S.doc;
    $("#enSrcSel").innerHTML = `<option value="">Tüm kaynaklar</option>` + d.sources.filter(s => d.national.src[s] || d.national.pipe[s]).map(s => `<option value="${s}" ${S.src === s ? "selected" : ""}>${d.source_names[s]}</option>`).join("");
    const newer = (d.gem.newer || []);
    $("#enSrcLine").innerHTML = (newer.length ? `<span class="tag warn" data-tip="${esc(newer.map(n => `${n.tracker}: ${n.release}`).join(", "))}">GEM'de yeni sürüm var</span> ` : "") + `Kaynak: <a href="https://globalenergymonitor.org" target="_blank" rel="noopener">Global Energy Monitor</a> santral ve sahiplik izleyicileri (CC BY 4.0, aktarım ${esc(d.gem.imported || "")})${d.epias ? ` · <a href="https://seffaflik.epias.com.tr" target="_blank" rel="noopener">EPİAŞ Şeffaflık</a> (YEKDEM)` : ""}${(d.kap || []).length ? ` · KAP bildirimleri` : ""} · ${fmt.int(d.units.length)} ünite · ${fmt.int(d.groups.length)} sahip/grup`;
    const rows = filtered();
    const bySrc = r => !S.src || r.s === S.src;
    const sc = $(".en-scroll")?.scrollTop || 0;
    body.innerHTML = `<div class="view" style="gap:var(--s-4)">${kpis()}${national()}${table(rows)}
      ${kapCard()}${newPlants()}
      ${unitList("enRecT", `Son yıllarda devreye girenler (${d.year - 2}–${d.year})`, d.recent.filter(bySrc), S.recLimit, "enRecMore", "başlangıç yılına göre")}
      ${unitList("enPipeT", "Yapım ve planlama aşamasındakiler", d.pipeline.filter(bySrc), S.pipeLimit, "enPipeMore", "büyükten küçüğe")}
      <p class="en-note">Santraller ve sahiplik <b>Global Energy Monitor</b> izleyicilerinden gelir (yılda yaklaşık iki kez güncellenir). Grup kapasitesi <b>pay oranına göredir</b>: ortak girişimlerde her ortağa payı kadar MW yazılır; “Konsolide” %50 ve üzeri payla kontrol edilen ünitelerin tam gücüdür. Kömür, doğalgaz ve biyoenerjide tam sahiplik zinciri kullanılır ve santrale en yakın eşleşen şirket esas alınır (ör. Aksa Enerji, Kazancı Holding değil). Kapsam dışı: jeotermal, 1 MW altı güneş ve izleyici eşiğinin altındaki küçük HES'ler; sahibi bilinmeyen üniteler (çoğu lisanssız güneş) Türkiye toplamında var, grup tablosunda yok. “Eşleşmedi” işaretli satırlar grup listesine henüz bağlanmadı. <b>KAP sütunu</b>, GEM verisinin tarihinden (${esc(Object.entries(d.gem.asof || {}).map(([k, v]) => `${d.source_names[k] || k} ${v.slice(0, 7)}`).join(", "))}) sonra borsa şirketlerinin KAP'ta bildirdiği devreye alma ve kapasite artışlarıdır; bildirimler AI ile okunur, kesin değer için bildirime bak.</p></div>`;
    if ($(".en-scroll")) $(".en-scroll").scrollTop = sc;
    $("#enMore")?.addEventListener("click", () => { S.limit += PAGE; render(); });
    $("#enAll")?.addEventListener("click", () => { S.limit = 1e9; render(); });
    $("#enLess")?.addEventListener("click", () => { S.limit = PAGE; render(); $("#enTblT")?.scrollIntoView({ block: "start" }); });
    $("#enRecMore")?.addEventListener("click", () => { S.recLimit += 30; render(); });
    $("#enPipeMore")?.addEventListener("click", () => { S.pipeLimit += 30; render(); });
    $("#enKapMore")?.addEventListener("click", () => { S.kapLimit += 30; render(); });
    $$("#enKapSeg button").forEach(b => b.onclick = () => { S.kapType = b.dataset.t; S.kapLimit = 15; render(); $(`#enKapSeg button[data-t="${b.dataset.t}"]`)?.focus(); });
    $$("#enBody .th-sort").forEach(b => b.onclick = () => {
      const c = b.dataset.c;
      S.dir = S.sort === c ? -S.dir : (["name", "code"].includes(c) ? 1 : -1); S.sort = c; S.limit = PAGE;
      render(); $(`#enBody .th-sort[data-c="${c}"]`)?.focus();
    });
  }
  function renderLoading() {
    $("#enSrcLine").innerHTML = `<span class="skeleton sk-line w40" style="display:inline-block;width:320px"></span>`;
    $("#enBody").innerHTML = `<div class="view" style="gap:var(--s-4)" aria-busy="true" aria-label="Enerji verisi yükleniyor">
      <div class="kpi-grid">${Array.from({ length: 6 }, () => `<div class="kpi"><div class="skeleton sk-line w60"></div><div class="skeleton sk-line lg w40"></div></div>`).join("")}</div>
      <div class="card"><div class="skeleton sk-line w40"></div><div class="skeleton" style="height:18px;margin-top:12px"></div></div>
      <div class="card card-flush"><table class="tbl"><tbody>${sh.skeletonRows(8, 8)}</tbody></table></div></div>`;
  }
  function renderError() {
    $("#enSrcLine").textContent = "";
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
      yenilenebilir_payi: g.renew ?? "", yatirim_hatti_mw: g.pipe_total, unite: g.n }));
    ex.download(`enerji_gruplar_${ex.stamp()}.csv`, ex.toCSV(rows), "text/csv;charset=utf-8");
  }
  function exportUnits() {
    const ex = window.radarExport, d = S.doc;
    const rows = d.units.map((u, i) => ({ santral: u.n, kaynak: d.source_names[u.s], mw: u.mw, durum: d.status_names[u.st] || u.st, baslangic: u.y || "", il: u.p || "",
      sahipler: d.owners[i].map(([g, s]) => `${g.name}${g.ticker ? ` (${g.ticker})` : ""} ${Math.round(s * 1000) / 10}%`).join("; "), gem_sahip: u.o || "", lisans: u.lic || "", gem: u.u || "" }));
    ex.download(`enerji_santraller_${ex.stamp()}.csv`, ex.toCSV(rows), "text/csv;charset=utf-8");
  }

  // ─────────────────────────────── bağla
  $$("#enKind button").forEach(b => b.onclick = () => {
    S.kind = b.dataset.k; S.limit = PAGE; $$("#enKind button").forEach(x => x.setAttribute("aria-checked", String(x === b))); render();
  });
  sh.radioKeys($("#enKind"));
  $("#enSrcSel").onchange = e => { S.src = e.target.value; S.limit = PAGE; S.recLimit = 12; S.pipeLimit = 12; render(); };
  let t; $("#enQ").oninput = e => { clearTimeout(t); t = setTimeout(() => { S.q = e.target.value.trim(); S.limit = PAGE; render(); }, 150); };
  $("#enBody").addEventListener("click", e => {
    const tr = e.target.closest("tr.row");
    if (tr && !e.target.closest("a, button")) toggle(tr);
  });
  $("#enBody").addEventListener("keydown", e => {
    const tr = e.target.closest("tr.row");
    if (!tr || e.target !== tr) return;
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(tr); }
    else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const rows = $$("#enBody tr.row"), i = rows.indexOf(tr);
      rows[i + (e.key === "ArrowDown" ? 1 : -1)]?.focus();
    }
  });

  sh.register("enerji", {
    onShow() { S.loaded ? render() : load(); },
    async refresh() { await load(true); },
    exports() {
      const has = S.loaded;
      return [{ label: "Gruplar (CSV)", hint: "filtreye göre", run: exportGroups, disabled: !has },
        { label: "Santraller (CSV)", hint: "tüm üniteler, sahipler ve paylar", run: exportUnits, disabled: !has }];
    },
    exportInfo: () => S.loaded ? `${KINDS[S.kind]}${S.src ? " · " + S.doc.source_names[S.src] : ""}${S.q ? ` · arama “${S.q}”` : ""}` : "",
    exportNote: "Enerji verisi henüz yüklenmedi",
  });
})();
