/* Lyra Radar — Banka Faiz Duyarlılığı (net faiz marjının politika faizine duyarlılığı).
   Veri: data/fin/_bankrate.json (temel.yml; radar/fundamentals/bankrate.py). KAP banka tablolarından çeyreklik
   aktif getirisi (faiz gelirleri / ort. aktif) ve fonlama maliyeti (faiz giderleri / ort. aktif) çıkarılır; ikisi ayrı ayrı
   politika faizinin bu ve önceki çeyrek ortalamasına regrese edilir (bankalar arası havuz + Bayes büzme).
   1 yıllık ΔNIM = [(a0 + 0,75·a1) − (f0 + 0,75·f1)] · Δr. Senaryo kaydırıcısı tarayıcıda aynı formülle yeniden hesaplar. */
(() => {
  "use strict";
  const sh = window.shell;
  const { $, $$, esc, fmt } = sh;
  const SRC = "data/fin/_bankrate.json";
  const S = { doc: null, loaded: false, loading: false, error: null, missing: false, dr: null, sort: "y1", dir: 1, sel: null, full: false };
  let waiters = [];

  async function load(force = false) {
    if (S.loading || (S.loaded && !force)) return;
    S.loading = true; S.error = null; S.missing = false;
    if (!S.loaded && sh.route === "banka-faiz") renderLoading();
    try {
      const r = await fetch(`${SRC}?t=${Date.now()}`, { cache: "no-store" });
      if (r.status === 404) { S.missing = true; throw new Error("veri henüz üretilmedi"); }
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      S.doc = await r.json();
      if (S.dr == null) S.dr = S.doc.delta_pp ?? -5;
      if (!S.sel) S.sel = S.doc.banks?.[0]?.code || null;
      S.loaded = true;
      sh.setUpdated("banka-faiz", new Date(S.doc.generated), { label: "Hesaplandı", staleMin: 60 * 48 });
    } catch (e) { S.error = e.message || "veri okunamadı"; }
    finally { S.loading = false; }
    waiters.splice(0).forEach(f => f());
    dispatchEvent(new Event("radar:bankrate"));
    if (sh.route === "banka-faiz") S.loaded ? render() : renderError();
  }

  // ─────────────────────────────── senaryo (Python'daki scen() ile aynı)
  function scen(b, delta, y1 = b.y1, se = b.y1_se) {
    if (delta == null || !b.ta) return null;
    const dnim = y1 * delta, dnii = dnim / 100 * b.ta, dnet = dnii * (1 - b.tax_rate);
    const a = (y1 - 1.645 * se) * delta * 100, c = (y1 + 1.645 * se) * delta * 100;
    return { dnim_bp: dnim * 100, dnii, nii_pct: b.nii_ttm > 0 ? dnii / b.nii_ttm * 100 : null, net_pct: b.net_ttm > 0 ? dnet / b.net_ttm * 100 : null,
      roe_pp: b.equity ? dnet / b.equity * 100 : null, mcap_pct: b.mcap ? dnet / b.mcap * 100 : null, lo_bp: Math.min(a, c), hi_bp: Math.max(a, c) };
  }
  const bp = (v, d = 0) => v == null || !isFinite(v) ? "—" : (v > 0 ? "+" : v < 0 ? "−" : "") + fmt.num(Math.abs(v), d) + " bp";
  const cls = v => v == null ? "" : v > 0.5 ? "up" : v < -0.5 ? "down" : "flat";
  const pp = (v, d = 2) => v == null ? "—" : fmt.num(v, d);
  const bn = v => v == null ? "—" : fmt.num(v / 1e9, 1) + " mr ₺";

  // ─────────────────────────────── görünüm
  function renderLoading() {
    $("#brBody").innerHTML = `<div class="kpi-grid">${Array.from({ length: 4 }, () => `<div class="kpi"><div class="skeleton sk-line w60"></div><div class="skeleton sk-line lg w40"></div></div>`).join("")}</div>
      <div class="skeleton sk-block" style="height:320px;margin-top:16px"></div>`;
  }
  function renderError() {
    $("#brBody").innerHTML = S.missing
      ? sh.stateHTML({ kind: "info", title: "Henüz hesaplanmadı", msg: "Banka faiz duyarlılığı temel analiz iş akışının bir sonraki turunda üretilecek (EVDS anahtarı gerekir)." })
      : sh.stateHTML({ kind: "error", title: "Banka faiz duyarlılığı yüklenemedi", msg: esc(S.error), action: "Tekrar dene", actionId: "brRetry" });
    $("#brRetry")?.addEventListener("click", () => load(true));
  }

  function kpis() {
    const p = S.doc.policy, d = S.doc, pool = d.pool || {};
    const k = (label, value, sub = "", tip = "") => `<div class="kpi" ${tip ? `data-tip="${esc(tip)}"` : ""}><span class="kpi-label">${label}</span><span class="kpi-value">${value}</span>${sub ? `<span class="kpi-sub">${sub}</span>` : ""}</div>`;
    return `<div class="kpi-grid">
      ${k("Fonlama faizi (TCMB)", "%" + fmt.num(p.now, 2), fmt.date(p.date, { day: "numeric", month: "short", year: "numeric" }), "Ağırlıklı ortalama fonlama maliyeti, TP.APIFON4")}
      ${k("12 ay sonrası politika faizi beklentisi", p.expect_12m == null ? "—" : "%" + fmt.num(p.expect_12m, 2), `Piyasa Katılımcıları Anketi${p.expect_date ? " · " + esc(p.expect_date) : ""}`, "TP.PKAUO.S04.D.U")}
      ${k("Beklenen değişim", d.delta_pp == null ? "—" : `<span class="${d.delta_pp < 0 ? "down" : "up"}">${d.delta_pp > 0 ? "+" : "−"}${fmt.num(Math.abs(d.delta_pp), 2)} puan</span>`, "varsayılan senaryo")}
      ${k("Sektör (havuz) duyarlılığı", bp(-(pool.y1 ?? 0) * 100, 0), "100 bp indirimde 1 yıllık ΔNIM", "Bütün bankaların ortak katsayısı. Pozitif: faiz indirimi marjı genişletir (fonlama, getiriden hızlı ucuzlar).")}
    </div>`;
  }

  function slider() {
    const lo = -15, hi = 10, dflt = S.doc.delta_pp;
    return `<div class="card br-sc">
      <div class="card-head"><h2 class="card-title" id="brScT">Senaryo: politika faizinde 12 ayda değişim</h2>
        <span class="card-meta">${dflt != null ? `<button type="button" class="link-btn" id="brReset">Anket beklentisine dön (${dflt > 0 ? "+" : "−"}${fmt.num(Math.abs(dflt), 2)})</button>` : ""}</span></div>
      <div class="br-sl"><input type="range" id="brDr" min="${lo}" max="${hi}" step="0.25" value="${S.dr}" aria-labelledby="brScT">
        <output id="brDrOut" class="mono">${S.dr > 0 ? "+" : S.dr < 0 ? "−" : ""}${fmt.num(Math.abs(S.dr), 2)} puan</output></div>
      <p class="card-foot">Faiz %${fmt.num(S.doc.policy.now, 2)} → <b class="mono">%${fmt.num(S.doc.policy.now + S.dr, 2)}</b>. Tablo ve grafik bu değişime göre yeniden hesaplanır; bilanço büyüklüğü ve faiz dışı kalemler sabit varsayılır.</p>
    </div>`;
  }

  const COLS = [
    ["code", "Banka", ""],
    ["dnim", "1 yıl ΔNIM", "Senaryoya göre 12 ayda marj değişimi, %90 aralık"],
    ["net", "Net kâr", "Son 12 ay net kâra göre (vergi sonrası)"],
    ["nii", "Net faiz geliri", "Son 12 ay net faiz gelirine göre değişim"],
    ["roe", "ΔÖzK kârlılığı", "Özkaynak kârlılığına etkisi, puan"],
    ["mc", "Piyasa değerine", "Net kâr etkisinin piyasa değerine oranı (yıllık getiri gibi okunabilir)"],
    ["nim", "NIM", "Son çeyrek net faiz marjı (yıllık, ortalama aktife göre, %)"],
    ["ba", "β aktif", "Aktif getirisinin politika faizine geçişkenliği: bu çeyrek + önceki çeyrek (büzülmüş)"],
    ["bl", "β fonlama", "Fonlama maliyetinin geçişkenliği: bu çeyrek + önceki çeyrek"],
    ["gap", "Gecikme farkı", "Aynı çeyrekte fonlama β − aktif β. Pozitif: mevduat getiriden hızlı yeniden fiyatlanır"],
    ["n", "Gözlem", "Kullanılan çeyrek sayısı"],
  ];
  function rows() {
    const out = S.doc.banks.map(b => {
      const src = S.full && b.full ? { ...b, y1: b.full.y1, y1_se: b.full.y1_se } : b;
      return { b, s: scen(src, S.dr, src.y1, src.y1_se), n: S.full && b.full ? b.full.n : b.n };
    });
    const key = { code: r => r.b.code, nim: r => r.b.nim, ba: r => r.b.asset.b0 + r.b.asset.b1, bl: r => r.b.liab.b0 + r.b.liab.b1, gap: r => r.b.lag_gap,
      dnim: r => r.s?.dnim_bp, nii: r => r.s?.nii_pct, net: r => r.s?.net_pct, roe: r => r.s?.roe_pp, mc: r => r.s?.mcap_pct, n: r => r.n }[S.sort] || (r => r.s?.dnim_bp);
    return out.sort((a, b) => { const x = key(a), y = key(b); return (x == null) - (y == null) || (x < y ? 1 : x > y ? -1 : 0) * S.dir; });
  }

  function table() {
    const rs = rows();
    const max = Math.max(1, ...rs.map(r => Math.max(Math.abs(r.s?.lo_bp || 0), Math.abs(r.s?.hi_bp || 0))));
    const X = v => (50 + v / max * 50).toFixed(1);
    const bar = s => s ? `<span class="br-ci" aria-hidden="true"><i class="br-ci0"></i><i class="br-cir" style="left:${X(s.lo_bp)}%;width:${(X(s.hi_bp) - X(s.lo_bp)).toFixed(1)}%"></i><i class="br-cid ${cls(s.dnim_bp)}" style="left:${X(s.dnim_bp)}%"></i></span>` : "";
    const th = ([k, l, tip]) => `<th scope="col" class="${k === "code" ? "" : "num"}" ${tip ? `data-tip="${esc(tip)}"` : ""}><button type="button" class="th-sort" data-k="${k}" aria-sort="${S.sort === k ? (S.dir > 0 ? "descending" : "ascending") : "none"}">${l}${S.sort === k ? (S.dir > 0 ? " ↓" : " ↑") : ""}</button></th>`;
    const td = (k, b, s, n) => ({
      code: `<td><button type="button" class="link-btn br-pick" data-c="${esc(b.code)}"><b>${esc(b.code)}</b></button> <button type="button" class="tk-pi tk-open" data-sym="${esc(b.code)}" aria-label="${esc(b.code)} hisse paneli">◧</button><span class="t3 br-nm">${esc(b.name || "")}</span></td>`,
      nim: `<td class="num">${b.nim == null ? "—" : "%" + fmt.num(b.nim, 2)}</td>`,
      ba: `<td class="num" data-tip="Bu çeyrek ${pp(b.asset.b0)} · önceki ${pp(b.asset.b1)} · R² ${pp(b.asset.r2)}">${pp(b.asset.b0 + b.asset.b1)}</td>`,
      bl: `<td class="num" data-tip="Bu çeyrek ${pp(b.liab.b0)} · önceki ${pp(b.liab.b1)} · R² ${pp(b.liab.r2)}">${pp(b.liab.b0 + b.liab.b1)}</td>`,
      gap: `<td class="num ${b.lag_gap > 0.03 ? "up" : b.lag_gap < -0.03 ? "down" : ""}">${b.lag_gap > 0 ? "+" : ""}${pp(b.lag_gap)}</td>`,
      dnim: `<td class="num br-dn"><span class="${cls(s?.dnim_bp)}">${bp(s?.dnim_bp)}</span>${bar(s)}<span class="t3 br-rg">${s ? `${bp(s.lo_bp)} … ${bp(s.hi_bp)}` : ""}</span></td>`,
      nii: `<td class="num ${cls(s?.nii_pct)}">${s?.nii_pct == null ? "—" : fmt.pct(s.nii_pct, 0)}</td>`,
      net: `<td class="num ${cls(s?.net_pct)}">${s?.net_pct == null ? "—" : fmt.pct(s.net_pct, 0)}</td>`,
      roe: `<td class="num ${cls(s?.roe_pp)}">${s?.roe_pp == null ? "—" : (s.roe_pp > 0 ? "+" : s.roe_pp < 0 ? "−" : "") + fmt.num(Math.abs(s.roe_pp), 1)}</td>`,
      mc: `<td class="num ${cls(s?.mcap_pct)}">${s?.mcap_pct == null ? "—" : fmt.pct(s.mcap_pct, 1)}</td>`,
      n: `<td class="num t3">${n}</td>`,
    })[k];
    const body = rs.map(({ b, s, n }) => `<tr class="${b.code === S.sel ? "is-sel" : ""}" data-c="${esc(b.code)}">${COLS.map(([k]) => td(k, b, s, n)).join("")}</tr>`).join("");
    const pool = S.full ? S.doc.sample?.full_pool : S.doc.pool;
    return `<section class="card card-flush" aria-labelledby="brTbT">
      <div class="card-head"><h2 class="card-title" id="brTbT">Bankalar: senaryoda 1 yıllık etki</h2>
        <span class="card-meta"><span class="seg seg-sm" role="radiogroup" aria-label="Örneklem" id="brSamp">
          <button type="button" role="radio" data-f="0" aria-checked="${!S.full}" data-tip="2024 T1 sonrası: sadeleşme dönemi (ana model)">2024+</button>
          <button type="button" role="radio" data-f="1" aria-checked="${S.full}" data-tip="2023 dahil: KKM ve menkul kıymet tesis dönemi; sağlamlık kontrolü">2023 dahil</button></span>
          · havuz ${bp(-(pool?.y1 ?? 0) * 100)} / 100 bp indirim</span></div>
      ${S.full ? `<p class="br-warn">2023 dahil örneklemde duyarlılık belirgin şekilde küçülüyor (havuz ${bp(-(S.doc.sample?.full_pool?.y1 ?? 0) * 100)} ↔ 2024+ ${bp(-(S.doc.pool?.y1 ?? 0) * 100)}). 2023'te KKM ve menkul kıymet tesis kuralları fonlama maliyetini politika faizinden kopardı; bugünkü rejime 2024+ modeli daha yakın, ama sonuç düzenleme ortamına duyarlı. β sütunları ana modelden.</p>` : ""}
      <div class="tbl-scroll"><table class="tbl br-tbl"><thead><tr>${COLS.map(th).join("")}</tr></thead><tbody>${body}</tbody></table></div>
      <p class="card-foot br-foot">β'lar 1 puan politika faizi değişiminin aktif getirisine / fonlama maliyetine (ortalama aktife göre, puan) yansıması. Satıra tıkla: grafikte göster. Aralık ±1,645 standart hata (%90).</p>
    </section>`;
  }

  function chart() {
    const b = S.doc.banks.find(x => x.code === S.sel) || S.doc.banks[0];
    if (!b) return "";
    const s = b.series, n = s.p.length, W = 760, H = 260, L = 34, R = 10, T = 10, B = 24;
    const all = [...s.y, ...s.f, ...s.r, ...s.y.map((v, i) => v - s.f[i])];
    const lo = Math.floor(Math.min(0, ...all) / 5) * 5, hi = Math.ceil(Math.max(...all) / 5) * 5;
    const x = i => L + (n === 1 ? 0 : i / (n - 1) * (W - L - R)), y = v => T + (hi - v) / (hi - lo || 1) * (H - T - B);
    const line = (arr, c, dash = "") => `<path d="${arr.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("")}" fill="none" stroke="${c}" stroke-width="2" ${dash ? `stroke-dasharray="${dash}"` : ""}/>`;
    const ticks = []; for (let v = lo; v <= hi; v += (hi - lo) > 40 ? 10 : 5) ticks.push(v);
    const nim = s.y.map((v, i) => v - s.f[i]);
    const pts = (arr, c, lbl) => arr.map((v, i) => `<circle cx="${x(i).toFixed(1)}" cy="${y(v).toFixed(1)}" r="3" fill="${c}" data-tip="${esc(s.p[i])} · ${lbl} %${fmt.num(v, 2)}"/>`).join("");
    return `<section class="card" aria-labelledby="brChT">
      <div class="card-head"><h2 class="card-title" id="brChT">${esc(b.code)}: aktif getirisi, fonlama maliyeti ve politika faizi</h2>
        <span class="card-meta">yıllık %, ortalama toplam aktife göre (TL ve döviz birlikte; döviz ağırlığı yüksek bankada seviye düşük görünür) · çeyreklik</span></div>
      <svg class="br-ch" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(b.code)} çeyreklik aktif getirisi, fonlama maliyeti, net faiz marjı ve politika faizi">
        ${ticks.map(v => `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" class="br-grid"/><text x="${L - 6}" y="${y(v) + 4}" text-anchor="end" class="br-ax">${v}</text>`).join("")}
        ${s.p.map((p, i) => (n <= 8 || i % 2 === 0 || i === n - 1) ? `<text x="${x(i)}" y="${H - 8}" text-anchor="middle" class="br-ax">${esc(p.replace("/", " Ç").replace("Ç03", "Ç1").replace("Ç06", "Ç2").replace("Ç09", "Ç3").replace("Ç12", "Ç4"))}</text>` : "").join("")}
        ${line(s.r, "var(--text-3)", "4 4")}${line(s.y, "var(--series-1)")}${line(s.f, "var(--series-2)")}${line(nim, "var(--series-3)")}
        ${pts(s.y, "var(--series-1)", "aktif getirisi")}${pts(s.f, "var(--series-2)", "fonlama maliyeti")}${pts(nim, "var(--series-3)", "NIM")}${pts(s.r, "var(--text-3)", "politika faizi")}
      </svg>
      <p class="br-leg"><span><i style="background:var(--series-1)"></i>Aktif getirisi</span><span><i style="background:var(--series-2)"></i>Fonlama maliyeti</span><span><i style="background:var(--series-3)"></i>NIM (fark)</span><span><i class="dash"></i>Politika faizi (çeyrek ort.)</span></p>
    </section>`;
  }

  function render() {
    if (!S.doc?.banks?.length) {
      $("#brBody").innerHTML = sh.stateHTML({ kind: "info", title: "Yeterli banka verisi yok", msg: esc(S.doc?.error || "") });
      return;
    }
    const sel = document.activeElement?.id;
    $("#brBody").innerHTML = `${kpis()}${slider()}<div class="br-grid2">${table()}${chart()}</div><p class="m-foot">${window.radarMethod?.link("banka-faiz") || ""}</p>
      <p class="src-line">Kaynak: ${esc(S.doc.policy.source)} · KAP mali tabloları · son dönem ${esc(S.doc.periods)}</p>`;
    bind();
    if (sel === "brDr") $("#brDr")?.focus();
  }
  function rerender() { const t = $("#brBody .br-grid2"); if (!t) return render(); t.innerHTML = table() + chart(); bindTable(); }

  function bind() {
    const r = $("#brDr");
    r.oninput = () => { S.dr = +r.value; $("#brDrOut").textContent = `${S.dr > 0 ? "+" : S.dr < 0 ? "−" : ""}${fmt.num(Math.abs(S.dr), 2)} puan`;
      $(".br-sc .card-foot b").textContent = "%" + fmt.num(S.doc.policy.now + S.dr, 2); rerender(); };
    $("#brReset")?.addEventListener("click", () => { S.dr = S.doc.delta_pp; render(); });
    bindTable();
  }
  function bindTable() {
    $$("#brBody .th-sort").forEach(b => b.onclick = () => { const k = b.dataset.k; S.dir = S.sort === k ? -S.dir : (k === "code" ? -1 : 1); S.sort = k; rerender(); });
    $$("#brBody .br-tbl tbody tr").forEach(tr => tr.onclick = e => { if (e.target.closest(".tk-open")) return; S.sel = tr.dataset.c; rerender(); });
    $$("#brSamp button").forEach(b => b.onclick = () => { S.full = b.dataset.f === "1"; rerender(); });
  }

  function exportCSV() {
    const ex = window.radarExport;
    const out = rows().map(({ b, s, n }) => ({ banka: b.code, ad: b.name || "", nim: b.nim, beta_aktif: +(b.asset.b0 + b.asset.b1).toFixed(3), beta_fonlama: +(b.liab.b0 + b.liab.b1).toFixed(3),
      gecikme_farki: b.lag_gap, senaryo_puan: S.dr, dnim_bp: s && +s.dnim_bp.toFixed(1), dnim_alt_bp: s && +s.lo_bp.toFixed(1), dnim_ust_bp: s && +s.hi_bp.toFixed(1),
      net_faiz_geliri_pct: s?.nii_pct?.toFixed(1), net_kar_pct: s?.net_pct?.toFixed(1), ozk_karlilik_puan: s?.roe_pp?.toFixed(2), piyasa_degerine_pct: s?.mcap_pct?.toFixed(2),
      gozlem: n, orneklem: S.full ? "2023 dahil" : "2024+" }));
    ex.download(`banka_faiz_duyarliligi_${ex.stamp()}.csv`, ex.toCSV(out), "text/csv;charset=utf-8");
  }

  // ─────────────────────────────── hisse paneli bölümü
  function forTicker(code) { return S.doc?.banks?.find(b => b.code === code) || null; }
  function section(code) {
    const b = forTicker(code);
    if (!b) return null;
    const d = S.doc.delta_pp, s = scen(b, d), p100 = scen(b, -1);
    const sec = document.createElement("div");
    sec.className = "tp-sec";
    sec.innerHTML = `<p class="d-sub">Faiz duyarlılığı <span class="t3">· ${esc(b.period)} · ${b.n} çeyrek</span></p>
      <div class="tp-mini">
        <div class="tp-mini-c" data-tip="100 bp politika faizi indiriminin 12 ayda net faiz marjına etkisi"><span class="t3">100 bp indirim</span><b class="mono ${cls(p100?.dnim_bp)}">${bp(p100?.dnim_bp)}</b></div>
        <div class="tp-mini-c" data-tip="Anket beklentisi (${d > 0 ? "+" : "−"}${fmt.num(Math.abs(d ?? 0), 2)} puan) ile 12 ayda NIM değişimi"><span class="t3">Beklenti senaryosu</span><b class="mono ${cls(s?.dnim_bp)}">${bp(s?.dnim_bp)}</b></div>
        <div class="tp-mini-c" data-tip="Senaryoda son 12 ay net kâra göre değişim"><span class="t3">Net kâr</span><b class="mono ${cls(s?.net_pct)}">${s?.net_pct == null ? "—" : fmt.pct(s.net_pct, 0)}</b></div>
      </div>
      <p class="tp-more"><a href="#banka-faiz/${esc(code)}">Banka faiz duyarlılığını aç →</a></p>`;
    return sec;
  }
  window.radarBankRate = {
    get loaded() { return S.loaded; },
    ensure() { if (!S.loaded && !S.loading && !S.error) load(); return new Promise(r => S.loaded || S.error ? r() : waiters.push(r)); },
    forTicker, section,
  };

  sh.register("banka-faiz", {
    onShow() {
      if (sh.param) S.sel = sh.param.toUpperCase();
      S.loaded ? render() : S.error ? renderError() : load();
    },
    async refresh() { await load(true); },
    exports: () => [{ label: "Bankalar (CSV)", hint: `senaryo ${S.dr ?? "—"} puan`, run: exportCSV, disabled: !S.loaded }],
    exportNote: "Banka faiz verisi henüz yüklenmedi",
  });
})();
