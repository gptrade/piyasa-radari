/* Piyasa Radarı — Temel Analiz (BIST-100, KAP mali tabloları).
   Rotalar: #temel (genel bakış) · #hisse/KOD (şirket) · #tarama · #karsilastir/KOD,KOD
   Veri: data/fin/_screen.json (evren özeti), data/fin/KOD.json (seriler + metrikler), data/fin/_universe.json
   Tutarlar TL; "Reel" görünümde her dönem TÜFE(son dönem)/TÜFE(dönem sonu) ile bugünün TL'sine taşınır. */
(() => {
  "use strict";
  const sh = window.shell;
  const { $, $$, esc, fmt, store } = sh;
  const MINUS = "−";
  const S = {
    screen: null, err: null, loaded: false, docs: {}, real: store.get("radar.finReal", true),
    sort: store.get("radar.finSort", ["overall", -1]), sector: "", q: "",
    tab: "ozet", nq: 5, chartMode: "q", trend: "roe",
    scrTab: "kriter", crit: "Benjamin Graham — Savunmacı Yatırımcı", allPass: true, scrSector: "",
    filters: store.get("radar.finFilters", [["pe", "<=", 15], ["roe", ">=", 0.1]]),
    cmp: store.get("radar.finCmp", []), cmpMetric: "rev_growth",
  };

  // ───────────── biçimler
  const pct = (v, d = 1) => v == null ? "—" : fmt.pct(v * 100, d, false);
  const pctS = (v, d = 1) => v == null ? "—" : fmt.pct(v * 100, d, true);
  const x = (v, d = 2) => v == null ? "—" : fmt.num(v, d) + "x";
  const tl = v => {
    if (v == null || !isFinite(v)) return "—";
    const a = Math.abs(v);
    if (a >= 1e9) return fmt.num(v / 1e9, 2) + " mr ₺";
    if (a >= 1e6) return fmt.num(v / 1e6, 1) + " mn ₺";
    return fmt.num(v, 0) + " ₺";
  };
  const bin = v => v == null ? "—" : fmt.num(v / 1000, 0);
  const days = v => v == null ? "—" : fmt.num(v, 0) + " gün";
  const GRADE_CLS = { A: "g-a", B: "g-b", C: "g-c", D: "g-d", E: "g-e" };
  const gradeTag = (g, label) => g ? `<span class="grade ${GRADE_CLS[g]}" ${label ? `data-tip="${esc(label)}"` : ""}>${g}</span>` : `<span class="grade">—</span>`;
  const plabel = pk => pk ? pk.replace("/", "/") : "—";
  const qlabel = pk => { const [y, m] = pk.split("/"); return `${+m / 3}Ç${y.slice(2)}`; };
  const trTitle = t => (t || "").replace(/\bA\.Ş\.?$/i, "A.Ş.");

  // Metrik sözlüğü: ad, biçim, yön (+1 büyük iyi, −1 küçük iyi), grup
  const MET = {
    gross_margin: ["Brüt kar marjı", pct, 1, "Karlılık"], ebitda_margin: ["FAVÖK marjı", pct, 1, "Karlılık"],
    op_margin: ["Esas faaliyet kar marjı", pct, 1, "Karlılık"], core_margin: ["Çekirdek faaliyet marjı", pct, 1, "Karlılık"],
    net_margin: ["Net kar marjı", pct, 1, "Karlılık"], roe: ["Özkaynak karlılığı (ROE)", pct, 1, "Karlılık"],
    roa: ["Aktif karlılığı (ROA)", pct, 1, "Karlılık"], roic: ["Yatırılan sermaye getirisi (ROIC)", pct, 1, "Karlılık"],
    rev_growth: ["Reel satış büyümesi", pctS, 1, "Reel büyüme"], ebitda_growth: ["Reel FAVÖK büyümesi", pctS, 1, "Reel büyüme"],
    net_growth: ["Reel net kar büyümesi", pctS, 1, "Reel büyüme"], asset_growth: ["Reel aktif büyümesi", pctS, 1, "Reel büyüme"],
    net_debt_ebitda: ["Net borç / FAVÖK", x, -1, "Borçluluk"], debt_equity: ["Borç / özkaynak", x, -1, "Borçluluk"],
    fin_debt_equity: ["Finansal borç / özkaynak", x, -1, "Borçluluk"], liab_assets: ["Yükümlülük / varlık", pct, -1, "Borçluluk"],
    interest_cov: ["FAVÖK / finansman gideri", x, 1, "Borçluluk"],
    current: ["Cari oran", x, 1, "Likidite"], quick: ["Asit-test oranı", x, 1, "Likidite"], cash_ratio: ["Nakit oranı", x, 1, "Likidite"],
    cfo_ni: ["İşletme nakdi / net kar", x, 1, "Nakit akışı"], fcf_margin: ["Serbest nakit akışı marjı", pct, 1, "Nakit akışı"],
    accruals: ["Tahakkuk oranı", pct, -1, "Nakit akışı"],
    asset_turnover: ["Aktif devir hızı", x, 1, "Verimlilik"], inv_days: ["Stok süresi", days, -1, "Verimlilik"],
    rec_days: ["Alacak tahsil süresi", days, -1, "Verimlilik"], pay_days: ["Borç ödeme süresi", days, 1, "Verimlilik"],
    ccc: ["Nakit dönüşüm süresi", days, -1, "Verimlilik"],
    pe: ["F/K", x, -1, "Değerleme"], pb: ["PD/DD", x, -1, "Değerleme"], ev_ebitda: ["FD/FAVÖK", x, -1, "Değerleme"],
    ev_sales: ["FD/Satış", x, -1, "Değerleme"], ps: ["F/Satış", x, -1, "Değerleme"], peg: ["PEG", x, -1, "Değerleme"],
    earnings_yield: ["Kazanç getirisi", pct, 1, "Değerleme"], fcf_yield: ["Serbest nakit getirisi", pct, 1, "Değerleme"],
    div_yield: ["Temettü verimi (12A)", pct, 1, "Değerleme"],
    // banka
    real_roe: ["Reel ROE (TÜFE'den arındırılmış)", pctS, 1, "Karlılık"], inflation: ["Yıllık TÜFE (dönem sonu)", pct, -1, "Karlılık"],
    nim: ["Net faiz marjı (aktife göre)", pct, 1, "Faiz marjı & gelir"], fee_share: ["Ücret-komisyonun gelirdeki payı", pct, 1, "Faiz marjı & gelir"],
    cost_income: ["Maliyet / gelir", pct, -1, "Verimlilik"], fee_cover: ["Ücret-komisyon / faaliyet giderleri", x, 1, "Verimlilik"],
    cost_of_risk: ["Risk maliyeti (beklenen zarar / krediler)", pct, -1, "Aktif kalitesi"],
    ldr: ["Kredi / mevduat", pct, -1, "Sermaye & fonlama"], equity_assets: ["Özkaynak / aktif", pct, 1, "Sermaye & fonlama"],
    loan_growth: ["Reel kredi büyümesi", pctS, 1, "Reel büyüme"], deposit_growth: ["Reel mevduat büyümesi", pctS, 1, "Reel büyüme"],
    tax_rate: ["Efektif vergi oranı", pct, -1, "Karlılık"],
    // sigorta
    loss_ratio: ["Hasar oranı (net)", pct, -1, "Teknik karlılık"], expense_ratio: ["Gider oranı", pct, -1, "Teknik karlılık"],
    combined: ["Birleşik oran", pct, -1, "Teknik karlılık"], tech_margin: ["Teknik denge / kazanılmış prim", pct, 1, "Teknik karlılık"],
    retention: ["Saklama oranı (net / brüt prim)", pct, 1, "Verimlilik"], reserves_cover: ["Nakit+finansal varlık / teknik karşılık", x, 1, "Likidite"],
    premium_growth: ["Reel brüt prim büyümesi", pctS, 1, "Reel büyüme"],
  };
  const MET_T = {
    sanayi: ["gross_margin", "ebitda_margin", "op_margin", "core_margin", "net_margin", "roe", "roa", "roic", "rev_growth", "ebitda_growth", "net_growth", "asset_growth",
      "net_debt_ebitda", "debt_equity", "fin_debt_equity", "liab_assets", "interest_cov", "current", "quick", "cash_ratio", "cfo_ni", "fcf_margin", "accruals",
      "asset_turnover", "inv_days", "rec_days", "pay_days", "ccc", "pe", "pb", "ev_ebitda", "ev_sales", "ps", "peg", "earnings_yield", "fcf_yield", "div_yield"],
    banka: ["roe", "real_roe", "roa", "inflation", "tax_rate", "nim", "fee_share", "cost_income", "fee_cover", "cost_of_risk", "ldr", "equity_assets",
      "loan_growth", "deposit_growth", "net_growth", "rev_growth", "pe", "pb", "peg", "earnings_yield", "div_yield"],
    sigorta: ["roe", "real_roe", "roa", "inflation", "loss_ratio", "expense_ratio", "combined", "tech_margin", "retention", "equity_assets", "reserves_cover",
      "premium_growth", "net_growth", "pe", "pb", "peg", "earnings_yield", "div_yield"],
  };
  const TPL = { sanayi: "Sanayi/hizmet", banka: "Banka", sigorta: "Sigorta" };
  const tplOf = x => x?.metrics?.template || x?.template || x?.t || "sanayi";
  const VALK = new Set(["pe", "pb", "ev_ebitda", "ev_sales", "ps", "peg", "earnings_yield", "fcf_yield", "div_yield"]);
  const mval = (row, k) => VALK.has(k) ? row.v?.[k] : row.r?.[k];
  const mOf = (m, k) => VALK.has(k) ? m.valuation?.[k] : m.ratios?.[k];

  // ───────────── veri
  async function getJSON(u) {
    const r = await fetch(`${u}?t=${Math.floor(Date.now() / 300000)}`);
    if (!r.ok) throw new Error(`${u} okunamadı (HTTP ${r.status})`);
    return r.json();
  }
  async function load() {
    try { S.screen = await getJSON("data/fin/_screen.json"); S.err = null; }
    catch (e) { S.err = e; }
    S.loaded = true;
    dispatchEvent(new Event("fundamentalsloaded"));
    if (S.screen) ["temel", "hisse", "tarama", "karsilastir"].forEach(r => sh.setUpdated(r, S.screen.updated, { label: "Temel analiz güncellendi", staleMin: 26 * 60 }));
    rerender();
  }
  async function doc(code) {
    if (S.docs[code]) return S.docs[code];
    S.docs[code] = getJSON(`data/fin/${code}.json`).catch(e => { delete S.docs[code]; throw e; });
    return S.docs[code];
  }
  const rows = () => S.screen?.rows || [];
  const rowOf = c => rows().find(r => r.code === c);
  function rerender() {
    const r = sh.route;
    if (r === "temel") renderOverview();
    else if (r === "hisse") renderCompany();
    else if (r === "tarama") renderScreen();
    else if (r === "karsilastir") renderCompare();
  }
  const loading = el => { el.innerHTML = `<div class="card"><div class="skeleton sk-block" style="height:160px"></div></div>`; };
  function notReady(el) {
    if (!S.loaded) { loading(el); return true; }
    if (S.err || !rows().length) {
      el.innerHTML = `<div class="card">${sh.stateHTML({ kind: S.err ? "info" : "empty",
        title: "Temel analiz verisi hazırlanıyor",
        msg: "BIST-100 şirketlerinin KAP mali tabloları kademeli olarak yükleniyor (KAP'ın istek sınırı nedeniyle tamamlanması yaklaşık bir gün sürer). Sayfa veri geldikçe dolar." })}</div>`;
      return true;
    }
    return false;
  }
  const realToggle = () => `<div class="seg" role="radiogroup" aria-label="Tutarlar"><button type="button" role="radio" data-real="1" aria-checked="${S.real}">Reel</button><button type="button" role="radio" data-real="0" aria-checked="${!S.real}">Nominal</button></div>`;
  function bindReal(el, cb) {
    $$("[data-real]", el).forEach(b => b.onclick = () => { S.real = b.dataset.real === "1"; store.set("radar.finReal", S.real); cb(); });
  }

  // ───────────── genel bakış
  const COLS = [
    ["code", "Şirket", null], ["sector", "Sektör", null], ["price", "Fiyat", v => fmt.num(v, 2)], ["mcap", "Piyasa değeri", tl],
    ["pe", "F/K", x], ["pb", "PD/DD", x], ["ev_ebitda", "FD/FAVÖK", x], ["roe", "ROE", pct], ["rev_growth", "Reel satış", pctS],
    ["quality", "Kalite", null], ["valuation_score", "Değerleme", null], ["overall", "Genel", null],
  ];
  const colVal = (row, k) => k === "code" ? row.code : k === "sector" ? row.sector || "" : k === "price" ? row.price : k === "mcap" ? row.mcap
    : ["quality", "valuation_score", "overall"].includes(k) ? row[k] : mval(row, k);
  function sorted(xs) {
    const [k, dir] = S.sort;
    return [...xs].sort((a, b) => {
      const va = colVal(a, k), vb = colVal(b, k);
      if (va == null && vb == null) return 0; if (va == null) return 1; if (vb == null) return -1;
      return (typeof va === "string" ? va.localeCompare(vb, "tr") : va - vb) * dir;
    });
  }
  function renderOverview() {
    const el = $("#view-temel");
    if (notReady(el)) return;
    const all = rows();
    const sectors = [...new Set(all.map(r => r.sector || "Diğer"))].sort((a, b) => a.localeCompare(b, "tr"));
    let xs = all.filter(r => !S.sector || (r.sector || "Diğer") === S.sector);
    if (S.q) { const q = S.q.toLocaleLowerCase("tr"); xs = xs.filter(r => `${r.code} ${r.title}`.toLocaleLowerCase("tr").includes(q)); }
    const dist = { A: 0, B: 0, C: 0, D: 0, E: 0 }; all.forEach(r => r.grade && dist[r.grade]++);
    const oos = S.screen.out_of_scope || [], pend = S.screen.pending || [];
    const scoreCell = (v, g) => `<td class="num"><span class="sc">${v ?? "—"}</span>${g !== undefined ? " " + gradeTag(g) : ""}</td>`;
    el.innerHTML = `
      <div class="kpi-grid fa-kpis">
        <div class="kpi"><span class="kpi-label">Analiz edilen</span><span class="kpi-value">${all.length}</span><span class="kpi-sub">${pend.length ? `${pend.length} şirket yükleniyor · ` : ""}${oos.length} kapsam dışı</span></div>
        <div class="kpi"><span class="kpi-label">Not dağılımı</span><span class="kpi-value fa-dist">${Object.entries(dist).map(([g, n]) => `${gradeTag(g)}<small>${n}</small>`).join(" ")}</span><span class="kpi-sub">A ≥ 80 · B ≥ 65 · C ≥ 50 · D ≥ 35</span></div>
        <div class="kpi"><span class="kpi-label">Sektör</span><span class="kpi-value">${sectors.length}</span><span class="kpi-sub">KAP sektör sınıflaması</span></div>
        <div class="kpi"><span class="kpi-label">Son veri</span><span class="kpi-value fa-small">${fmt.date(S.screen.updated, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</span><span class="kpi-sub">Fiyatlar saatlik, tablolar KAP'ta yayımlandıkça</span></div>
      </div>
      <section class="card card-flush">
        <div class="card-head"><h2 class="card-title">Şirketler</h2><span class="card-meta">Genel skor = kalite %60 + değerleme %40 · satıra tıkla</span></div>
        <div class="toolbar fa-tools">
          <label class="search"><svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="9" cy="9" r="5.5" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="m13.5 13.5 3 3" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>
            <input type="search" id="faQ" placeholder="Kod ya da şirket adı" value="${esc(S.q)}" aria-label="Şirket ara"></label>
          <select id="faSector" class="fa-select" aria-label="Sektör"><option value="">Tüm sektörler (${all.length})</option>${sectors.map(s => `<option ${s === S.sector ? "selected" : ""}>${esc(s)}</option>`).join("")}</select>
        </div>
        <div class="tbl-scroll"><table class="tbl fa-tbl">
          <thead><tr>${COLS.map(([k, l]) => `<th scope="col" class="${k === "code" || k === "sector" ? "" : "num"}"><button type="button" class="th-sort" data-k="${k}" aria-sort="${S.sort[0] === k ? (S.sort[1] > 0 ? "ascending" : "descending") : "none"}">${l}${S.sort[0] === k ? (S.sort[1] > 0 ? " ▲" : " ▼") : ""}</button></th>`).join("")}</tr></thead>
          <tbody>${sorted(xs).map(r => `<tr class="row" tabindex="0" data-code="${r.code}">
            <td><b class="mono">${r.code}</b>${r.t && r.t !== "sanayi" ? ` <span class="tag na">${TPL[r.t]}</span>` : ""} <span class="muted fa-name">${esc(trTitle(r.title))}</span></td>
            <td class="muted"><span class="fa-sec-name" title="${esc(r.sector || "")}">${esc(r.sector || "—")}</span></td>
            <td class="num">${fmt.num(r.price, 2)}</td><td class="num">${tl(r.mcap)}</td>
            <td class="num">${x(r.v?.pe)}</td><td class="num">${x(r.v?.pb)}</td><td class="num">${x(r.v?.ev_ebitda)}</td>
            <td class="num">${pct(r.r?.roe)}</td><td class="num ${(r.r?.rev_growth ?? 0) >= 0 ? "" : "down"}">${pctS(r.r?.rev_growth)}</td>
            ${scoreCell(r.quality)}${scoreCell(r.valuation_score)}${scoreCell(r.overall, r.grade)}</tr>`).join("") || `<tr><td colspan="12">${sh.stateHTML({ title: "Eşleşen şirket yok", compact: true })}</td></tr>`}</tbody>
        </table></div>
        ${pend.length ? `<p class="card-foot fa-oos">Tabloları yükleniyor (KAP istek sınırı nedeniyle kademeli): ${pend.map(o => `<span class="mono">${esc(o.code)}</span>`).join(" ")}</p>` : ""}
        ${oos.length ? `<p class="card-foot fa-oos">Kapsam dışı: ${oos.map(o => `<span class="mono">${esc(o.code)}</span>`).join(" ")}. Faktoring, finansal kiralama gibi tablo yapısı farklı şirketler şimdilik kapsam dışı.</p>` : ""}
      </section>
      ${divCard(all)}
      ${sectorTable(all)}
      <p class="fa-disc">Bu panel yatırım tavsiyesi vermez. Mali tablolar KAP bildirimlerinden, fiyatlar Yahoo Finance'ten; reel düzeltmede TÜİK TÜFE (TCMB EVDS) kullanılır.</p>`;
    $("#faQ").oninput = e => { S.q = e.target.value; const pos = e.target.selectionStart; renderOverview(); const i = $("#faQ"); i.focus(); i.setSelectionRange(pos, pos); };
    $("#faSector").onchange = e => { S.sector = e.target.value; renderOverview(); };
    $$(".tk-cmp", el).forEach(b => b.onclick = () => sh.go("hisse", { param: b.dataset.code }));
    $$(".th-sort", el).forEach(b => b.onclick = () => {
      const k = b.dataset.k; S.sort = [k, S.sort[0] === k ? -S.sort[1] : (k === "code" || k === "sector" ? 1 : -1)];
      store.set("radar.finSort", S.sort); renderOverview();
    });
    bindRows(el);
  }
  const med = xs => { const v = xs.filter(x => x != null && isFinite(x)).sort((a, b) => a - b); if (!v.length) return null; const m = v.length >> 1; return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2; };
  function divCard(all) {
    const today = new Date().toISOString().slice(0, 10);
    const up = all.flatMap(r => (r.div?.ex || []).filter(d => d >= today).map(d => ({ r, d }))).sort((a, b) => a.d.localeCompare(b.d));
    const recent = all.filter(r => r.div && r.div.status !== "yok" && r.div.yield).sort((a, b) => b.div.yield - a.div.yield).slice(0, 8);
    if (!up.length && !recent.length) return "";
    return `<section class="card"><div class="card-head"><h2 class="card-title">Temettü</h2><span class="card-meta">KAP kar payı kararları · brüt, pay başına</span></div>
      <div class="res-cols"><div><p class="d-sub">Yaklaşan hak kullanımlar</p>${up.length ? `<table class="fa-kv"><tbody>${up.slice(0, 10).map(({ r, d }) => `<tr><th scope="row"><button type="button" class="tk-cmp link-btn" data-code="${r.code}">${r.code}</button> <span class="muted">${fmt.date(d + "T12:00:00Z", { day: "numeric", month: "short" })}</span></th><td class="num">${fmt.num(r.div.gross, 2)} ₺ <small class="muted">${pct(r.div.yield)}</small>${r.div.status !== "kesin" ? ` <small class="warn-t" data-tip="Genel kurul onayı bekleniyor">öneri</small>` : ""}</td></tr>`).join("")}</tbody></table>` : `<p class="tp-empty">Önümüzdeki günlerde hak kullanım yok.</p>`}</div>
      <div><p class="d-sub">En yüksek temettü verimi (son karar)</p><table class="fa-kv"><tbody>${recent.map(r => `<tr><th scope="row"><button type="button" class="tk-cmp link-btn" data-code="${r.code}">${r.code}</button></th><td class="num">${pct(r.div.yield)} <small class="muted">${fmt.num(r.div.gross, 2)} ₺</small></td></tr>`).join("")}</tbody></table></div></div>
      <p class="card-foot">Takvim sekmesinde de görünür. Verim = son karardaki brüt kar payı / güncel fiyat.</p></section>`;
  }
  function sectorTable(all) {
    const by = {};
    all.forEach(r => (by[r.sector || "Diğer"] ||= []).push(r));
    const rows_ = Object.entries(by).map(([sec, xs]) => ({ sec, n: xs.length, pe: med(xs.map(r => r.v?.pe)), pb: med(xs.map(r => r.v?.pb)),
      ev: med(xs.map(r => r.v?.ev_ebitda)), roe: med(xs.map(r => r.r?.roe)), ov: med(xs.map(r => r.overall)) })).sort((a, b) => b.n - a.n || a.sec.localeCompare(b.sec, "tr"));
    return `<section class="card card-flush"><div class="card-head"><h2 class="card-title">Sektörler</h2><span class="card-meta">medyan değerler · satıra tıkla, tabloyu süz</span></div>
      <div class="tbl-scroll"><table class="tbl fa-tbl"><thead><tr><th>Sektör</th><th class="num">Şirket</th><th class="num">F/K</th><th class="num">PD/DD</th><th class="num">FD/FAVÖK</th><th class="num">ROE</th><th class="num">Genel skor</th></tr></thead>
      <tbody>${rows_.map(r => `<tr class="row" tabindex="0" data-sec="${esc(r.sec)}"><td>${esc(r.sec)}</td><td class="num">${r.n}</td><td class="num">${x(r.pe)}</td><td class="num">${x(r.pb)}</td><td class="num">${x(r.ev)}</td><td class="num">${pct(r.roe)}</td><td class="num">${r.ov == null ? "—" : Math.round(r.ov)}</td></tr>`).join("")}</tbody></table></div></section>`;
  }
  function bindRows(el) {
    $$("tr.row[data-sec]", el).forEach(tr => { const f = () => { S.sector = tr.dataset.sec; renderOverview(); $("#view-temel").scrollIntoView?.({ block: "start" }); };
      tr.onclick = f; tr.onkeydown = e => { if (e.key === "Enter") f(); }; });
    $$("tr.row[data-code]", el).forEach(tr => {
      const open = () => sh.go("hisse", { param: tr.dataset.code, focus: true });
      tr.onclick = open; tr.onkeydown = e => { if (e.key === "Enter") open(); };
    });
  }

  // ───────────── grafik yardımcıları (SVG; tek eksen, ince işaretler, ipucu)
  const H = 200, PAD = { l: 52, r: 10, t: 12, b: 26 };
  const cw = el => Math.max(260, Math.round(el?.clientWidth || 560));
  function niceMax(v) { if (v <= 0) return 1; const p = 10 ** Math.floor(Math.log10(v)); const n = v / p; return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p; }
  function axisFmt(v, kind) {
    if (kind === "pct") return (v < 0 ? MINUS : "") + "%" + fmt.num(Math.abs(v * 100), 0);
    if (kind === "x") return fmt.num(v, 1);
    const a = Math.abs(v);
    return a >= 1e12 ? fmt.num(v / 1e12, a >= 1e13 ? 0 : 1) + " tn" : a >= 1e9 ? fmt.num(v / 1e9, a >= 1e10 ? 0 : 1) + " mr" : a >= 1e6 ? fmt.num(v / 1e6, 0) + " mn" : fmt.num(v, 0);
  }
  function barChart(labels, vals, { kind = "tl", tipFmt = tl, color = "var(--series-1)", w: W = 560 } = {}) {
    const ok = vals.filter(v => v != null);
    if (!ok.length) return `<p class="tp-empty">Veri yok</p>`;
    const max = niceMax(Math.max(0, ...ok)), min = Math.min(0, ...ok) < 0 ? -niceMax(-Math.min(...ok)) : 0;
    const iw = W - PAD.l - PAD.r, ih = H - PAD.t - PAD.b;
    const y = v => PAD.t + ih * (max - v) / (max - min);
    const bw = Math.min(36, iw / labels.length * 0.55);
    const ticks = [min, (min + max) / 2, max].filter((v, i, a) => a.indexOf(v) === i);
    return `<svg class="fa-chart" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Çubuk grafik">
      ${ticks.map(t => `<line x1="${PAD.l}" x2="${W - PAD.r}" y1="${y(t)}" y2="${y(t)}" class="${t === 0 ? "ax0" : "gl"}"/><text x="${PAD.l - 6}" y="${y(t) + 4}" class="tk-y">${axisFmt(t, kind)}</text>`).join("")}
      ${labels.map((l, i) => {
        const cx = PAD.l + iw * (i + 0.5) / labels.length, v = vals[i];
        const bar = v == null ? "" : (() => { const y0 = y(0), y1 = y(v), h = Math.max(1, Math.abs(y1 - y0)); const top = Math.min(y0, y1);
          return `<rect x="${cx - bw / 2}" y="${top}" width="${bw}" height="${h}" rx="3" fill="${v < 0 ? "var(--down)" : color}" data-tip="<b>${esc(l)}</b><br>${esc(tipFmt(v))}"/>`; })();
        return `${bar}<rect x="${cx - iw / labels.length / 2}" y="${PAD.t}" width="${iw / labels.length}" height="${ih}" fill="transparent" ${v != null ? `data-tip="<b>${esc(l)}</b><br>${esc(tipFmt(v))}"` : ""}/><text x="${cx}" y="${H - 8}" class="tk-x">${esc(l)}</text>`;
      }).join("")}</svg>`;
  }
  function lineChart(labels, series, { kind = "pct", tipFmt = pct, w: W = 560 } = {}) {
    const all = series.flatMap(s => s.vals).filter(v => v != null && isFinite(v));
    if (!all.length) return `<p class="tp-empty">Veri yok</p>`;
    let lo = Math.min(...all), hi = Math.max(...all);
    if (lo === hi) { lo -= Math.abs(lo) * 0.1 || 1; hi += Math.abs(hi) * 0.1 || 1; }
    const span = hi - lo; lo -= span * 0.08; hi += span * 0.08;
    const iw = W - PAD.l - PAD.r, ih = H - PAD.t - PAD.b;
    const xp = i => PAD.l + (labels.length === 1 ? iw / 2 : iw * i / (labels.length - 1));
    const y = v => PAD.t + ih * (hi - v) / (hi - lo);
    const ticks = [lo, (lo + hi) / 2, hi];
    const COL = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)", "var(--series-5)"];
    const paths = series.map((s, si) => {
      let d = "", pen = false;
      s.vals.forEach((v, i) => { if (v == null || !isFinite(v)) { pen = false; return; } d += `${pen ? "L" : "M"}${xp(i).toFixed(1)},${y(v).toFixed(1)}`; pen = true; });
      const dots = s.vals.map((v, i) => v == null || !isFinite(v) ? "" : `<circle cx="${xp(i)}" cy="${y(v)}" r="3.5" fill="${COL[si]}" stroke="var(--surface)" stroke-width="2"/>`).join("");
      return `<path d="${d}" fill="none" stroke="${COL[si]}" stroke-width="2" stroke-linejoin="round"/>${dots}`;
    }).join("");
    const hits = labels.map((l, i) => {
      const tip = `<b>${esc(l)}</b>` + series.map((s, si) => `<br><span style="color:${COL[si]}">●</span> ${esc(s.name)}: ${esc(tipFmt(s.vals[i]))}`).join("");
      const w = iw / Math.max(1, labels.length - 1);
      return `<rect x="${xp(i) - w / 2}" y="${PAD.t}" width="${w}" height="${ih}" fill="transparent" data-tip="${tip.replace(/"/g, "&quot;")}"/>`;
    }).join("");
    const step = Math.ceil(labels.length / 8);
    return `<svg class="fa-chart" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Çizgi grafik">
      ${ticks.map(t => `<line x1="${PAD.l}" x2="${W - PAD.r}" y1="${y(t)}" y2="${y(t)}" class="gl"/><text x="${PAD.l - 6}" y="${y(t) + 4}" class="tk-y">${axisFmt(t, kind)}</text>`).join("")}
      ${lo < 0 && hi > 0 ? `<line x1="${PAD.l}" x2="${W - PAD.r}" y1="${y(0)}" y2="${y(0)}" class="ax0"/>` : ""}
      ${paths}${hits}
      ${labels.map((l, i) => i % step === 0 || i === labels.length - 1 ? `<text x="${xp(i)}" y="${H - 8}" class="tk-x">${esc(l)}</text>` : "").join("")}</svg>
      ${series.length > 1 ? `<div class="chart-legend">${series.map((s, si) => `<span><i style="background:${COL[si]}"></i>${esc(s.name)}</span>`).join("")}</div>` : ""}`;
  }
  function radarChart(cats, series) {
    const R = 92, cx = 220, cy = 128, n = cats.length;
    const pt = (i, v) => { const a = -Math.PI / 2 + 2 * Math.PI * i / n; return [cx + Math.cos(a) * R * v / 100, cy + Math.sin(a) * R * v / 100]; };
    const COL = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)", "var(--series-5)"];
    const rings = [25, 50, 75, 100].map(v => `<polygon points="${cats.map((_, i) => pt(i, v).join(",")).join(" ")}" class="rd-ring"/>`).join("");
    const spokes = cats.map((c, i) => { const [x2, y2] = pt(i, 100), [lx, ly] = pt(i, 114);
      return `<line x1="${cx}" y1="${cy}" x2="${x2}" y2="${y2}" class="rd-ring"/><text x="${lx}" y="${ly + 3}" class="rd-lbl" text-anchor="${Math.abs(lx - cx) < 5 ? "middle" : lx > cx ? "start" : "end"}">${esc(c)}</text>`; }).join("");
    const polys = series.map((s, si) => `<polygon points="${s.vals.map((v, i) => pt(i, v ?? 0).join(",")).join(" ")}" fill="${COL[si]}" fill-opacity=".12" stroke="${COL[si]}" stroke-width="2"/>` +
      s.vals.map((v, i) => { const [px, py] = pt(i, v ?? 0); return `<circle cx="${px}" cy="${py}" r="4" fill="${COL[si]}" stroke="var(--surface)" stroke-width="2" data-tip="<b>${esc(s.name)}</b> · ${esc(cats[i])}: ${v ?? "—"}"/>`; }).join("")).join("");
    return `<svg class="fa-radar" viewBox="0 0 440 260" role="img" aria-label="Kategori puanları">${rings}${spokes}${polys}</svg>
      <div class="chart-legend">${series.map((s, si) => `<span><i style="background:${COL[si]}"></i>${esc(s.name)}</span>`).join("")}</div>`;
  }
  function ring(v, label, g, sub) {
    const r = 34, c = 2 * Math.PI * r, f = v == null ? 0 : v / 100;
    const col = v == null ? "var(--surface-3)" : v >= 65 ? "var(--up)" : v >= 50 ? "var(--warn-line)" : "var(--down)";
    return `<div class="card fa-ring"><svg viewBox="0 0 84 84" aria-hidden="true"><circle cx="42" cy="42" r="${r}" class="rg-bg"/><circle cx="42" cy="42" r="${r}" stroke="${col}" class="rg-fg" stroke-dasharray="${c * f} ${c}" transform="rotate(-90 42 42)"/>
      <text x="42" y="46" class="rg-v">${v ?? "—"}</text></svg><div><p class="kpi-label">${esc(label)}</p><p class="fa-ring-g">${gradeTag(g)} ${esc(gLabel(g))}</p><p class="kpi-sub">${sub}</p></div></div>`;
  }
  const gLabel = g => ({ A: "Çok güçlü", B: "Güçlü", C: "Orta", D: "Zayıf", E: "Çok zayıf" }[g] || "");

  // ───────────── şirket sayfası
  function realF(se, i) {
    if (!S.real) return 1;
    const base = se.cpi[se.cpi.length - 1], c = se.cpi[i];
    return base && c ? base / c : 1;
  }
  function amountsLabel(se) { return S.real ? `Reel (${se.periods[se.periods.length - 1]} TL)` : "Nominal"; }
  async function renderCompany() {
    const el = $("#view-hisse");
    const code = (sh.param || "").toUpperCase();
    if (!code) { sh.go("temel", { push: false }); return; }
    if (notReady(el)) return;
    const row = rowOf(code);
    $("#pageTitle").textContent = code; $("#pageSub").textContent = row ? trTitle(row.title) : "";
    document.title = `${code} · Temel Analiz · Piyasa Radarı`;
    if (!el.dataset.code || el.dataset.code !== code) { loading(el); el.dataset.code = code; }
    let d;
    try { d = await doc(code); } catch (e) {
      el.innerHTML = `<div class="card">${sh.stateHTML({ kind: "info", title: `${code} için temel analiz verisi yok`, msg: "Şirket BIST-100 kapsamında değil ya da tabloları henüz yüklenmedi." })}</div>`; return;
    }
    if (sh.route !== "hisse" || (sh.param || "").toUpperCase() !== code) return;
    const m = d.metrics, se = d.series;
    if (!m || !se) {
      el.innerHTML = `<div class="card">${sh.stateHTML({ kind: "info", title: `${code}: ${d.template === "finansal" ? "finansal kuruluş şablonu (kapsam dışı)" : "hesaplama için yeterli dönem yok"}`, msg: d.template === "finansal" ? "Banka ve sigorta tabloları ayrı modelle eklenecek." : "Son 12 ay hesabı için bir önceki yıl sonu raporu gerekiyor; yükleme sürüyor." })}</div>`; return;
    }
    const tabs = [["ozet", "Özet"], ["fin", "Finansallar"], ["graf", "Grafikler"], ["detay", "Detaylı Analiz"]];
    const v = m.valuation || {};
    el.innerHTML = `
      <div class="fa-head card">
        <span class="fa-badge">${code}</span>
        <div class="fa-h-main"><h2 class="fa-h-title">${esc(trTitle(d.title))}</h2>
          <p class="fa-h-tags"><span class="tag na">${esc(row?.sector || "—")}</span><span class="tag na">Son dönem ${esc(m.period)}</span><span class="tag na">${d.reports?.[m.period]?.consolidated ? "Konsolide" : "Solo"}</span>${(S.screen.rows.find(r => r.code === code)) ? "" : ""}</p></div>
        <div class="fa-h-px"><b class="mono">${fmt.num(v.price, 2)} ₺</b><span class="muted">${tl(v.mcap)} piyasa değeri</span></div>
        <div class="fa-h-acts">${realToggle()}
          <button type="button" class="btn" id="faCmpAdd">${S.cmp.includes(code) ? "Karşılaştırmada ✓" : "Karşılaştırmaya ekle"}</button>
          ${window.radar?.openTicker ? `<button type="button" class="btn" id="faSig">Sinyaller</button>` : ""}</div>
      </div>
      <div class="seg fa-tabs" role="tablist">${tabs.map(([k, l]) => `<button type="button" role="tab" data-tab="${k}" aria-checked="${S.tab === k}" aria-selected="${S.tab === k}">${l}</button>`).join("")}</div>
      <div id="faBody"></div>`;
    $$("[data-tab]", el).forEach(b => b.onclick = () => { S.tab = b.dataset.tab; renderCompany(); });
    bindReal(el, renderCompany);
    $("#faCmpAdd").onclick = () => { if (!S.cmp.includes(code)) S.cmp = [...S.cmp, code].slice(-5); store.set("radar.finCmp", S.cmp); sh.go("karsilastir", { param: S.cmp.join(",") }); };
    $("#faSig") && ($("#faSig").onclick = e => { sh.go("sinyal"); setTimeout(() => window.radar?.openTicker?.(code, e.target), 60); });
    const body = $("#faBody");
    if (S.tab === "ozet") body.innerHTML = tabSummary(d, row);
    else if (S.tab === "fin") { body.innerHTML = tabFin(d); bindFin(body, d); }
    else if (S.tab === "graf") { body.innerHTML = tabCharts(d); bindCharts(body, d); }
    else { body.innerHTML = tabDetail(d); divHistory(code); }
    $$(".tk-cmp", body).forEach(b => b.onclick = () => sh.go("hisse", { param: b.dataset.code }));
  }

  function summaryFin(d, row, tmpl) {
    const m = d.metrics, r = m.ratios, se = d.series, i = se.periods.length - 1;
    const ttm = k => se.ttm[k]?.[i];
    const strong = [], weak = [];
    const add = (cond, arr, txt) => { if (cond) arr.push(txt); };
    add(r.real_roe != null && r.real_roe > 0, strong, `Enflasyonun üzerinde özkaynak getirisi (reel ROE ${pctS(r.real_roe)})`);
    add(r.real_roe != null && r.real_roe < 0, weak, `Özkaynak getirisi enflasyonun altında (reel ROE ${pctS(r.real_roe)})`);
    add(r.net_growth != null && r.net_growth > 0.1, strong, `Reel net kar büyümesi (${pctS(r.net_growth)})`);
    add(r.net_growth != null && r.net_growth < -0.2, weak, `Reel net kar düşüşü (${pctS(r.net_growth)})`);
    if (tmpl === "banka") {
      add(r.cost_income != null && r.cost_income < 0.4, strong, `Düşük maliyet/gelir (${pct(r.cost_income)})`);
      add(r.cost_income != null && r.cost_income > 0.6, weak, `Yüksek maliyet/gelir (${pct(r.cost_income)})`);
      add(r.cost_of_risk != null && r.cost_of_risk < 0.015, strong, `Düşük risk maliyeti (${pct(r.cost_of_risk, 2)})`);
      add(r.cost_of_risk != null && r.cost_of_risk > 0.03, weak, `Yüksek risk maliyeti (${pct(r.cost_of_risk, 2)})`);
      add(r.fee_cover != null && r.fee_cover >= 0.8, strong, `Ücret-komisyon gelirleri giderlerin ${pct(r.fee_cover, 0)}'ini karşılıyor`);
      add(r.ldr != null && r.ldr > 1.05, weak, `Kredi/mevduat %100'ün üzerinde (${pct(r.ldr)}) — piyasa fonlamasına bağımlılık`);
      add(r.ldr != null && r.ldr < 0.85, strong, `Mevduatla rahat fonlanan bilanço (kredi/mevduat ${pct(r.ldr)})`);
      add(r.equity_assets != null && r.equity_assets < 0.07, weak, `İnce özkaynak tamponu (özkaynak/aktif ${pct(r.equity_assets)})`);
      add(r.nim != null && r.nim < 0.02, weak, `Düşük net faiz marjı (${pct(r.nim, 2)})`);
    } else {
      add(r.combined != null && r.combined < 0.95, strong, `Teknik kârlı sigortacılık (birleşik oran ${pct(r.combined)})`);
      add(r.combined != null && r.combined > 1.05, weak, `Birleşik oran %100'ün üzerinde (${pct(r.combined)}) — kâr yatırım gelirine dayanıyor`);
      add(r.loss_ratio != null && r.loss_ratio > 0.8, weak, `Yüksek hasar oranı (${pct(r.loss_ratio)})`);
      add(r.premium_growth != null && r.premium_growth > 0.1, strong, `Reel prim büyümesi (${pctS(r.premium_growth)})`);
      add(r.premium_growth != null && r.premium_growth < 0, weak, `Reel prim daralması (${pctS(r.premium_growth)})`);
      add(r.reserves_cover != null && r.reserves_cover >= 1.2, strong, `Teknik karşılıkları rahat karşılayan likit varlıklar (${x(r.reserves_cover)})`);
    }
    const view = m.overall == null ? "—" : m.overall >= 65 ? "Olumlu" : m.overall >= 50 ? "Nötr / Karışık" : "Zayıf";
    const viewCls = m.overall == null ? "" : m.overall >= 65 ? "up" : m.overall >= 50 ? "warn-t" : "down";
    const cats = (f) => Object.entries(m.categories).filter(([, s]) => s != null && f(s)).map(([c, s]) => `${c.toLocaleLowerCase("tr")} (${s})`).join(", ") || "—";
    const lead = tmpl === "banka"
      ? `son 12 ayda faaliyet geliri <b>${tl(ttm("revenue"))}</b> (net faiz geliri ${tl(ttm("nii"))}, net ücret-komisyon ${tl(ttm("fees"))}), ana ortaklık net karı <b>${tl(ttm("net_parent"))}</b>; ROE ${pct(r.roe)}, maliyet/gelir ${pct(r.cost_income)}, risk maliyeti ${pct(r.cost_of_risk, 2)}`
      : `son 12 ayda brüt prim <b>${tl(ttm("revenue"))}</b>, birleşik oran ${pct(r.combined)}, ana ortaklık net karı <b>${tl(ttm("net_parent"))}</b>; ROE ${pct(r.roe)}`;
    const text = `<b>${esc(trTitle(d.title))}</b> (${d.code}) ${TPL[tmpl].toLocaleLowerCase("tr")}. ${m.period} itibarıyla ${lead}.
      Tablolar enflasyon muhasebesi (TMS 29) uygulanmadan, nominal yayımlanır; büyümeler TÜFE ile reelleştirildi (yıllık TÜFE ${pct(r.inflation)}).
      Kalite puanı <b>${m.quality ?? "—"}/100</b>; güçlü alanlar: ${cats(s => s >= 75)}; zayıf alanlar: ${cats(s => s < 50)}. Değerleme puanı <b>${m.valuation_score ?? "—"}/100</b>, genel skor <b>${m.overall ?? "—"}/100 (${m.grade || "—"})</b>.`;
    return { strong, weak, view, viewCls, text };
  }
  function summaryText(d, row) {
    const tmpl = tplOf(d);
    if (tmpl !== "sanayi") return summaryFin(d, row, tmpl);
    const m = d.metrics, r = m.ratios, v = m.valuation, se = d.series, i = se.periods.length - 1;
    const ttm = k => se.ttm[k]?.[i];
    const strong = [], weak = [];
    const add = (cond, arr, txt) => { if (cond) arr.push(txt); };
    add(r.net_debt_ebitda != null && r.net_debt_ebitda < 1 || (se.bs.net_debt?.[i] ?? 1) < 0, strong, (se.bs.net_debt?.[i] ?? 0) < 0 ? "Net nakit pozisyonu" : `Düşük net borç/FAVÖK (${x(r.net_debt_ebitda)})`);
    add(r.net_debt_ebitda != null && r.net_debt_ebitda > 3, weak, `Yüksek net borç/FAVÖK (${x(r.net_debt_ebitda)})`);
    add(r.net_margin != null && r.net_margin >= 0.15, strong, `Sağlam net kar marjı (${pct(r.net_margin)})`);
    add(r.net_margin != null && r.net_margin < 0.03, weak, `Zayıf net kar marjı (${pct(r.net_margin)})`);
    add(r.interest_cov != null && r.interest_cov >= 5, strong, `Finansman giderlerini rahat karşılayan FAVÖK (${x(r.interest_cov)})`);
    add(r.interest_cov != null && r.interest_cov < 2, weak, `FAVÖK finansman giderini zor karşılıyor (${x(r.interest_cov)})`);
    add(r.cfo_ni != null && r.cfo_ni >= 1, strong, `Karın nakde dönüşümü güçlü (${x(r.cfo_ni)})`);
    add(r.cfo_ni != null && r.cfo_ni < 0.5, weak, `Karın nakde dönüşümü zayıf (${x(r.cfo_ni)})`);
    add(r.roe != null && r.roe >= 0.25, strong, `Yüksek özkaynak karlılığı (${pct(r.roe)})`);
    add(r.roe != null && r.roe < 0.05, weak, `Düşük özkaynak karlılığı (${pct(r.roe)})`);
    add(r.ebitda_margin != null && r.ebitda_margin >= 0.25, strong, `Güçlü FAVÖK marjı (${pct(r.ebitda_margin)})`);
    add(r.current != null && r.current >= 1.5, strong, `Rahat likidite (cari oran ${x(r.current)})`);
    add(r.current != null && r.current < 1, weak, `Cari oran 1'in altında (${x(r.current)})`);
    add(r.rev_growth != null && r.rev_growth >= 0.1, strong, `Reel satış büyümesi (${pctS(r.rev_growth)})`);
    add(r.rev_growth != null && r.rev_growth < -0.05, weak, `Reel satış daralması (${pctS(r.rev_growth)})`);
    add(r.net_growth != null && r.net_growth < -0.2, weak, `Reel net kar düşüşü (${pctS(r.net_growth)})`);
    add(ttm("fcf") != null && ttm("fcf") < 0, weak, `Negatif serbest nakit akışı (${tl(ttm("fcf"))})`);
    add(r.ccc != null && r.ccc > 180, weak, `Uzun nakit dönüşüm süresi (${days(r.ccc)})`);
    add(r.asset_turnover != null && r.asset_turnover < 0.3, weak, `Düşük aktif devir hızı (${x(r.asset_turnover)})`);
    const view = m.overall == null ? "—" : m.overall >= 65 ? "Olumlu" : m.overall >= 50 ? "Nötr / Karışık" : "Zayıf";
    const viewCls = m.overall == null ? "" : m.overall >= 65 ? "up" : m.overall >= 50 ? "warn-t" : "down";
    const text = `<b>${esc(trTitle(d.title))}</b> (${d.code}) ${esc(row?.sector || "")} sektöründe. ${m.period} itibarıyla son 12 aylık hasılat <b>${tl(ttm("revenue"))}</b>${r.rev_growth != null ? ` (reel ${pctS(r.rev_growth)})` : ""}, FAVÖK <b>${tl(ttm("ebitda"))}</b> (marj ${pct(r.ebitda_margin)}), ana ortaklık net karı <b>${tl(ttm("net_parent"))}</b>.
      Bilanço (kalite) puanı <b>${m.quality ?? "—"}/100</b>; güçlü alanlar: ${Object.entries(m.categories).filter(([, s]) => s >= 75).map(([c, s]) => `${c.toLocaleLowerCase("tr")} (${s})`).join(", ") || "—"}; zayıf alanlar: ${Object.entries(m.categories).filter(([, s]) => s != null && s < 50).map(([c, s]) => `${c.toLocaleLowerCase("tr")} (${s})`).join(", ") || "—"}.
      Değerleme puanı <b>${m.valuation_score ?? "—"}/100</b> ile genel skor <b>${m.overall ?? "—"}/100 (${m.grade || "—"})</b>. Piotroski ${m.piotroski ?? "—"}/9, Altman Z'' ${fmt.num(m.altman_z2, 2)} (${zZone(m.altman_z2)}), Beneish M ${fmt.num(m.beneish_m, 2)} (${m.beneish_m == null ? "—" : m.beneish_m < -1.78 ? "düşük risk" : "dikkat"}).`;
    return { strong, weak, view, viewCls, text };
  }
  const zZone = z => z == null ? "—" : z > 2.6 ? "güvenli bölge" : z > 1.1 ? "gri bölge" : "riskli bölge";

  function tabSummary(d, row) {
    const tmpl = tplOf(d);
    const m = d.metrics, r = m.ratios, v = m.valuation, se = d.series, i = se.periods.length - 1;
    const ttm = k => se.ttm[k]?.[i];
    const q = (k, delta) => delta == null ? "" : `<span class="${delta >= 0 ? "up" : "down"}">${delta >= 0 ? "↑" : "↓"} ${k}</span>`;
    const histPrev = k => { const h = m.history?.[k]; if (!h) return null; const j = h.length - 5; return j >= 0 ? h[j] : null; };
    const dpt = k => r[k] != null && histPrev(k) != null ? (r[k] - histPrev(k)) * 100 : null;
    const s = summaryText(d, row);
    const res = window.radarResearch?.data?.consensus?.[d.code] || null;
    const mini = (title, badge, items) => `<div class="card fa-mini"><div class="card-head"><h3 class="card-title">${title}</h3>${badge ? `<span class="tag na">${badge}</span>` : ""}</div>
      <table class="fa-kv"><tbody>${items.map(([k, val, extra]) => `<tr><th scope="row">${k}</th><td class="num">${val}${extra ? ` <small>${extra}</small>` : ""}</td></tr>`).join("")}</tbody></table></div>`;
    const crit = Object.entries(m.criteria);
    return `
      <div class="fa-rings">
        ${ring(m.overall, "Genel skor", m.grade, "Kalite %60 + değerleme %40")}
        ${ring(m.quality, "Bilanço (kalite) puanı", m.quality_grade, tmpl === "sanayi" ? "6 kategori ortalaması" : `${TPL[tmpl]} modeli · ${Object.keys(m.categories).length} kategori`)}
        ${ring(m.valuation_score, "Değerleme puanı", m.valuation_grade, m.intrinsic ? `İçsel değer ${fmt.num(m.intrinsic, 2)} ₺ · potansiyel ${pctS(m.potential, 0)}` : "Sektör çarpanlarına göre")}
      </div>
      <div class="card-head fa-sec"><h2 class="card-title">Kısaca</h2><span class="card-meta">${m.period} · ${tmpl === "sanayi" ? "reel" : "nominal tablolar, büyümeler reel"} · akışlar son 12 ay</span></div>
      <div class="fa-minis">
        ${tmpl === "banka" ? [
          mini("Karlılık", "son 12 ay", [["ROE", pct(r.roe), q(fmt.num(dpt("roe"), 1) + " puan", dpt("roe"))], ["Reel ROE", pctS(r.real_roe)], ["ROA", pct(r.roa, 2)]]),
          mini("Gelir yapısı", "son 12 ay", [["Net faiz marjı", pct(r.nim, 2)], ["Ücret-komisyon payı", pct(r.fee_share)], ["Maliyet / gelir", pct(r.cost_income)]]),
          mini("Risk ve fonlama", "", [["Risk maliyeti", pct(r.cost_of_risk, 2)], ["Kredi / mevduat", pct(r.ldr)], ["Özkaynak / aktif", pct(r.equity_assets)]]),
          mini("Büyüme", "reel, yıllık", [["Krediler", pctS(r.loan_growth)], ["Mevduat", pctS(r.deposit_growth)], ["Net kar", pctS(r.net_growth)]])].join("")
        : tmpl === "sigorta" ? [
          mini("Karlılık", "son 12 ay", [["ROE", pct(r.roe), q(fmt.num(dpt("roe"), 1) + " puan", dpt("roe"))], ["Reel ROE", pctS(r.real_roe)], ["ROA", pct(r.roa, 2)]]),
          mini("Teknik sonuç", "son 12 ay", [["Birleşik oran", pct(r.combined)], ["Hasar oranı", pct(r.loss_ratio)], ["Gider oranı", pct(r.expense_ratio)]]),
          mini("Sermaye ve likidite", "", [["Özsermaye / aktif", pct(r.equity_assets)], ["Likit varlık / teknik karşılık", x(r.reserves_cover)], ["Saklama oranı", pct(r.retention)]]),
          mini("Büyüme", "reel, yıllık", [["Brüt prim", pctS(r.premium_growth)], ["Net kar", pctS(r.net_growth)], ["Yıllık TÜFE", pct(r.inflation)]])].join("")
        : [
        mini("Karlılık", "son 12 ay", [["ROE", pct(r.roe), q(fmt.num(dpt("roe"), 1) + " puan", dpt("roe"))], ["FAVÖK marjı", pct(r.ebitda_margin), q(fmt.num(dpt("ebitda_margin"), 1) + " puan", dpt("ebitda_margin"))], ["Net kar marjı", pct(r.net_margin), q(fmt.num(dpt("net_margin"), 1) + " puan", dpt("net_margin"))]]),
        mini("Büyüme", "reel, yıllık", [["Hasılat", pctS(r.rev_growth)], ["FAVÖK", pctS(r.ebitda_growth)], ["Net kar", pctS(r.net_growth)]]),
        mini("Borçluluk", "", [["Net borç / FAVÖK", (se.bs.net_debt?.[i] ?? 0) < 0 ? "Net nakit" : x(r.net_debt_ebitda)], ["Borç / özkaynak", x(r.debt_equity)], ["Cari oran", x(r.current)]]),
        mini("Nakit akışı", "son 12 ay", [["Serbest nakit akışı", tl(ttm("fcf"))], ["İşletme nakdi / kar", x(r.cfo_ni)], ["SNA marjı", pct(r.fcf_margin)]])].join("")}
        ${mini("Değerleme", "", [["F/K · PD/DD", `${x(v.pe)} · ${x(v.pb)}`], tmpl === "sanayi" ? ["FD/FAVÖK", x(v.ev_ebitda)] : ["Kazanç getirisi", pct(v.earnings_yield)], ["İçsel değer", m.intrinsic ? fmt.num(m.intrinsic, 2) + " ₺" : "—", m.potential != null ? q(pctS(m.potential, 1), m.potential) : ""]])}
        ${(() => { const dv = row?.div;
          if (dv && dv.status !== "yok") return mini("Temettü", dv.status === "kesin" ? "KAP · kesin" : "KAP · öneri", [["Brüt / net (pay başı)", `${fmt.num(dv.gross, 2)} · ${fmt.num(dv.net, 2)} ₺`], ["Verim (brüt)", pct(dv.yield)], [dv.next_ex ? "Hak kullanım" : "Son hak kullanım", dv.next_ex || dv.ex?.[dv.ex.length - 1] || "genel kurul bekleniyor"]]);
          if (dv?.status === "yok") return mini("Temettü", "KAP", [["Son karar", "Dağıtım yok"], ["Karar tarihi", dv.decision || "—"], ["Ödenen (12A)", tl(Math.abs(ttm("dividends_paid") || 0))]]);
          return mini("Temettü", "nakit akışından", [["Ödenen (12A)", tl(Math.abs(ttm("dividends_paid") || 0))], ["Verim (12A)", pct(v.div_yield)], ["Dağıtım oranı", ttm("net_parent") > 0 ? pct(Math.abs(ttm("dividends_paid") || 0) / ttm("net_parent")) : "—"]]); })()}
        ${mini("Beklentiler", "aracı kurumlar", res ? [["Medyan hedef", res.median_tp ? fmt.num(res.median_tp, 2) + " ₺" : "—", res.median_tp && v.price ? q(pctS(res.median_tp / v.price - 1, 1), res.median_tp / v.price - 1) : ""], ["Hedef veren kurum", fmt.int(res.n || 0)], ["Dağılım", `${res.dist?.AL || 0} AL · ${res.dist?.TUT || 0} TUT · ${res.dist?.SAT || 0} SAT`]] : [["Kurum notu", "Yok"], ["Kapsam", "İzleme listesi"]])}
        ${mini("Şirket", "", [["Ödenmiş sermaye", tl(se.bs.paid_capital?.[i])], ["Özkaynak (ana ort.)", tl(se.bs.equity_parent?.[i])], ["Toplam varlık", tl(se.bs.total_assets?.[i])]])}
      </div>
      <div class="fa-two">
        <section class="card"><div class="card-head"><h2 class="card-title">Yönetici özeti</h2><span class="fa-outlook ${s.viewCls}">Temel görünüm: ${s.view}</span></div>
          <p class="d-sum">${s.text}</p>
          <div class="res-cols"><div><p class="d-sub">Güçlü yönler</p><ul class="fa-list ok">${s.strong.map(t => `<li>${esc(t)}</li>`).join("") || "<li class='na'>Öne çıkan yok</li>"}</ul></div>
          <div><p class="d-sub">Zayıf yönler</p><ul class="fa-list no">${s.weak.map(t => `<li>${esc(t)}</li>`).join("") || "<li class='na'>Öne çıkan yok</li>"}</ul></div></div>
          <p class="card-foot">Kural tabanlı özet; oranlardan otomatik üretilir, yatırım tavsiyesi değildir.</p></section>
        <section class="card"><div class="card-head"><h2 class="card-title">Puan dağılımı</h2></div>
          ${Object.entries(m.categories).map(([c, sc]) => `<div class="fa-bar"><span>${esc(c)}</span><span class="fa-track"><i style="width:${sc ?? 0}%;background:${sc == null ? "var(--surface-3)" : sc >= 65 ? "var(--up)" : sc >= 50 ? "var(--warn-line)" : "var(--down)"}"></i></span><b class="mono">${sc ?? "—"}</b></div>`).join("")}
          ${tmpl !== "sanayi" ? `<p class="card-foot">Piotroski, Altman Z'' ve Beneish M sanayi şirketleri için tasarlandı; ${TPL[tmpl].toLocaleLowerCase("tr")} modelinde kullanılmaz.</p>` : ""}
          <div class="fa-scores" ${tmpl !== "sanayi" ? "hidden" : ""}>
            <div><span class="kpi-label">Piotroski F</span><b class="mono">${m.piotroski ?? "—"}/9</b><small>${m.piotroski == null ? "" : m.piotroski >= 7 ? "✓ Güçlü" : m.piotroski >= 4 ? "● Orta" : "✗ Zayıf"}</small></div>
            <div><span class="kpi-label">Altman Z''</span><b class="mono">${fmt.num(m.altman_z2, 2)}</b><small>${m.altman_z2 == null ? "" : (m.altman_z2 > 2.6 ? "✓ " : m.altman_z2 > 1.1 ? "● " : "✗ ") + zZone(m.altman_z2)}</small></div>
            <div><span class="kpi-label">Beneish M</span><b class="mono">${fmt.num(m.beneish_m, 2)}</b><small>${m.beneish_m == null ? "" : m.beneish_m < -1.78 ? "✓ Düşük risk" : "! Dikkat"}</small></div>
          </div>
          <div class="card-head fa-sec"><h3 class="card-title">Kriter uyumu</h3><a class="link-btn" href="#tarama">Listeler</a></div>
          <table class="fa-kv"><tbody>${crit.map(([k, c]) => { const r0 = c.total ? c.pass / c.total : 0;
            if (!c.known || !c.total) return `<tr><th scope="row">${esc(k)}</th><td class="num muted" data-tip="Bir yıl önceki dönem yüklenince hesaplanır">veri bekleniyor</td></tr>`;
            return `<tr><th scope="row">${esc(k)}</th><td class="num"><b>${c.pass}/${c.total}</b>${c.known < c.total ? ` <small class="muted" data-tip="${c.total - c.known} kriter için veri yok">(${c.total - c.known} —)</small>` : ""} <span class="tag ${r0 >= 0.75 ? "fa-ok" : r0 >= 0.5 ? "fa-mid" : "fa-no"}">${r0 >= 0.75 ? "✓" : r0 >= 0.5 ? "!" : "✗"} %${Math.round(r0 * 100)}</span></td></tr>`; }).join("")}</tbody></table>
        </section>
      </div>`;
  }

  // Finansallar
  const IS_ROWS = [["revenue", "Satışlar"], ["gross", "Brüt kar"], ["op_profit", "Esas faaliyet karı"], ["ebitda", "FAVÖK"], ["monetary", "Net parasal pozisyon K/Z"], ["net_parent", "Net dönem karı (ana ortaklık)"]];
  const BS_ROWS = [["current_assets", "Dönen varlıklar"], ["noncurrent_assets", "Duran varlıklar"], ["total_assets", "Toplam varlıklar"], ["fin_debt", "Finansal borçlar"], ["net_debt", "Net borç"], ["equity_parent", "Özkaynaklar (ana ortaklık)"]];
  const FIN_ROWS = {
    banka: {
      is: [["int_inc", "Faiz gelirleri"], ["int_exp", "Faiz giderleri"], ["nii", "Net faiz geliri"], ["fees", "Net ücret ve komisyon"], ["revenue", "Faaliyet brüt karı"], ["ecl", "Beklenen zarar karşılıkları"], ["opex", "Faaliyet giderleri (personel + diğer)"], ["net_parent", "Net dönem karı (ana ortaklık)"]],
      bs: [["loans", "Krediler"], ["total_assets", "Toplam varlıklar"], ["deposits", "Mevduat"], ["borrowings", "Alınan krediler"], ["securities_issued", "İhraç edilen menkul kıymetler"], ["equity_parent", "Özkaynaklar (ana ortaklık)"]],
      charts: [["revenue", "Faaliyet geliri"], ["nii", "Net faiz geliri"], ["net_parent", "Net kar"]],
      g: [["loans", "Krediler", "bs"], ["deposits", "Mevduat", "bs"], ["equity_parent", "Özkaynaklar", "bs"]],
      src: [["Mevduat", "deposits"], ["Alınan krediler + ihraçlar", ["borrowings", "securities_issued", "money_market", "subordinated"]], ["Özkaynaklar", "equity_total"]],
    },
    sigorta: {
      is: [["revenue", "Brüt yazılan primler"], ["ceded", "Reasüröre devredilen"], ["net_earned", "Kazanılmış primler (net)"], ["claims", "Gerçekleşen tazminatlar (net)"], ["opex", "Faaliyet giderleri"], ["tech_balance", "Genel teknik bölüm dengesi"], ["inv_inc", "Yatırım gelirleri"], ["net_parent", "Net dönem karı (ana ortaklık)"]],
      bs: [["cash", "Nakit ve benzerleri"], ["fin_assets", "Finansal varlıklar"], ["total_assets", "Toplam varlıklar"], ["tech_reserves", "Teknik karşılıklar"], ["equity_parent", "Özsermaye (ana ortaklık)"]],
      charts: [["revenue", "Brüt prim"], ["tech_balance", "Teknik denge"], ["net_parent", "Net kar"]],
      g: [["total_assets", "Toplam varlıklar", "bs"], ["tech_reserves", "Teknik karşılıklar", "bs"], ["equity_parent", "Özsermaye", "bs"]],
      src: [["Teknik karşılıklar", "tech_reserves"], ["Özsermaye", "equity_total"]],
    },
  };
  function tabFin(d) {
    const tmpl = tplOf(d), FR = FIN_ROWS[tmpl];
    const se = d.series, m = d.metrics, n = se.periods.length, i = n - 1;
    const ya = se.periods.indexOf(`${+se.periods[i].slice(0, 4) - 1}/${se.periods[i].slice(5)}`);
    const pq = i - 1;
    const fr = j => j >= 0 ? realF(se, j) : 1;
    const chg = (a, b) => a == null || b == null || b === 0 ? "—" : `<span class="${a / b - 1 >= 0 ? "up" : "down"}">${pctS(a / b - 1, 0)}</span>`;
    // Kümülatif gelir tablosu: cari ve önceki yıl aynı dönem (raporun kendi karşılaştırmalı sütunu, aynı birim)
    const isRows = (FR?.is || IS_ROWS).map(([k, l]) => { const a = se.cum[k]?.[i], b = se.cum_prev[k]?.[i];
      return `<tr><th scope="row">${l}</th><td class="num">${bin(a == null ? null : a * fr(i))}</td><td class="num">${bin(b == null ? null : b * fr(i))}</td><td class="num">${chg(a, b != null && b < 0 && a != null && a > 0 ? null : b)}</td></tr>`; }).join("");
    const bsRows = (FR?.bs || BS_ROWS).map(([k, l]) => { const a = se.bs[k]?.[i], b = pq >= 0 ? se.bs[k]?.[pq] : null, c = ya >= 0 ? se.bs[k]?.[ya] : null;
      const ar = a == null ? null : a * fr(i), br = b == null ? null : b * fr(pq), cr = c == null ? null : c * fr(ya);
      return `<tr><th scope="row">${l}</th><td class="num">${bin(ar)}</td><td class="num">${bin(br)}</td><td class="num">${chg(ar, br)}</td><td class="num">${bin(cr)}</td><td class="num">${chg(ar, cr)}</td></tr>`; }).join("");
    const v = m.valuation, sm = m.sector_median || {};
    const mult = tmpl === "sanayi"
      ? [["F/K", v.pe, sm.pe], ["FD/FAVÖK", v.ev_ebitda, sm.ev_ebitda], ["PD/DD", v.pb, sm.pb], ["FD/Satış", v.ev_sales, sm.ev_sales], ["PEG", v.peg, null], ["Net borç/FAVÖK", m.ratios.net_debt_ebitda, null]]
      : [["F/K", v.pe, sm.pe], ["PD/DD", v.pb, sm.pb], ["PEG", v.peg, null], ["Kazanç getirisi", v.earnings_yield, null, pct], ["Temettü verimi (12A)", v.div_yield, null, pct]];
    return `
      <div class="toolbar fa-sec"><div class="seg" role="radiogroup" aria-label="Çeyrek sayısı">${[4, 5, 8, 12].map(k => `<button type="button" role="radio" data-nq="${k}" aria-checked="${S.nq === k}">${k} çeyrek</button>`).join("")}</div>
        <span class="grow"></span><span class="card-meta">bin ₺ · ${amountsLabel(se)}</span></div>
      <div class="fa-two">
        <section class="card"><div class="card-head"><h2 class="card-title">Özet gelir tablosu</h2><span class="card-meta">dönemsel (yılbaşından)</span></div>
          <div class="tbl-scroll"><table class="tx fa-tx"><thead><tr><th>Kalem</th><th class="num">${se.periods[i]}</th><th class="num">${+se.periods[i].slice(0, 4) - 1}/${se.periods[i].slice(5)}</th><th class="num">% Y/Y</th></tr></thead><tbody>${isRows}</tbody></table></div></section>
        <section class="card"><div class="card-head"><h2 class="card-title">Özet bilanço</h2></div>
          <div class="tbl-scroll"><table class="tx fa-tx"><thead><tr><th>Kalem</th><th class="num">${se.periods[i]}</th><th class="num">${pq >= 0 ? se.periods[pq] : "—"}</th><th class="num">%</th><th class="num">${ya >= 0 ? se.periods[ya] : "—"}</th><th class="num">% Y/Y</th></tr></thead><tbody>${bsRows}</tbody></table></div></section>
      </div>
      <div class="fa-three">
        ${(FR?.charts || [["revenue", "Satışlar"], ["ebitda", "FAVÖK"], ["net_parent", "Net kar"]]).map(([k, l]) => `<section class="card"><div class="card-head"><h2 class="card-title">${S.chartMode === "q" ? "Çeyreklik" : "Son 12 ay"} ${l.toLocaleLowerCase("tr")}</h2>
          <div class="seg" role="radiogroup">${[["q", "Çeyreklik"], ["ttm", "12A"]].map(([mk, ml]) => `<button type="button" role="radio" data-cm="${mk}" aria-checked="${S.chartMode === mk}">${ml}</button>`).join("")}</div></div>
          <div class="fa-q" data-k="${k}"></div></section>`).join("")}
      </div>
      <div class="fa-two">
        <section class="card"><div class="card-head"><h2 class="card-title">Çarpanlar</h2><span class="card-meta">sektör medyanı: ${esc(rowOf(d.code)?.sector || "—")}</span></div>
          <table class="tx fa-tx"><thead><tr><th>Çarpan</th><th class="num">${d.code}</th><th class="num">Sektör med.</th></tr></thead>
          <tbody>${mult.map(([l, a, b, f = x]) => `<tr><th scope="row">${l}</th><td class="num"><b>${f(a)}</b></td><td class="num muted">${b == null ? "—" : f(b)}</td></tr>`).join("")}</tbody></table></section>
        <section class="card"><div class="card-head"><h2 class="card-title">Kaynak dağılımı</h2><span class="card-meta">${se.periods[i]}</span></div>${sourceBar(se, i, FR?.src)}
          <p class="card-foot">Kaynak: KAP finansal rapor bildirimleri (${d.reports?.[m.period]?.consolidated ? "konsolide" : "solo"}). ${tmpl === "sanayi" ? "Son 4. çeyrek = yıllık − 9 aylık (TÜFE ile aynı birime taşınarak)." : "Banka ve sigorta tabloları TMS 29 uygulanmadan, nominal yayımlanır; 4. çeyrek = yıllık − 9 aylık."}</p></section>
      </div>`;
  }
  function sourceBar(se, i, spec) {
    const ta = se.bs.total_assets?.[i], eq = se.bs.equity_total?.[i], cl = se.bs.current_liab?.[i], nl = se.bs.noncurrent_liab?.[i];
    if (!ta) return "<p class='tp-empty'>Veri yok</p>";
    const COLS = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)"];
    const val = k => Array.isArray(k) ? k.reduce((a, kk) => a + (se.bs[kk]?.[i] || 0), 0) : se.bs[k]?.[i];
    let parts = spec ? spec.map(([l, k], j) => [l, val(k), COLS[j]]) : [["Özkaynaklar", eq, "var(--series-1)"], ["KV yükümlülükler", cl, "var(--series-2)"], ["UV yükümlülükler", nl, "var(--series-3)"]];
    if (spec) { const rest = ta - parts.reduce((a, p) => a + (p[1] || 0), 0); if (rest > 0) parts.push(["Diğer yükümlülükler", rest, "var(--series-other)"]); }
    return `<div class="fa-stack">${parts.map(([l, v, c]) => v > 0 ? `<i style="width:${v / ta * 100}%;background:${c}" data-tip="${l}: ${pct(v / ta)}"></i>` : "").join("")}</div>
      <div class="chart-legend">${parts.map(([l, v, c]) => `<span><i style="background:${c}"></i>${l} ${pct(v / ta, 0)}</span>`).join("")}</div>`;
  }
  function bindFin(body, d) {
    const se = d.series;
    $$("[data-nq]", body).forEach(b => b.onclick = () => { S.nq = +b.dataset.nq; renderCompany(); });
    $$("[data-cm]", body).forEach(b => b.onclick = () => { S.chartMode = b.dataset.cm; renderCompany(); });
    $$(".fa-q", body).forEach(box => {
      const k = box.dataset.k, src = S.chartMode === "q" ? se.q : se.ttm;
      const idx = se.periods.map((_, j) => j).slice(-S.nq);
      box.innerHTML = barChart(idx.map(j => qlabel(se.periods[j])), idx.map(j => src[k]?.[j] == null ? null : src[k][j] * realF(se, j)), { w: cw(box) });
    });
  }

  // Grafikler: oran eğilimleri
  const TREND = ["roe", "roa", "net_margin", "ebitda_margin", "gross_margin", "current", "net_debt_ebitda", "debt_equity", "rev_growth", "net_growth", "asset_growth", "cfo_ni", "asset_turnover"];
  const trendKeys = d => { const t = tplOf(d); return t === "sanayi" ? TREND : Object.keys(d.metrics.history).filter(k => k !== "periods"); };
  function tabCharts(d) {
    const h = d.metrics.history, FR = FIN_ROWS[tplOf(d)], TK = trendKeys(d);
    if (!TK.includes(S.trend)) S.trend = TK[0];
    return `<section class="card"><div class="card-head"><h2 class="card-title">Oran eğilimi</h2>
        <select id="faTrend" class="fa-select" aria-label="Oran">${TK.map(k => `<option value="${k}" ${S.trend === k ? "selected" : ""}>${MET[k][0]}</option>`).join("")}</select></div>
        <div id="faTrendC"></div><p class="card-foot">Her dönem son 12 ay akışları ve dönem sonu bilançosuyla hesaplanır; büyüme oranları reeldir.</p></section>
      <div class="fa-three">${(FR?.g || [["total_assets", "Toplam varlıklar", "bs"], ["equity_parent", "Özkaynaklar", "bs"], ["cfo", "İşletme nakit akışı (12A)", "ttm"]]).map(([k, l, g]) =>
        `<section class="card"><div class="card-head"><h2 class="card-title">${l}</h2><span class="card-meta">${amountsLabel(d.series)}</span></div><div class="fa-g" data-k="${k}" data-g="${g}"></div></section>`).join("")}</div>`;
  }
  function bindCharts(body, d) {
    const h = d.metrics.history, se = d.series;
    const draw = () => { const k = S.trend, f = MET[k][1];
      $("#faTrendC").innerHTML = lineChart(h.periods.map(qlabel), [{ name: MET[k][0], vals: h[k] }], { kind: f === pct || f === pctS ? "pct" : "x", tipFmt: f, w: cw($("#faTrendC")) }); };
    $("#faTrend").onchange = e => { S.trend = e.target.value; draw(); };
    draw();
    $$(".fa-g", body).forEach(b => { const src = se[b.dataset.g][b.dataset.k] || [];
      b.innerHTML = barChart(se.periods.map(qlabel).slice(-8), src.map((v, j) => v == null ? null : v * realF(se, j)).slice(-8), { w: cw(b) }); });
  }

  // Detaylı analiz: tüm oranlar + kriter ayrıntısı
  function tabDetail(d) {
    const m = d.metrics, groups = {};
    (MET_T[tplOf(d)] || MET_T.sanayi).forEach(k => { const [l, f, , g] = MET[k]; (groups[g] ||= []).push([l, f(mOf(m, k))]); });
    return `<div class="fa-two">
      <section class="card"><div class="card-head"><h2 class="card-title">Tüm oranlar</h2><span class="card-meta">${m.period} · son 12 ay</span></div>
        ${Object.entries(groups).map(([g, xs]) => `<p class="d-sub">${g}</p><table class="fa-kv"><tbody>${xs.map(([l, v]) => `<tr><th scope="row">${l}</th><td class="num">${v}</td></tr>`).join("")}</tbody></table>`).join("")}</section>
      <section class="card"><div class="card-head"><h2 class="card-title">Kriter setleri</h2></div>
        ${Object.entries(m.criteria).map(([k, c]) => `<details class="fa-crit"><summary><b>${esc(k)}</b> <span class="mono">${c.pass}/${c.total}</span></summary>
          <ul class="fa-list">${c.items.map(([l, ok]) => `<li class="${ok == null ? "na" : ok ? "ok" : "no"}">${esc(l)}</li>`).join("")}</ul></details>`).join("")}
        <div id="faDivHist"></div>
        <p class="card-foot">✓ sağlandı · ✗ sağlanmadı · — veri yok. Eşikler <a href="#metodoloji">Metodoloji</a> sayfasında; uzun geçmiş gerektiren kriterler mevcut yıllık dönemlerle sınanır.</p></section></div>`;
  }

  async function divHistory(code) {
    let all;
    try { all = S.divs ||= await getJSON("data/fin/_dividends.json"); } catch { return; }
    const xs = all[code] || [], box = $("#faDivHist");
    if (!box || !xs.length) return;
    const ST = { kesin: "kesin", "öneri": "öneri", yok: "dağıtım yok" };
    box.innerHTML = `<div class="card-head fa-sec"><h3 class="card-title">Kar payı kararları (KAP)</h3></div>
      <table class="tx fa-tx"><thead><tr><th>Karar</th><th>Durum</th><th class="num">Brüt</th><th class="num">Net</th><th class="num">Dağıtım %</th><th>Hak kullanım</th></tr></thead>
      <tbody>${xs.slice(0, 10).map(x => `<tr><td><a href="https://www.kap.org.tr/tr/Bildirim/${x.idx}" target="_blank" rel="noopener">${esc(x.decision || "—")}</a></td><td>${esc(ST[x.status] || x.status || "")}</td>
        <td class="num">${x.gross ? fmt.num(x.gross, 4) : "—"}</td><td class="num">${x.net ? fmt.num(x.net, 4) : "—"}</td><td class="num">${x.payout != null ? fmt.num(x.payout, 1) : "—"}</td>
        <td>${(x.installments || []).map(i => esc(i.ex || "")).join(", ") || "—"}</td></tr>`).join("")}</tbody></table>`;
  }

  // ───────────── tarama
  const OPS = { ">=": (a, b) => a >= b, "<=": (a, b) => a <= b };
  const PCTK = k => MET[k] && (MET[k][1] === pct || MET[k][1] === pctS);
  function renderScreen() {
    const el = $("#view-tarama");
    if (notReady(el)) return;
    const labels = S.screen.criteria_labels || {};
    const sets = Object.keys(labels);
    if (!sets.includes(S.crit)) S.crit = sets[0];
    const all = rows().filter(r => !S.scrSector || (r.sector || "Diğer") === S.scrSector);
    const sectors = [...new Set(rows().map(r => r.sector || "Diğer"))].sort((a, b) => a.localeCompare(b, "tr"));
    const tabsH = `<div class="seg fa-tabs" role="tablist"><button type="button" role="tab" data-st="metrik" aria-checked="${S.scrTab === "metrik"}">Metrik taraması</button><button type="button" role="tab" data-st="kriter" aria-checked="${S.scrTab === "kriter"}">Kriter taraması (sağlandı / sağlanmadı)</button></div>`;
    const secSel = `<select id="faScrSec" class="fa-select" aria-label="Sektör"><option value="">Tüm sektörler</option>${sectors.map(s => `<option ${s === S.scrSector ? "selected" : ""}>${esc(s)}</option>`).join("")}</select>`;
    let body;
    if (S.scrTab === "kriter") {
      const lbl = labels[S.crit] || [];
      let xs = all.map(r => ({ r, c: r.crit?.[S.crit] })).filter(o => o.c);
      if (S.allPass) xs = xs.filter(o => o.c[0] === o.c[1]);
      xs.sort((a, b) => b.c[0] / b.c[1] - a.c[0] / a.c[1] || (b.r.overall ?? 0) - (a.r.overall ?? 0));
      body = `<section class="card"><div class="fa-two fa-crit-head"><div><h2 class="card-title">Kriter seti</h2>
          <div class="chips">${sets.map(s => `<button type="button" class="chip" data-set="${esc(s)}" aria-pressed="${s === S.crit}">${esc(s)} <span class="n">${labels[s].length}</span></button>`).join("")}</div>
          <label class="fa-check"><input type="checkbox" id="faAllPass" ${S.allPass ? "checked" : ""}> Yalnızca tüm kriterleri sağlayanlar</label></div>
          <div><h2 class="card-title">Kapsam</h2>${secSel}<p class="card-meta">${all.length} hisse taranır</p></div></div></section>
        <section class="card card-flush"><div class="card-head"><h2 class="card-title">${xs.length} hisse · uyum oranına göre sıralı</h2><span class="card-meta">✓ sağlandı · ✗ sağlanmadı · — veri yok</span></div>
          <div class="tbl-scroll"><table class="tbl fa-tbl"><thead><tr><th>Hisse</th><th class="num">Uyum</th>${lbl.map((l, i) => `<th class="num" data-tip="${esc(l)}">${i + 1}</th>`).join("")}</tr></thead>
          <tbody>${xs.map(({ r, c }) => `<tr class="row" tabindex="0" data-code="${r.code}"><td><b class="mono">${r.code}</b> <span class="muted fa-name">${esc(r.sector || "")}</span></td>
            <td class="num"><b>${c[0]}/${c[1]}</b> <small class="muted">%${Math.round(c[0] / c[1] * 100)}</small></td>
            ${c[3].map(v => `<td class="num ${v == null ? "muted" : v ? "up" : "down"}">${v == null ? "—" : v ? "✓" : "✗"}</td>`).join("")}</tr>`).join("") || `<tr><td colspan="${lbl.length + 2}">${sh.stateHTML({ title: "Tüm kriterleri sağlayan hisse yok", msg: "Filtreyi gevşetmek için kutunun işaretini kaldır.", compact: true })}</td></tr>`}</tbody></table></div>
          <div class="card-foot fa-legend-crit"><b>Kriterler</b><ol>${lbl.map(l => `<li>${esc(l)}</li>`).join("")}</ol></div></section>`;
    } else {
      const xs = all.filter(r => S.filters.every(([k, op, v]) => { const a = mval(r, k); return a != null && OPS[op](a, v); }));
      const keys = [...new Set(S.filters.map(f => f[0]))];
      body = `<section class="card"><div class="card-head"><h2 class="card-title">Filtreler</h2>${secSel}</div>
          <div class="fa-filters">${S.filters.map(([k, op, v], i) => `<div class="fa-f" data-i="${i}">
            <select class="fa-select" data-f="k">${Object.entries(MET).map(([mk, [l]]) => `<option value="${mk}" ${mk === k ? "selected" : ""}>${l}</option>`).join("")}</select>
            <select class="fa-select" data-f="op"><option ${op === ">=" ? "selected" : ""}>&gt;=</option><option ${op === "<=" ? "selected" : ""}>&lt;=</option></select>
            <input class="fa-num" data-f="v" type="number" step="any" value="${PCTK(k) ? +(v * 100).toFixed(4) : v}" aria-label="Eşik">${PCTK(k) ? "<span class='muted'>%</span>" : ""}
            <button type="button" class="btn btn-icon" data-f="rm" aria-label="Filtreyi kaldır">×</button></div>`).join("")}
            <button type="button" class="link-btn" id="faAddF">+ Filtre ekle</button></div></section>
        <section class="card card-flush"><div class="card-head"><h2 class="card-title">${xs.length} hisse</h2><span class="card-meta">genel skora göre</span></div>
          <div class="tbl-scroll"><table class="tbl fa-tbl"><thead><tr><th>Hisse</th>${keys.map(k => `<th class="num">${MET[k][0]}</th>`).join("")}<th class="num">Genel</th></tr></thead>
          <tbody>${xs.sort((a, b) => (b.overall ?? -1) - (a.overall ?? -1)).map(r => `<tr class="row" tabindex="0" data-code="${r.code}"><td><b class="mono">${r.code}</b> <span class="muted fa-name">${esc(trTitle(r.title))}</span></td>
            ${keys.map(k => `<td class="num">${MET[k][1](mval(r, k))}</td>`).join("")}<td class="num">${r.overall ?? "—"} ${gradeTag(r.grade)}</td></tr>`).join("") || `<tr><td colspan="${keys.length + 2}">${sh.stateHTML({ title: "Eşleşen hisse yok", compact: true })}</td></tr>`}</tbody></table></div></section>`;
    }
    el.innerHTML = tabsH + body;
    $$("[data-st]", el).forEach(b => b.onclick = () => { S.scrTab = b.dataset.st; renderScreen(); });
    $$("[data-set]", el).forEach(b => b.onclick = () => { S.crit = b.dataset.set; renderScreen(); });
    $("#faAllPass") && ($("#faAllPass").onchange = e => { S.allPass = e.target.checked; renderScreen(); });
    $("#faScrSec").onchange = e => { S.scrSector = e.target.value; renderScreen(); };
    const saveF = () => { store.set("radar.finFilters", S.filters); renderScreen(); };
    $$(".fa-f", el).forEach(f => {
      const i = +f.dataset.i;
      $("[data-f=k]", f).onchange = e => { S.filters[i] = [e.target.value, S.filters[i][1], S.filters[i][2]]; saveF(); };
      $("[data-f=op]", f).onchange = e => { S.filters[i][1] = e.target.value; saveF(); };
      $("[data-f=v]", f).onchange = e => { const k = S.filters[i][0]; const n = parseFloat(e.target.value); if (isFinite(n)) { S.filters[i][2] = PCTK(k) ? n / 100 : n; saveF(); } };
      $("[data-f=rm]", f).onclick = () => { S.filters.splice(i, 1); saveF(); };
    });
    $("#faAddF") && ($("#faAddF").onclick = () => { S.filters.push(["net_debt_ebitda", "<=", 2]); saveF(); });
    bindRows(el);
  }

  // ───────────── karşılaştır
  async function renderCompare() {
    const el = $("#view-karsilastir");
    if (notReady(el)) return;
    const fromHash = (sh.param || "").split(",").map(s => s.trim().toUpperCase()).filter(Boolean);
    if (fromHash.length) { S.cmp = fromHash.slice(0, 5); store.set("radar.finCmp", S.cmp); }
    const codes = S.cmp.filter(c => rowOf(c));
    const pick = `<section class="card"><div class="toolbar"><span class="chip-label">Karşılaştırılan</span><div class="chips">${codes.map(c => `<button type="button" class="chip" data-rm="${c}" aria-pressed="true">${c} <span aria-hidden="true">×</span></button>`).join("")}</div>
      ${codes.length < 5 ? `<select id="faCmpPick" class="fa-select" aria-label="Şirket ekle"><option value="">+ Şirket ekle</option>${rows().filter(r => !codes.includes(r.code)).sort((a, b) => a.code.localeCompare(b.code)).map(r => `<option value="${r.code}">${r.code} · ${esc(trTitle(r.title))}</option>`).join("")}</select>` : ""}</div></section>`;
    if (codes.length < 2) {
      el.innerHTML = pick + `<div class="card">${sh.stateHTML({ title: "En az iki şirket seç", msg: "Şirket sayfasındaki “Karşılaştırmaya ekle” düğmesini ya da yukarıdaki listeyi kullan (en fazla 5)." })}</div>`;
      bindCmp(el); return;
    }
    el.innerHTML = pick + `<div class="card"><div class="skeleton sk-block" style="height:200px"></div></div>`;
    bindCmp(el);
    const docs = await Promise.all(codes.map(c => doc(c).catch(() => null)));
    if (sh.route !== "karsilastir") return;
    const ok = codes.map((c, i) => ({ c, d: docs[i], r: rowOf(c) })).filter(o => o.d?.metrics);
    const tpls = [...new Set(ok.map(o => tplOf(o.d)))], mixed = tpls.length > 1;
    const radarSet = ok.filter(o => tplOf(o.d) === tplOf(ok[0].d));
    const cats = Object.keys(ok[0].d.metrics.categories);
    const R = o => o.d.metrics.ratios;
    const KEYS = tpls.length === 1 && tpls[0] === "banka" ? [["Kalite puanı", o => o.d.metrics.quality, 1, v => `${v}/100`], ["Karlılık (ROE)", o => R(o).roe, 1, pct],
      ["Net faiz marjı", o => R(o).nim, 1, v => pct(v, 2)], ["Maliyet / gelir", o => R(o).cost_income, -1, pct], ["Risk maliyeti", o => R(o).cost_of_risk, -1, v => pct(v, 2)],
      ["Kredi / mevduat", o => R(o).ldr, -1, pct], ["Özkaynak / aktif", o => R(o).equity_assets, 1, pct], ["Reel kredi büyümesi", o => R(o).loan_growth, 1, pctS],
      ["Ucuzluk (F/K)", o => o.d.metrics.valuation.pe, -1, x], ["Ucuzluk (PD/DD)", o => o.d.metrics.valuation.pb, -1, x]]
    : tpls.length === 1 && tpls[0] === "sigorta" ? [["Kalite puanı", o => o.d.metrics.quality, 1, v => `${v}/100`], ["Karlılık (ROE)", o => R(o).roe, 1, pct],
      ["Birleşik oran", o => R(o).combined, -1, pct], ["Hasar oranı", o => R(o).loss_ratio, -1, pct], ["Reel prim büyümesi", o => R(o).premium_growth, 1, pctS],
      ["Özsermaye / aktif", o => R(o).equity_assets, 1, pct], ["Ucuzluk (F/K)", o => o.d.metrics.valuation.pe, -1, x], ["Ucuzluk (PD/DD)", o => o.d.metrics.valuation.pb, -1, x]]
    : [["Bilanço kalitesi", o => o.d.metrics.quality, 1, v => `${v}/100`], ["Karlılık (ROE)", o => o.d.metrics.ratios.roe, 1, pct],
      ["Reel büyüme", o => o.d.metrics.ratios.rev_growth, 1, pctS], ["Borçluluk (net borç / FAVÖK)", o => o.d.metrics.ratios.net_debt_ebitda, -1, x],
      ["Kar kalitesi (işletme nakdi / kar)", o => o.d.metrics.ratios.cfo_ni, 1, x], ["Likidite (cari oran)", o => o.d.metrics.ratios.current, 1, x],
      ["Ucuzluk (F/K)", o => o.d.metrics.valuation.pe, -1, x], ["Ucuzluk (FD/FAVÖK)", o => o.d.metrics.valuation.ev_ebitda, -1, x]];
    const assess = KEYS.map(([l, f, dir, fm]) => { const vs = ok.map(o => [o.c, f(o)]).filter(([, v]) => v != null);
      if (vs.length < 2) return ""; vs.sort((a, b) => (b[1] - a[1]) * dir);
      return `<li><b>${l}:</b> en iyi ${vs[0][0]} (${fm(vs[0][1])}), en zayıf ${vs[vs.length - 1][0]} (${fm(vs[vs.length - 1][1])}).</li>`; }).join("");
    const rank = [...ok].sort((a, b) => (b.d.metrics.overall ?? 0) - (a.d.metrics.overall ?? 0)).map(o => `${o.c} (${o.d.metrics.overall ?? "—"} · ${o.d.metrics.grade || "—"})`).join(" › ");
    const allP = [...new Set(ok.flatMap(o => o.d.metrics.history.periods))].sort();
    const metKeys = [...new Set(tpls.flatMap(t => MET_T[t] || []))];
    const tbl = metKeys.map(k => [k, MET[k]]).map(([k, [l, f, dir, g]]) => {
      const vs = ok.map(o => mOf(o.d.metrics, k));
      const valid = vs.filter(v => v != null);
      const best = valid.length > 1 && new Set(valid).size > 1 ? (dir > 0 ? Math.max(...valid) : Math.min(...valid)) : null;
      return [g, `<tr><th scope="row">${l}</th>${vs.map(v => { const b = best != null && v === best; return `<td class="num ${b ? "fa-best" : ""}">${f(v)}${b ? " <span class='up' aria-label='en iyi'>●</span>" : ""}</td>`; }).join("")}</tr>`];
    });
    let lastG = "";
    el.innerHTML = pick + `
      <div class="fa-two">
        <section class="card"><div class="card-head"><h2 class="card-title">Kategori puanları</h2><span class="card-meta">${TPL[tplOf(ok[0].d)]} modeli kategorileri (0–100)</span></div>
          ${mixed ? `<p class="tp-warn">Farklı modeller karşılaştırılıyor (${tpls.map(t => TPL[t]).join(", ")}); kategori grafiği yalnız ${TPL[tplOf(ok[0].d)].toLocaleLowerCase("tr")} şirketlerini gösterir, oran tablosunda boş hücreler o modelde olmayan oranlardır.</p>` : ""}
          ${radarChart(cats, radarSet.map(o => ({ name: o.c, vals: cats.map(c => o.d.metrics.categories[c]) })))}
          <details class="fa-crit"><summary>Tablo görünümü</summary><table class="tx fa-tx"><thead><tr><th>Kategori</th>${radarSet.map(o => `<th class="num">${o.c}</th>`).join("")}</tr></thead>
          <tbody>${cats.map(c => `<tr><th scope="row">${c}</th>${radarSet.map(o => `<td class="num">${o.d.metrics.categories[c] ?? "—"}</td>`).join("")}</tr>`).join("")}</tbody></table></details></section>
        <section class="card"><div class="card-head"><h2 class="card-title">Karşılaştırmalı değerlendirme</h2></div>
          <ul class="fa-assess">${assess}<li>Genel skora göre sıralama: ${rank}.</li></ul></section>
      </div>
      <section class="card"><div class="card-head"><h2 class="card-title">Metrik eğilimi</h2>
        <select id="faCmpM" class="fa-select" aria-label="Metrik">${[...new Set(ok.flatMap(o => trendKeys(o.d)))].map(k => `<option value="${k}" ${S.cmpMetric === k ? "selected" : ""}>${MET[k][0]}</option>`).join("")}</select></div>
        <div id="faCmpChart"></div></section>
      <section class="card card-flush"><div class="card-head"><h2 class="card-title">Tüm oranlar</h2><span class="card-meta">${metKeys.length} oran · ● satırdaki en iyi değer</span></div>
        <div class="tbl-scroll"><table class="tbl fa-tbl"><thead><tr><th>Oran</th>${ok.map(o => `<th class="num"><button type="button" class="tk-cmp link-btn" data-code="${o.c}">${o.c}</button></th>`).join("")}</tr></thead>
        <tbody>${tbl.map(([g, h]) => { const head = g !== lastG ? `<tr class="fa-grp"><td colspan="${ok.length + 1}">${g}</td></tr>` : ""; lastG = g; return head + h; }).join("")}</tbody></table></div></section>`;
    bindCmp(el);
    const cmpKeys = [...new Set(ok.flatMap(o => trendKeys(o.d)))];
    if (!cmpKeys.includes(S.cmpMetric)) { S.cmpMetric = cmpKeys[0]; $("#faCmpM").value = S.cmpMetric; }
    const draw = () => { const k = S.cmpMetric, f = MET[k][1];
      $("#faCmpChart").innerHTML = lineChart(allP.map(qlabel), ok.map(o => ({ name: o.c, vals: allP.map(p => { const j = o.d.metrics.history.periods.indexOf(p); return j >= 0 ? o.d.metrics.history[k]?.[j] : null; }) })), { kind: f === pct || f === pctS ? "pct" : "x", tipFmt: f, w: cw($("#faCmpChart")) }); };
    $("#faCmpM").onchange = e => { S.cmpMetric = e.target.value; draw(); };
    draw();
    $$(".tk-cmp", el).forEach(b => b.onclick = () => sh.go("hisse", { param: b.dataset.code }));
  }
  function bindCmp(el) {
    $$("[data-rm]", el).forEach(b => b.onclick = () => { S.cmp = S.cmp.filter(c => c !== b.dataset.rm); store.set("radar.finCmp", S.cmp); sh.go("karsilastir", { param: S.cmp.join(","), push: false }); renderCompare(); });
    $("#faCmpPick") && ($("#faCmpPick").onchange = e => { if (!e.target.value) return; S.cmp = [...S.cmp.filter(c => rowOf(c)), e.target.value].slice(0, 5); store.set("radar.finCmp", S.cmp); sh.go("karsilastir", { param: S.cmp.join(","), push: false }); renderCompare(); });
  }


  // ───────────── metodoloji
  function renderMethod() {
    const el = $("#view-metodoloji");
    const cat = [
      ["Karlılık", "ROE %0→%30, ROA %0→%12, net marj %0→%20, FAVÖK marjı %0→%30, brüt marj %5→%45"],
      ["Reel Büyüme", "12A satış −%10→+%20, FAVÖK −%20→+%25, net kar −%30→+%30 (bir yıl önceye göre, TÜFE ile)"],
      ["Finansal Yapı", "Net borç/FAVÖK 4→0 (net nakit = en iyi), finansal borç/özkaynak 1,5→0,2, FAVÖK/finansman gideri 1→8, yükümlülük/varlık %80→%30"],
      ["Likidite", "Cari oran 0,8→2, asit-test 0,5→1,5, nakit oranı 0,1→0,8"],
      ["Nakit Akışı & Kar Kalitesi", "İşletme nakdi/net kar 0→1,2, serbest nakit akışı marjı −%5→+%12, tahakkuk oranı %10→−%5"],
      ["Verimlilik", "Aktif devir hızı 0,2→1,5, nakit dönüşüm süresi 180→30 gün, ROIC %0→%25"],
    ];
    el.innerHTML = `<div class="fa-two">
      <section class="card fa-method"><h2 class="card-title">Veri</h2>
        <ul>
          <li><b>Mali tablolar:</b> KAP'taki "Finansal Rapor" bildirimleri (bilanço, kar/zarar, nakit akış). Aynı dönemde konsolide ve solo rapor varsa konsolide kullanılır; düzeltme bildirimi gelirse dönem yeniden okunur.</li>
          <li><b>Kapsam:</b> BIST-100. Bankalar, sigorta ve finansal kiralama şirketlerinin tablo şablonu farklı olduğu için şimdilik kapsam dışı.</li>
          <li><b>Enflasyon:</b> TCMB EVDS, TÜİK TÜFE genel endeksi (2003=100, <span class="mono">TP.GENENDEKS.T1</span>) — TMS 29 düzeltmesinde kullanılan seri.</li>
          <li><b>Fiyat ve sektör:</b> Son kapanış Yahoo Finance'ten (saatlik); sektör KAP sınıflamasından. Pay sayısı = ödenmiş sermaye (pay başına 1 TL nominal).</li>
          <li><b>Güncelleme:</b> Yeni bildirimler saatlik taranır. KAP'ın istek sınırı nedeniyle 15 dakikada en fazla 9 rapor indirilir.</li>
        </ul>
        <h2 class="card-title">Birimler ve reel düzeltme</h2>
        <ul>
          <li>TMS 29 raporları her dönemi kendi dönem sonunun alım gücüyle verir. Farklı dönemleri birleştirirken tutarlar TÜFE oranıyla aynı birime taşınır.</li>
          <li><b>Çeyrek:</b> Gelir tablosunda raporun 3 aylık sütunu; 4. çeyrek = yıllık − 9 aylık × TÜFE(Ara)/TÜFE(Eyl). Nakit akışında kümülatif farkı.</li>
          <li><b>Son 12 ay (12A):</b> bu yılın kümülatifi + geçen yılın tamamı × TÜFE oranı − raporun karşılaştırmalı (geçen yıl aynı dönem) sütunu.</li>
          <li><b>Reel görünüm:</b> her dönem TÜFE(son dönem) / TÜFE(dönem sonu) ile çarpılır. Büyüme oranları her zaman reeldir.</li>
          <li><b>Ortalama bilanço:</b> ROE ve ROA'da dönem sonu ile bir yıl önceki (TÜFE ile taşınmış) bakiyenin ortalaması.</li>
        </ul>
        <h2 class="card-title">Tanımlar</h2>
        <ul>
          <li><b>FAVÖK</b> = brüt kar − genel yönetim − pazarlama − Ar-Ge giderleri + amortisman (esas faaliyetlerden diğer gelir/giderler hariç). <b>Çekirdek faaliyet karı</b> = FAVÖK − amortisman.</li>
          <li><b>Finansal borç</b> = KV borçlanmalar + UV borçlanmaların KV kısmı + UV borçlanmalar (kiralama yükümlülükleri dahil). <b>Net borç</b> = finansal borç − nakit − KV finansal yatırımlar.</li>
          <li><b>Serbest nakit akışı</b> = işletme faaliyetlerinden nakit + maddi/maddi olmayan duran varlık ve yatırım amaçlı gayrimenkul alımları.</li>
          <li><b>Firma değeri</b> = piyasa değeri + net borç + kontrol gücü olmayan paylar. Çarpanlar piyasa değeri / 12A.</li>
          <li><b>ROIC</b> = esas faaliyet karı × (1 − %25) / (özkaynak + finansal borç − nakit ve KV yatırımlar).</li>
        </ul>
      </section>
      <section class="card fa-method"><h2 class="card-title">Puanlar</h2>
        <ul>
          <li><b>Kategori puanı (0–100):</b> her oran "kötü" ile "iyi" eşiği arasında doğrusal puanlanır, kategori içinde ortalanır.</li>
        </ul>
        <table class="fa-kv fa-mkv"><tbody>${cat.map(([c, t]) => `<tr><th scope="row">${c}</th><td>${t}</td></tr>`).join("")}</tbody></table>
        <ul>
          <li><b>Bilanço (kalite) puanı:</b> altı kategorinin ortalaması.</li>
          <li><b>Değerleme puanı:</b> F/K, PD/DD, FD/FAVÖK ve FD/Satış'ın sektör medyanına oranı (yarısı = 100, eşit ≈ 67, iki katı = 0) ve içsel değer potansiyeli (−%40→+%60). Sektörde 3'ten az şirket varsa tüm evrenin medyanı.</li>
          <li><b>İçsel değer:</b> sektör medyan F/K × hisse başı kar, medyan PD/DD × hisse başı defter değeri ve medyan FD/FAVÖK'ten türetilen özkaynak değerinin ortalaması.</li>
          <li><b>Genel skor</b> = %60 kalite + %40 değerleme. Not: A ≥ 80, B ≥ 65, C ≥ 50, D ≥ 35, E altı.</li>
          <li><b>Piotroski F (0–9):</b> ROA > 0, işletme nakdi > 0, ROA arttı, nakit > net kar, UV borç/varlık azaldı, cari oran arttı, sermaye artırımı yok, brüt marj arttı, aktif devir hızı arttı (bir yıl öncesine göre).</li>
          <li><b>Altman Z'':</b> 6,56·(net işletme sermayesi/varlık) + 3,26·(birikmiş karlar/varlık) + 6,72·(esas faaliyet karı/varlık) + 1,05·(özkaynak/yükümlülük). > 2,6 güvenli, 1,1–2,6 gri, < 1,1 riskli.</li>
          <li><b>Beneish M:</b> 8 değişkenli model; −1,78 üstü kazanç manipülasyonu riski işaretidir.</li>
          <li><b>Kriter setleri:</b> Graham, Buffett, Lynch ve Greenblatt kurallarının BIST'e ve enflasyon muhasebesine uyarlanmış hâlleri; eşikler her kriterin adında yazar. Uzun geçmiş gerektirenler mevcut yıllık dönemlerle sınanır.</li>
        </ul>
        <h2 class="card-title">Bankalar ve sigorta şirketleri</h2>
        <ul>
          <li><b>Tablolar:</b> BDDK ve SEDDK tek düzen hesap planları; bankalarda bilanço TP/YP/Toplam sütunlarıyla gelir, toplam kullanılır. Bu tablolar TMS 29 uygulanmadan, <b>nominal</b> yayımlanır: 12A ve 4. çeyrek hesabında TÜFE oranı uygulanmaz, büyümeler ve reel ROE ise TÜFE ile hesaplanır.</li>
          <li><b>Banka oranları:</b> net faiz marjı = net faiz geliri / ortalama aktif; maliyet/gelir = (personel + diğer faaliyet giderleri) / faaliyet brüt karı; risk maliyeti = beklenen zarar karşılık giderleri / ortalama krediler; kredi/mevduat; özkaynak/aktif; reel ROE = (1 + ROE) / (1 + yıllık TÜFE) − 1. Sermaye yeterlilik oranı mali tablolarda yer almadığı için kullanılmaz.</li>
          <li><b>Sigorta oranları:</b> hasar oranı = gerçekleşen tazminatlar (net) / kazanılmış primler (net); gider oranı = (faaliyet + diğer teknik giderler) / kazanılmış primler; birleşik oran = hasar + gider; saklama oranı = net / brüt yazılan prim; likit varlık / teknik karşılıklar.</li>
          <li><b>Kategoriler:</b> banka — karlılık, faiz marjı ve gelir yapısı, verimlilik, aktif kalitesi, sermaye ve fonlama, reel büyüme; sigorta — karlılık, teknik karlılık, verimlilik, sermaye, likidite, reel büyüme. Değerleme yalnız aynı modeldeki şirketlerin F/K ve PD/DD medyanlarıyla karşılaştırılır. Piotroski, Altman ve Beneish bu modellerde kullanılmaz.</li>
        </ul>
        <p class="card-foot">Bu panel bilgi amaçlıdır, yatırım tavsiyesi değildir. Kural tabanlı puanlar şirketin iş modelini, yönetimini veya geleceğe dönük beklentileri bilmez.</p>
      </section></div>`;
  }

  // ───────────── kayıt
  const csv = (name, head, data) => () => {
    const blob = new Blob(["﻿" + [head, ...data].map(r => r.map(v => `"${String(v ?? "").replace(/"/g, '""')}"`).join(";")).join("\n")], { type: "text/csv" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };
  const reg = (route, render) => sh.register(route, {
    onShow() { if (!S.loaded) load(); render(); },
    refresh: async () => { S.docs = {}; S.divs = null; await load(); },
    exports: () => route === "temel" && rows().length ? [{ label: "Şirket tablosu (CSV)", hint: "görünen sütunlar", run: csv("temel-analiz.csv",
      ["Kod", "Şirket", "Sektör", "Dönem", "Fiyat", "Piyasa değeri", "F/K", "PD/DD", "FD/FAVÖK", "ROE", "Reel satış büyümesi", "Kalite", "Değerleme", "Genel", "Not"],
      rows().map(r => [r.code, r.title, r.sector, r.period, r.price, r.mcap, r.v?.pe, r.v?.pb, r.v?.ev_ebitda, r.r?.roe, r.r?.rev_growth, r.quality, r.valuation_score, r.overall, r.grade])) }] : [],
    exportNote: "Bu görünümde dışa aktarma yok",
  });
  reg("temel", renderOverview);
  reg("hisse", renderCompany);
  reg("tarama", renderScreen);
  reg("karsilastir", renderCompare);
  sh.register("metodoloji", { onShow: renderMethod, exports: () => [], exportNote: "Metodoloji metni" });
  addEventListener("themechange", () => { if (["hisse", "karsilastir"].includes(sh.route)) rerender(); });
  window.radarFundamentals = { open: code => sh.go("hisse", { param: code }), has: code => !!rowOf(code), get rows() { return rows(); } };
  load();
})();
