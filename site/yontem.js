/* Lyra Radar — Yöntem Karnesi: hangi tarama yöntemi BIST'te gerçekten işe yarıyor?
   Veri: data/yontem/yontem.json (yontem.yml, haftalık → yontem dalı; radar/yontem.py). Aylık, nokta-zamanlı faktör testi:
   her yöntem için beşli dilimler, en iyi − en kötü dilim farkı, rank IC, Newey-West t, maliyet sonrası en iyi dilim,
   alt dönemler, reel TL ve USD getiri. Tarayıcı yalnız gösterir; hesap sunucuda. */
(() => {
  "use strict";
  const sh = window.shell;
  const { $, $$, esc, fmt } = sh;
  const SRC = "data/yontem/yontem.json";
  const S = { doc: null, loaded: false, loading: false, error: null, missing: false, grp: "all", sort: "t", sel: null };
  const GROUPS = { all: "Tümü", "Değer": "Değer", "Kalite": "Kalite", "Fiyat": "Fiyat", "Olay": "Olay", "Birleşik": "Birleşik" };
  const V = {
    guclu: ["Güçlü kanıt", "up", "t ≥ 3 ve alt dönemlerin çoğunda aynı yön"],
    kisa_guclu: ["Güçlü · kısa dönem", "up", "t ≥ 3, ama test tek bir dönemi (ör. yalnız 2023 sonrası) ya da 60 aydan azını kapsıyor; farklı piyasa koşullarında sınanmadı"],
    umut: ["Zayıf işaret", "warn-t", "2 ≤ t < 3: umut verici ama çoklu test eşiğinin altında"],
    yok: ["Kanıt yok", "t3", "|t| < 2: getiri farkı şanstan ayırt edilemiyor"],
    zayif_ters: ["Zayıf ters", "warn-t", "−3 < t ≤ −2: beklenenin tersi yönde, zayıf"],
    ters: ["Ters çalışıyor", "down", "t ≤ −3: beklenenin tersi yönde güçlü"],
    yetersiz: ["Veri yetersiz", "t3", "24 aydan az test edilebilir dönem"],
  };
  const ORDER = { guclu: 0, kisa_guclu: 0.5, umut: 1, zayif_ters: 3, ters: 4, yok: 2, yetersiz: 5 };

  async function load(force = false) {
    if (S.loading || (S.loaded && !force)) return;
    S.loading = true; S.error = null; S.missing = false;
    if (!S.loaded) renderLoading();
    try {
      const r = await fetch(`${SRC}?t=${Date.now()}`, { cache: "no-store" });
      if (r.status === 404) { S.missing = true; throw new Error("veri henüz yayımlanmadı"); }
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      S.doc = await r.json();
      S.loaded = true;
      sh.setUpdated("yontem-karnesi", new Date(S.doc.generated), { label: "Hesaplandı", staleMin: 60 * 24 * 8 });
    } catch (e) { S.error = e.message || "veri okunamadı"; }
    finally { S.loading = false; }
    if (sh.route === "yontem-karnesi") S.loaded ? render() : renderError();
  }

  function renderLoading() {
    $("#ykBody").innerHTML = `<div class="kpi-grid">${Array.from({ length: 4 }, () => `<div class="kpi"><div class="skeleton sk-line w60"></div><div class="skeleton sk-line lg w40"></div></div>`).join("")}</div>
      <div class="skeleton sk-block" style="height:360px;margin-top:16px"></div>`;
  }
  function renderError() {
    $("#ykBody").innerHTML = S.missing
      ? sh.stateHTML({ kind: "info", title: "Yöntem karnesi henüz hesaplanmadı", msg: "Test haftada bir (pazar sabahı) çalışıyor; ilk sonuç bir sonraki turda görünecek." })
      : sh.stateHTML({ kind: "error", title: "Yöntem karnesi yüklenemedi", msg: esc(S.error), action: "Tekrar dene", actionId: "ykRetry" });
    $("#ykRetry")?.addEventListener("click", () => load(true));
  }

  const pc = (v, d = 2) => v == null || !isFinite(v) ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${fmt.num(Math.abs(v) * 100, d)}%`;
  const tt = v => v == null ? "—" : `${v < 0 ? "−" : ""}${fmt.num(Math.abs(v), 1)}`;
  const tcls = v => v == null ? "t3" : v >= 3 ? "up" : v >= 2 ? "warn-t" : v <= -3 ? "down" : v <= -2 ? "warn-t" : "t3";
  const mlab = m => m ? `${["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"][+m.slice(5) - 1]} ${m.slice(0, 4)}` : "—";

  function controls() {
    const seg = (id, opts, cur, lbl) => `<div class="seg" role="radiogroup" aria-label="${lbl}" id="${id}">${Object.entries(opts).map(([v, l]) =>
      `<button type="button" role="radio" data-v="${v}" aria-checked="${String(cur) === v}">${l}</button>`).join("")}</div>`;
    return `<div class="toolbar ok-tb">${seg("ykG", GROUPS, S.grp, "Yöntem grubu")}${seg("ykS", { t: "Kanıta göre", ls: "Getiri farkına göre", name: "Ada göre" }, S.sort, "Sıralama")}</div>`;
  }

  function kpis(d) {
    const k = (label, value, sub = "", tip = "") => `<div class="kpi" ${tip ? `data-tip="${esc(tip)}"` : ""}><span class="kpi-label">${label}</span><span class="kpi-value">${value}</span>${sub ? `<span class="kpi-sub">${sub}</span>` : ""}</div>`;
    const fs = d.factors, strong = fs.filter(f => f.verdict === "guclu" || f.verdict === "kisa_guclu").length, weak = fs.filter(f => f.verdict === "umut").length;
    const fund = fs.filter(f => f.scope !== "Tüm hisseler" && f.n), fn = fund.length ? Math.max(...fund.map(f => f.n)) : 0;
    return `<div class="kpi-grid">
      ${k("Test dönemi", d.months ? `${mlab(d.months[0])} – ${mlab(d.months[1])}` : "—", `${fmt.int(d.n_months)} ay · fiyat yöntemleri`)}
      ${k("Temel yöntemlerde", `${fmt.int(fn)} ay`, `KAP tabloları ${esc(d.first_period || "—")} döneminden; geçmiş iniyor`, "Mali tablolar 2016 yıl sonuna kadar kademeli iniyor (KAP indirme sınırı). Doldukça temel yöntemlerin test dönemi uzar.")}
      ${k("Hisse / ay", fmt.int(d.stocks_avg), `likidite süzgeci sonrası · ${fmt.int(d.companies)} şirketin tablosu`)}
      ${k("Güçlü kanıt", `${strong} <small class="muted">/ ${fs.length}</small>`, `${weak} zayıf işaret · eşik t ≥ 3`, "Çok sayıda yöntem test edildiğinde t ≥ 2 eşiği şans eseri 'başarılı' yöntem üretir; bu yüzden güçlü kanıt için t ≥ 3 aranır.")}
    </div>`;
  }

  function quintBars(q) {
    if (!q) return "";
    const R = Math.max(0.01, ...q.map(v => Math.abs(v || 0)));
    return `<span class="yk-q" aria-label="Dilim fazla getirileri">${q.map((v, i) => `<i class="${(v || 0) >= 0 ? "pos" : "neg"}" style="height:${(Math.abs(v || 0) / R * 100).toFixed(0)}%" data-tip="${i + 1}. dilim: aylık ${pc(v)} (piyasaya göre)"></i>`).join("")}</span>`;
  }

  function list(d) {
    let fs = d.factors.filter(f => S.grp === "all" || f.group === S.grp);
    const key = { t: f => [ORDER[f.verdict] ?? 9, -(Math.abs(f.ls_t ?? 0))], ls: f => [-(f.ls ?? -9), 0], name: f => [f.name, 0] }[S.sort];
    fs = [...fs].sort((a, b) => { const x = key(a), y = key(b); return x[0] < y[0] ? -1 : x[0] > y[0] ? 1 : x[1] - y[1]; });
    const row = f => {
      const v = V[f.verdict] || V.yetersiz;
      return `<tr class="${S.sel === f.key ? "is-sel" : ""}" data-k="${f.key}">
        <td><b>${esc(f.name)}</b><span class="t3 ok-sub">${esc(f.group)} · ${esc(f.scope)}</span></td>
        <td><span class="${v[1]}" data-tip="${esc(v[2])}"><b>${v[0]}</b></span></td>
        <td class="num"><b class="${tcls(f.ls_t)}">${pc(f.ls)}</b><span class="t3 ok-sub">t ${tt(f.ls_t)}</span></td>
        <td class="num">${f.ic == null ? "—" : fmt.num(f.ic, 3)}<span class="t3 ok-sub">t ${tt(f.ic_t)}</span></td>
        <td class="num">${pc(f.top_ann, 1)}<span class="t3 ok-sub">yıllık · maliyet sonrası</span></td>
        <td class="num">${quintBars(f.quint)}</td>
        <td class="num">${fmt.int(f.n || 0)}<span class="t3 ok-sub">${fmt.int(f.stocks || 0)} hisse</span></td></tr>`;
    };
    return `<section class="card card-flush" aria-labelledby="ykTbT">
      <div class="card-head"><h2 class="card-title" id="ykTbT">Yöntemler</h2><span class="card-meta">satıra tıkla: birikimli getiri, alt dönemler, reel TL ve USD</span></div>
      <div class="tbl-scroll"><table class="tx ok-tbl yk-tbl"><thead><tr>
        <th scope="col">Yöntem</th><th scope="col">Sonuç</th>
        <th scope="col" class="num" data-tip="Her ay en iyi %20 ile en kötü %20'lik dilimin ertesi ay getiri farkı (eşit ağırlık); aylık ortalama ve Newey-West t">Aylık fark (Ü−A)</th>
        <th scope="col" class="num" data-tip="Sinyal sırası ile ertesi ay getiri sırası arasındaki korelasyonun aylık ortalaması">Rank IC</th>
        <th scope="col" class="num" data-tip="En iyi dilimin piyasaya (eşit ağırlıklı evren) göre fazla getirisi; devir hızına göre %0,2/işlem maliyeti düşülmüş">En iyi dilim</th>
        <th scope="col" class="num" data-tip="1. (en kötü) → 5. (en iyi) dilimin aylık fazla getirisi. Düzenli artan bir merdiven, tek uçtan gelen bir farktan daha güvenilirdir.">Dilimler</th>
        <th scope="col" class="num">Ay</th></tr></thead>
      <tbody>${fs.map(row).join("")}</tbody></table></div></section>`;
  }

  function chart(f) {
    const c = f.cum;
    if (!c || c.m.length < 2) return "";
    const W = 640, H = 220, P = { l: 44, r: 12, t: 12, b: 26 };
    const ser = [["top", "En iyi dilim (net, piyasaya göre)", "var(--series-1)"], ["bot", "En kötü dilim (piyasaya göre)", "var(--text-3)"], ["ls", "Fark (en iyi − en kötü)", "var(--series-2)"]];
    const all = ser.flatMap(([k]) => c[k]).map(v => Math.log(v));
    const lo = Math.min(0, ...all), hi = Math.max(0, ...all), n = c.m.length;
    const x = i => P.l + (W - P.l - P.r) * i / (n - 1), y = v => P.t + (H - P.t - P.b) * (hi - Math.log(v)) / ((hi - lo) || 1);
    const ticks = [lo, 0, hi].filter((v, i, a) => a.indexOf(v) === i).map(v => Math.exp(v));
    const yrs = c.m.map((m, i) => [m, i]).filter(([m], i) => m.endsWith("-01") || i === 0);
    const step = Math.ceil(yrs.length / 8);
    return `<svg class="k-ev-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Birikimli fazla getiri">
      ${ticks.map(t => `<line x1="${P.l}" x2="${W - P.r}" y1="${y(t)}" y2="${y(t)}" class="${t === 1 ? "z" : "g"}"/><text x="${P.l - 6}" y="${y(t) + 4}" text-anchor="end">${pc(t - 1, 0)}</text>`).join("")}
      ${yrs.filter((_, j) => j % step === 0).map(([m, i]) => `<text x="${x(i)}" y="${H - 8}" text-anchor="middle">${m.slice(0, 4)}</text>`).join("")}
      ${ser.map(([k, , col]) => `<path class="ln" style="stroke:${col}" d="${c[k].map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("")}"/>`).join("")}
    </svg><div class="chart-legend">${ser.map(([k, l, col]) => `<span><i style="background:${col}"></i>${l} ${pc(c[k][n - 1] - 1, 0)}</span>`).join("")}</div>`;
  }

  function detail(d) {
    const f = d.factors.find(x => x.key === S.sel);
    if (!f) return "";
    const v = V[f.verdict] || V.yetersiz;
    const real = (o, l) => o ? `<tr><th scope="row">${l}</th><td class="num">${pc(o.top, 1)}</td><td class="num">${pc(o.bench, 1)}</td><td class="num t3">${o.n} ay</td></tr>` : "";
    return `<section class="k-ev" aria-labelledby="ykDtT">
      <div class="k-ev-h"><h3 class="card-title" id="ykDtT">${esc(f.name)} <span class="${v[1]}">· ${v[0]}</span></h3><span class="card-meta">${esc(f.scope)} · ${mlab(f.from)} – ${mlab(f.to)} · ${f.n} ay</span></div>
      <p class="t2">${esc(f.desc)}</p>
      ${chart(f)}
      <div class="res-cols">
        <div><p class="d-sub">Alt dönemler · aylık fark (Ü−A)</p><table class="fa-kv"><tbody>${(f.subs || []).map(s => `<tr><th scope="row">${esc(s.name)} <span class="muted">${s.n} ay</span></th><td class="num"><b class="${tcls(s.t)}">${pc(s.ls)}</b> <small class="muted">t ${tt(s.t)}</small></td></tr>`).join("") || `<tr><td class="t3">Alt dönem için yeterli ay yok</td></tr>`}</tbody></table></div>
        <div><p class="d-sub">Yıllık getiri · en iyi dilim (net) ve evren</p><table class="fa-kv"><thead><tr><th></th><th class="num">En iyi dilim</th><th class="num">Evren (EA)</th><th></th></tr></thead><tbody>${real(f.real, "Reel TL (TÜFE)")}${real(f.usd, "ABD doları")}</tbody></table>
          <p class="t3">Devir hızı: ayda en iyi dilimin %${fmt.num((f.turn || 0) * 100, 0)}'i değişiyor · isabet (fark > 0 olan ay): %${fmt.num((f.hit || 0) * 100, 0)}</p></div>
      </div></section>`;
  }

  function render() {
    const d = S.doc;
    $("#ykBody").innerHTML = `${controls()}${kpis(d)}
      <p class="card-foot fa-oos">Geriye dönük test; gelecek getirinin garantisi değildir. Borsadan çıkmış şirketler veri kaynağında olmadığı için sonuçlar bir miktar iyimserdir. Ayrıntı: ${window.radarMethod?.link("yontem-karnesi") || "Metodoloji"}</p>
      ${list(d)}${detail(d)}
      <p class="src-line">Kaynak: KAP mali tabloları (yayın anına göre), TCMB EVDS TÜFE, fiyat Yahoo (kişisel kullanım; ham fiyat yayımlanmaz) · ${fmt.date(d.generated, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</p>`;
    bind();
  }

  function bind() {
    const segB = (id, f) => { $$(`#${id} button`).forEach(b => b.onclick = () => { f(b.dataset.v); render(); }); sh.radioKeys($(`#${id}`)); };
    segB("ykG", v => { S.grp = v; });
    segB("ykS", v => { S.sort = v; });
    $$("#ykBody .yk-tbl tbody tr").forEach(tr => tr.onclick = () => { S.sel = S.sel === tr.dataset.k ? null : tr.dataset.k; render(); $("#ykDtT")?.scrollIntoView({ block: "nearest", behavior: "smooth" }); });
  }

  function exportCSV() {
    const ex = window.radarExport;
    const out = S.doc.factors.map(f => ({ yontem: f.name, grup: f.group, kapsam: f.scope, sonuc: (V[f.verdict] || V.yetersiz)[0], ay: f.n, hisse_ay: f.stocks,
      aylik_fark: f.ls, fark_t: f.ls_t, rank_ic: f.ic, ic_t: f.ic_t, en_iyi_dilim_aylik_net: f.top, en_iyi_yillik_net: f.top_ann, devir: f.turn,
      ...Object.fromEntries((f.quint || []).map((v, i) => [`dilim${i + 1}`, v])) }));
    ex.download(`yontem_karnesi_${ex.stamp()}.csv`, ex.toCSV(out), "text/csv;charset=utf-8");
  }

  sh.register("yontem-karnesi", {
    onShow() { S.sel = sh.param || S.sel; S.loaded ? render() : S.error ? renderError() : load(); },
    async refresh() { await load(true); },
    exports: () => [{ label: "Yöntemler (CSV)", hint: "tüm yöntemlerin istatistikleri", run: exportCSV, disabled: !S.loaded }],
    exportNote: "Yöntem karnesi henüz yüklenmedi",
  });
})();
