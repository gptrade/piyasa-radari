/* Piyasa Radarı — Enerji: Türkiye elektrik üretim şirketlerinin kurulu güç envanteri.
   Veri: data/enerji/kurulu_guc.json (enerji.yml, haftalık; EPİAŞ Şeffaflık Platformu).
   Kurulu güç = lisanslı santrallerin Emre Amade Kapasitesi (EAK), son 7 günün kaynak bazında en yüksek değeri. */
(() => {
  "use strict";
  const sh = window.shell;
  const { $, $$, esc, fmt } = sh;
  const SRC = "data/enerji/kurulu_guc.json";
  const PAGE = 25;
  const KINDS = { all: "Tümü", listed: "Borsada", private: "Borsa dışı", kamu: "Kamu" };

  const S = { doc: null, loaded: false, loading: false, error: null, missing: false,
    q: "", kind: "all", src: "", sort: "total", dir: -1, open: new Set(), limit: PAGE, addLimit: 15 };

  // ─────────────────────────────── birimler
  const mw = v => v == null ? "—" : fmt.num(v, v >= 100 ? 0 : 1);
  const gw = v => v == null ? "—" : fmt.num(v / 1000, 1) + " GW";
  const pct = (v, d = 1) => v == null ? "—" : "%" + fmt.num(v * 100, d);
  const color = s => `var(--en-${s})`;

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
      sh.setUpdated("enerji", new Date(S.doc.generated), { label: "EPİAŞ verisi", staleMin: 60 * 24 * 9 });
    } catch (e) {
      S.error = e.message || "veri okunamadı";
    } finally { S.loading = false; }
    S.loaded ? render() : renderError();
  }

  function prepare(d) {
    d.orgById = new Map(d.orgs.map(o => [o.id, o]));
    const top10 = d.groups.slice(0, 10).reduce((s, g) => s + g.total, 0);
    d.top10 = d.national.total ? top10 / d.national.total : null;
    const yearAgo = new Date(Date.now() - 365 * 864e5).toISOString().slice(0, 10);
    d.adds12 = d.additions.filter(a => a.date >= yearAgo);
    d.groups.forEach(g => { g.code = g.ticker || g.parent || ""; g.n = g.orgs.length; });
    return d;
  }
  const kindOf = g => g.kind === "kamu" ? "kamu" : g.ticker || g.parent ? "listed" : "private";

  // ─────────────────────────────── süzme
  function filtered() {
    const d = S.doc, q = S.q.toLocaleLowerCase("tr");
    let rows = d.groups.filter(g => S.kind === "all" || kindOf(g) === S.kind);
    if (S.src) rows = rows.filter(g => g.src[S.src] > 0);
    if (q) rows = rows.filter(g => g.name.toLocaleLowerCase("tr").includes(q) || g.code.toLocaleLowerCase("tr").includes(q) ||
      g.orgs.some(id => (d.orgById.get(id)?.name || "").toLocaleLowerCase("tr").includes(q)));
    const k = S.sort === "total" && S.src ? "srcMw" : S.sort;
    rows.forEach(g => { g.srcMw = S.src ? g.src[S.src] || 0 : g.total; });
    return rows.sort((a, b) => {
      const va = a[k], vb = b[k];
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      return (typeof va === "string" ? va.localeCompare(vb, "tr") : va - vb) * S.dir;
    });
  }

  // ─────────────────────────────── çizim parçaları
  function mixBar(src, total, { h = 10, tip = true } = {}) {
    const d = S.doc;
    if (!total) return "";
    const parts = d.sources.filter(s => src[s] > 0).map(s => {
      const w = src[s] / total * 100;
      return `<span style="width:${w.toFixed(2)}%;background:${color(s)}" ${tip ? `data-tip="${esc(`${d.source_names[s]}: ${mw(src[s])} MW (${pct(src[s] / total)})`)}"` : ""}></span>`;
    }).join("");
    return `<span class="en-mix" style="height:${h}px" role="img" aria-label="${esc(d.sources.filter(s => src[s] > 0).map(s => `${d.source_names[s]} ${pct(src[s] / total, 0)}`).join(", "))}">${parts}</span>`;
  }
  function legend(src, total) {
    const d = S.doc;
    return `<div class="en-legend">${d.sources.filter(s => src[s] > 0).map(s =>
      `<span><i style="background:${color(s)}"></i>${d.source_names[s]} <b>${gw(src[s])}</b> <em>${pct(src[s] / total)}</em></span>`).join("")}</div>`;
  }
  function kpis() {
    const d = S.doc, n = d.national;
    const ren = ["hidro", "ruzgar", "gunes", "jeotermal"].reduce((s, k) => s + (n.src[k] || 0), 0);
    const addMw = d.adds12.reduce((s, a) => s + a.mw, 0);
    const big = d.groups.find(g => g.kind !== "kamu");
    const k = (label, value, sub = "", tip = "") => `<div class="kpi" ${tip ? `data-tip="${esc(tip)}"` : ""}><span class="kpi-label">${label}</span><span class="kpi-value">${value}</span>${sub ? `<span class="kpi-sub">${sub}</span>` : ""}</div>`;
    return `<div class="kpi-grid">
      ${k("Lisanslı kurulu güç", gw(n.total), "EAK, lisanslı", "Lisanslı santrallerin son 7 günde kaynak bazında en yüksek emre amade kapasitesi. Lisanssız (çoğu ≤5 MW) güneş santralleri dahil değil.")}
      ${k("Yenilenebilir payı", pct(n.total ? ren / n.total : null), "hidro·rüzgâr·güneş·JES")}
      ${k("Borsa şirketlerinin payı", pct(d.listed_share), "ortaklar dahil", "Santral şirketi borsada olan ya da borsadaki bir ortağa bağlı grupların toplam kapasitesi (konsolide; ortaklık payı düşülmez)")}
      ${k("İlk 10 grubun payı", pct(d.top10))}
      ${k("Son 12 ayda devreye giren", fmt.num(addMw, 0) + " MW", `${fmt.int(d.adds12.length)} geçici kabul`, "Enerji İşleri Genel Müdürlüğü geçici kabul listesi (lisanslı santraller)")}
      ${k("En büyük özel grup", big ? esc(big.name) : "—", big ? `${gw(big.total)} · ${pct(big.share)}` : "")}
    </div>`;
  }
  function national() {
    const n = S.doc.national;
    return `<section class="card" aria-labelledby="enNatT">
      <div class="card-head"><h2 class="card-title" id="enNatT">Türkiye kaynak dağılımı</h2><span class="card-meta">${gw(n.total)} · ${esc(fmt.date(S.doc.window[0], { day: "numeric", month: "short" }))}–${esc(fmt.date(S.doc.window[1], { day: "numeric", month: "short", year: "numeric" }))}</span></div>
      ${mixBar(n.src, n.total, { h: 18 })}${legend(n.src, n.total)}</section>`;
  }

  function table(rows) {
    const d = S.doc;
    const COLS = [["rank", "#", 1], ["name", "Grup / şirket"], ["code", "Kod"], ["total", S.src ? `${d.source_names[S.src]} (MW)` : "Kurulu güç (MW)", 1], ["share", "Türkiye payı", 1],
      ["mix", "Kaynak dağılımı"], ["renew", "Yenilenebilir", 1], ["adds12", "12 ayda eklenen (MW)", 1], ["n", "Şirket", 1]];
    const TIPS = { share: "Grubun kapasitesi ÷ Türkiye lisanslı EAK toplamı", adds12: "Son 12 ayda geçici kabulü yapılan ilave kurulu güç", n: "EPİAŞ'taki tüzel kişi (santral şirketi) sayısı",
      code: "Borsa kodu; santral şirketi borsada değilse borsadaki ortağın kodu (↳)" };
    const head = COLS.map(([c, l, num]) => c === "mix" || c === "rank" ? `<th scope="col" class="${num ? "num" : ""}">${l}</th>` :
      `<th scope="col" class="${num ? "num" : ""}" aria-sort="${c === S.sort ? (S.dir > 0 ? "ascending" : "descending") : "none"}"><button type="button" class="th-sort" data-c="${c}" ${TIPS[c] ? `data-tip="${esc(TIPS[c])}"` : ""}>${l}<span class="arr" aria-hidden="true">${c === S.sort ? (S.dir > 0 ? "▲" : "▼") : "▼"}</span></button></th>`).join("");
    const rank = new Map(d.groups.map((g, i) => [g.key, i + 1]));
    const shown = rows.slice(0, S.limit);
    const body = shown.map(g => {
      const open = S.open.has(g.key);
      const code = g.ticker ? `<a href="#hisse/${esc(g.ticker)}" class="en-code" data-tip="Temel analiz">${esc(g.ticker)}</a>` :
        g.parent ? `<a href="#hisse/${esc(g.parent)}" class="en-code parent" data-tip="Borsadaki ortak">↳ ${esc(g.parent)}</a>` : "";
      const tag = g.kind === "kamu" ? ` <span class="tag na">kamu</span>` : g.auto ? ` <span class="tag" data-tip="Unvanın ilk kelimesiyle otomatik gruplandı; grup listesine henüz eklenmedi">otomatik</span>` : "";
      return `<tr class="row ${open ? "open" : ""}" data-k="${esc(g.key)}" tabindex="0" aria-expanded="${open}">
        <td class="num en-rank">${rank.get(g.key)}</td>
        <td class="en-nm"><span>${esc(g.name)}</span>${tag}</td>
        <td>${code}</td>
        <td class="num"><b>${mw(S.src ? g.srcMw : g.total)}</b></td>
        <td class="num">${pct(S.src ? (d.national.src[S.src] ? g.srcMw / d.national.src[S.src] : null) : g.share, 2)}</td>
        <td class="en-mixc">${mixBar(g.src, g.total)}</td>
        <td class="num">${pct(g.renew, 0)}</td>
        <td class="num">${g.adds12 ? fmt.num(g.adds12, 0) : "—"}</td>
        <td class="num">${g.n}</td>
      </tr>${open ? `<tr class="drawer"><td colspan="${COLS.length}">${drawer(g)}</td></tr>` : ""}`;
    }).join("");
    const total = rows.length;
    return `<section class="card card-flush" aria-labelledby="enTblT">
      <div class="card-head"><h2 class="card-title" id="enTblT">Gruplar (${fmt.int(total)})</h2><span class="card-meta">satıra tıkla: şirketler ve yeni santraller · başlığa tıkla: sırala</span></div>
      <div class="tbl-scroll en-scroll"><table class="tbl en-tbl"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>
      ${total > shown.length || S.limit > PAGE ? `<div class="tbl-foot"><span>${fmt.int(shown.length)} / ${fmt.int(total)} grup gösteriliyor</span>
        <span>${total > shown.length ? `<button type="button" class="link-btn" id="enMore">${Math.min(PAGE, total - shown.length)} grup daha</button> · <button type="button" class="link-btn" id="enAll">Tümü</button>` : `<button type="button" class="link-btn" id="enLess">İlk ${PAGE} gruba dön</button>`}</span></div>` : ""}
      ${total ? "" : sh.stateHTML({ kind: "empty", title: "Eşleşen grup yok", msg: "Aramayı ya da filtreleri değiştir." })}</div></section>`;
  }
  function drawer(g) {
    const d = S.doc;
    const orgs = g.orgs.map(id => d.orgById.get(id)).filter(Boolean);
    const list = `<table class="tx"><thead><tr><th>Şirket</th><th class="num">MW</th><th>Kaynaklar</th></tr></thead><tbody>${orgs.slice(0, 40).map(o =>
      `<tr><td>${esc(o.name)}</td><td class="num">${mw(o.total)}</td><td class="en-fields">${Object.entries(o.fields).sort((a, b) => b[1] - a[1]).map(([f, v]) =>
        `<span><i style="background:${color(fieldSrc(f))}"></i>${esc(d.field_names[f] || f)} ${mw(v)}</span>`).join("")}</td></tr>`).join("")}</tbody></table>
      ${orgs.length > 40 ? `<p class="meta">+${orgs.length - 40} şirket daha</p>` : ""}`;
    const adds = d.additions.filter(a => a.group === g.key).slice(0, 12);
    const al = adds.length ? `<table class="tx"><thead><tr><th>Geçici kabul</th><th>Santral</th><th>Kaynak</th><th class="num">MW</th></tr></thead><tbody>${adds.map(a =>
      `<tr><td>${a.date ? fmt.date(a.date + "T12:00:00Z", { day: "numeric", month: "short", year: "numeric" }) : "—"}</td><td>${esc(a.plant)}${a.city ? ` <span class="meta">${esc(a.city)}</span>` : ""}</td><td><i class="en-dot" style="background:${color(a.src)}"></i>${esc(a.fuel)}</td><td class="num">${fmt.num(a.mw, 1)}</td></tr>`).join("")}</tbody></table>` :
      `<p class="meta">Kayıtlı geçici kabul yok.</p>`;
    return `<div class="en-drawer"><div><h3 class="en-h3">Tüzel kişiler (${orgs.length})</h3>${list}</div><div><h3 class="en-h3">Devreye alınan santraller</h3>${al}</div></div>`;
  }
  const FIELD_SRC = { barajli: "hidro", akarsu: "hidro", ruzgar: "ruzgar", gunes: "gunes", jeotermal: "jeotermal", dogalgaz: "dogalgaz", linyit: "komur", ithalKomur: "komur", tasKomur: "komur" };
  const fieldSrc = f => FIELD_SRC[f] || "diger";

  function additions() {
    const d = S.doc;
    let rows = d.adds12;
    if (S.src) rows = rows.filter(a => a.src === S.src);
    if (!rows.length) return "";
    const gname = new Map(d.groups.map(g => [g.key, g]));
    const shown = rows.slice(0, S.addLimit);
    const bySrc = {}; rows.forEach(a => { bySrc[a.src] = (bySrc[a.src] || 0) + a.mw; });
    const sum = Object.values(bySrc).reduce((s, v) => s + v, 0);
    return `<section class="card card-flush" aria-labelledby="enAddT">
      <div class="card-head"><h2 class="card-title" id="enAddT">Son 12 ayda devreye alınanlar</h2><span class="card-meta">${fmt.num(sum, 0)} MW · ${fmt.int(rows.length)} geçici kabul</span></div>
      <div style="padding:0 var(--s-4) var(--s-3)">${mixBar(bySrc, sum, { h: 10 })}</div>
      <div class="tbl-scroll"><table class="tbl en-add"><thead><tr><th scope="col">Tarih</th><th scope="col">Grup / şirket</th><th scope="col">Santral</th><th scope="col">Kaynak</th><th scope="col" class="num">MW</th><th scope="col">İl</th></tr></thead><tbody>
      ${shown.map(a => { const g = gname.get(a.group); return `<tr><td class="en-date">${a.date ? fmt.date(a.date + "T12:00:00Z", { day: "numeric", month: "short", year: "2-digit" }) : "—"}</td>
        <td class="en-nm" data-tip="${esc(a.company)}"><span>${esc(g ? g.name : a.company)}</span>${g?.ticker ? ` <a href="#hisse/${esc(g.ticker)}" class="en-code">${esc(g.ticker)}</a>` : ""}</td>
        <td>${esc(a.plant)}</td><td><i class="en-dot" style="background:${color(a.src)}"></i>${esc(a.fuel)}</td><td class="num"><b>${fmt.num(a.mw, 1)}</b></td><td>${esc(a.city)}</td></tr>`; }).join("")}
      </tbody></table>
      ${rows.length > shown.length ? `<div class="tbl-foot"><span>${shown.length} / ${rows.length}</span><button type="button" class="link-btn" id="enAddMore">Daha fazla</button></div>` : ""}</div></section>`;
  }

  // ─────────────────────────────── ana çizim
  function render() {
    if (sh.route !== "enerji") return;
    const body = $("#enBody");
    if (!S.loaded) return S.error ? renderError() : renderLoading();
    const d = S.doc;
    $("#enSrcSel").innerHTML = `<option value="">Tüm kaynaklar</option>` + d.sources.filter(s => d.national.src[s]).map(s => `<option value="${s}" ${S.src === s ? "selected" : ""}>${d.source_names[s]}</option>`).join("");
    $("#enSrcLine").innerHTML = `Kaynak: <a href="https://seffaflik.epias.com.tr" target="_blank" rel="noopener">EPİAŞ Şeffaflık Platformu</a> (emre amade kapasite, geçici kabul listesi) · ${fmt.int(d.orgs.length)} üretici şirket · güncelleme ${fmt.dt(d.generated)} · haftalık`;
    const rows = filtered();
    const sc = $(".en-scroll")?.scrollTop || 0;
    body.innerHTML = `<div class="view" style="gap:var(--s-4)">${kpis()}${national()}${table(rows)}${additions()}
      <p class="en-note">Kurulu güç, EPİAŞ'ın santral bazında yayımladığı <b>emre amade kapasitenin</b> (EAK) son 7 gündeki en yüksek değeridir; bakım ve arızadaki üniteler düşük görünebilir, kuraklıkta barajlı santrallerin EAK'ı lisans gücünün altına inebilir. Lisanssız (çoğunlukla ≤5 MW, dağıtık) güneş santralleri EPİAŞ şirket verisinde yoktur; bu yüzden Türkiye toplamı TEİAŞ kurulu güç istatistiğinden düşüktür. Grup kapasiteleri konsolidedir (ortaklık payı düşülmez). Şirket → grup eşleştirmesi unvanlara göre yapılır; “otomatik” işaretli gruplar henüz elle doğrulanmadı.</p></div>`;
    if ($(".en-scroll")) $(".en-scroll").scrollTop = sc;
    $("#enMore")?.addEventListener("click", () => { S.limit += PAGE; render(); });
    $("#enAll")?.addEventListener("click", () => { S.limit = 1e9; render(); });
    $("#enLess")?.addEventListener("click", () => { S.limit = PAGE; render(); $("#enTblT")?.scrollIntoView({ block: "start" }); });
    $("#enAddMore")?.addEventListener("click", () => { S.addLimit += 30; render(); });
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
    $("#enBody").innerHTML = S.missing ? sh.stateHTML({ kind: "info", title: "Enerji verisi henüz oluşmadı",
      msg: "Kurulu güç envanteri EPİAŞ Şeffaflık Platformu'ndan haftalık çekiliyor. İlk çalıştırma için EPİAŞ hesabının (EPIAS_USERNAME / EPIAS_PASSWORD) GitHub secret'larına eklenmesi gerekiyor." }) :
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
    const rows = filtered().map(g => ({ grup: g.name, kod: g.ticker || "", borsadaki_ortak: g.parent || "", tur: kindOf(g), otomatik: g.auto ? "evet" : "",
      kurulu_guc_mw: g.total, turkiye_payi: g.share, ...Object.fromEntries(d.sources.map(s => [`${s}_mw`, g.src[s] || 0])), yenilenebilir_payi: g.renew ?? "", eklenen_12ay_mw: g.adds12, sirket_sayisi: g.n }));
    ex.download(`enerji_gruplar_${ex.stamp()}.csv`, ex.toCSV(rows), "text/csv;charset=utf-8");
  }
  function exportOrgs() {
    const ex = window.radarExport, d = S.doc, gname = new Map(d.groups.map(g => [g.key, g]));
    const rows = d.orgs.map(o => ({ sirket: o.name, epias_id: o.id, eic: o.eic || "", grup: gname.get(o.group)?.name || "", kod: gname.get(o.group)?.code || "", kurulu_guc_mw: o.total,
      ...Object.fromEntries(Object.keys(d.field_names).map(f => [f, o.fields[f] || 0])) }));
    ex.download(`enerji_sirketler_${ex.stamp()}.csv`, ex.toCSV(rows), "text/csv;charset=utf-8");
  }
  function exportAdds() {
    const ex = window.radarExport;
    const rows = S.doc.additions.map(a => ({ gecici_kabul: a.date, sirket: a.company, santral: a.plant, yakit: a.fuel, kaynak: a.src, ilave_mw: a.mw, il: a.city }));
    ex.download(`enerji_devreye_alinanlar_${ex.stamp()}.csv`, ex.toCSV(rows), "text/csv;charset=utf-8");
  }

  // ─────────────────────────────── bağla
  $$("#enKind button").forEach(b => b.onclick = () => {
    S.kind = b.dataset.k; S.limit = PAGE; $$("#enKind button").forEach(x => x.setAttribute("aria-checked", String(x === b))); render();
  });
  sh.radioKeys($("#enKind"));
  $("#enSrcSel").onchange = e => { S.src = e.target.value; S.limit = PAGE; S.addLimit = 15; render(); };
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
        { label: "Şirketler (CSV)", hint: "tüzel kişi bazında, alt kaynaklarla", run: exportOrgs, disabled: !has },
        { label: "Devreye alınanlar (CSV)", hint: "geçici kabul listesi", run: exportAdds, disabled: !has }];
    },
    exportInfo: () => S.loaded ? `${KINDS[S.kind]}${S.src ? " · " + S.doc.source_names[S.src] : ""}${S.q ? ` · arama “${S.q}”` : ""}` : "",
    exportNote: "Enerji verisi henüz yüklenmedi",
  });
})();
