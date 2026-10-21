/* Piyasa Radarı — Kâğıt Portföy (kurallı stratejilerin izlenmesi).
   Veri: data/olay/paper.json (olay.yml → radar/paper.py). İlk strateji: bilanço sürprizi (PEAD). Olumlu sürpriz uzun bacak,
   olumsuz sürpriz ayrıca izlenir; uzun − kısa teorik. Takvim zamanı portföyü: açık pozisyonlar eşit ağırlıklı, günlük dengelenir;
   10'dan az pozisyon varsa nakit. Maliyet tek yön %0,2. Kıyas: eşit ağırlıklı BIST Tüm ve XU100. */
(() => {
  "use strict";
  const sh = window.shell;
  const { $, $$, esc, fmt } = sh;
  const SRC = "data/olay/paper.json";
  const S = { doc: null, loaded: false, loading: false, error: null, missing: false, k: "pead_5", view: "x", limit: 40, leg: "all" };

  async function load(force = false) {
    if (S.loading || (S.loaded && !force)) return;
    S.loading = true; S.error = null; S.missing = false;
    if (!S.loaded) $("#ptBody").innerHTML = `<div class="kpi-grid">${Array.from({ length: 4 }, () => `<div class="kpi"><div class="skeleton sk-line w60"></div><div class="skeleton sk-line lg w40"></div></div>`).join("")}</div><div class="skeleton sk-block" style="height:320px;margin-top:16px"></div>`;
    try {
      const r = await fetch(`${SRC}?t=${Date.now()}`, { cache: "no-store" });
      if (r.status === 404) { S.missing = true; throw new Error("veri henüz yayımlanmadı"); }
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      S.doc = await r.json();
      if (!S.doc.strategies?.[S.k]) S.k = Object.keys(S.doc.strategies || {})[0];
      S.loaded = true;
      sh.setUpdated("kagit-portfoy", new Date(S.doc.generated), { label: "Hesaplandı", staleMin: 60 * 6 });
    } catch (e) { S.error = e.message || "veri okunamadı"; }
    finally { S.loading = false; }
    if (sh.route === "kagit-portfoy") S.loaded ? render() : renderError();
  }
  function renderError() {
    $("#ptBody").innerHTML = S.missing
      ? sh.stateHTML({ kind: "info", title: "Kâğıt portföy henüz yayımlanmadı", msg: "Olay veritabanının bir sonraki turunda üretilecek." })
      : sh.stateHTML({ kind: "error", title: "Kâğıt portföy yüklenemedi", msg: esc(S.error), action: "Tekrar dene", actionId: "ptRetry" });
    $("#ptRetry")?.addEventListener("click", () => load(true));
  }

  const pc = (v, d = 1) => v == null || !isFinite(v) ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${fmt.num(Math.abs(v), d)}%`;
  const cls = v => v == null ? "" : v > 0 ? "up" : v < 0 ? "down" : "";
  const SER = {
    x: [["long_x", "Olumlu sürpriz − kıyas", "var(--up)"], ["short_x", "Olumsuz sürpriz − kıyas", "var(--down)"], ["ls", "Uzun − kısa (teorik)", "var(--accent)"]],
    abs: [["long", "Olumlu sürpriz (net)", "var(--up)"], ["short", "Olumsuz sürpriz (net)", "var(--down)"], ["ew", "BIST Tüm (eşit ağırlıklı)", "var(--text-3)"], ["xu100", "XU100", "var(--series-4)"]],
  };

  function kpis(s) {
    const st = s.stats, k = (label, value, sub = "", tip = "") => `<div class="kpi" ${tip ? `data-tip="${esc(tip)}"` : ""}><span class="kpi-label">${label}</span><span class="kpi-value">${value}</span>${sub ? `<span class="kpi-sub">${sub}</span>` : ""}</div>`;
    const L = st.long || {}, X = st.long_x || {}, LS = st.ls || {};
    return `<div class="kpi-grid">
      ${k("Olumlu sürpriz · net", `<span class="${cls(L.total)}">${pc(L.total)}</span>`, `${fmt.int(L.days || 0)} yatırımlı gün · en büyük düşüş ${pc(L.maxdd)}`, "Maliyet düşülmüş; nakitte kalınan günler getiri 0")}
      ${k("Kıyasa göre fark", `<span class="${cls(X.total)}">${pc(X.total)}</span>`, "yalnız yatırımlı günlerde, EA BIST Tüm'e göre", "Stratejinin asıl testi: aynı günlerde piyasanın genelinden iyi mi?")}
      ${k("Uzun − kısa (teorik)", `<span class="${cls(LS.total)}">${pc(LS.total)}</span>`, `Sharpe ${LS.sharpe == null ? "—" : fmt.num(LS.sharpe, 2)} · ${fmt.int(LS.days || 0)} gün`, "Olumlu sürpriz al, olumsuz sürprizi aç sat. BIST'te açığa satış kısıtlı ve ödünç maliyeti yok sayılıyor.")}
      ${k("İşlem", fmt.int(s.n_trades.long + s.n_trades.short), `kârlı kapanan: olumlu %${fmt.num(s.hit.long[0], 0)} · olumsuz %${fmt.num(s.hit.short[0], 0)}`, "Net getirisi pozitif kapanan işlemlerin oranı")}
    </div>`;
  }

  function chart(s) {
    const D = s.dates, N = D.length, ser = SER[S.view].filter(([k]) => s.nav[k]);
    if (N < 2) return "";
    const W = 860, H = 280, P = { l: 52, r: 16, t: 14, b: 34 };
    const vals = ser.flatMap(([k]) => s.nav[k].map(v => (v - 1) * 100)).concat(0);
    let y0 = Math.min(...vals), y1 = Math.max(...vals); const pad = (y1 - y0) * 0.08 || 1; y0 -= pad; y1 += pad;
    const X = i => P.l + i / (N - 1) * (W - P.l - P.r), Y = v => P.t + (y1 - v) / (y1 - y0) * (H - P.t - P.b);
    const step = (y1 - y0) > 60 ? 20 : (y1 - y0) > 30 ? 10 : (y1 - y0) > 12 ? 5 : (y1 - y0) > 5 ? 2 : 1, ticks = [];
    for (let t = Math.ceil(y0 / step) * step; t <= y1; t += step) ticks.push(t);
    const line = a => a.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y((v - 1) * 100).toFixed(1)}`).join("");
    const months = []; D.forEach((d, i) => { if (i === 0 || d.slice(5, 7) !== D[i - 1].slice(5, 7)) months.push([i, d]); });
    const inv = s.npos.long.map(n => n > 0);
    // yatırımlı günler (uzun bacak) zemin bandı
    let bands = "", st = null;
    inv.forEach((v, i) => { if (v && st == null) st = i; if ((!v || i === N - 1) && st != null) { const e = v ? i : i - 1; bands += `<rect x="${X(st)}" y="${P.t}" width="${Math.max(1, X(e) - X(st))}" height="${H - P.t - P.b}" class="pt-inv"/>`; st = null; } });
    const hov = D.map((d, i) => `<rect x="${X(i) - (W - P.l - P.r) / N / 2}" y="${P.t}" width="${(W - P.l - P.r) / N}" height="${H - P.t - P.b}" class="k-ev-hit" data-tip="${esc(`<b>${fmt.date(d, { day: "numeric", month: "short", year: "numeric" })}</b>` + ser.map(([k, l]) => `<br>${l}: ${pc((s.nav[k][i] - 1) * 100, 2)}`).join("") + `<br><span class='t3'>açık pozisyon: ${s.npos.long[i]} olumlu · ${s.npos.short[i]} olumsuz</span>`)}"/>`).join("");
    return `<section class="card" aria-labelledby="ptChT">
      <div class="card-head"><h2 class="card-title" id="ptChT">Birikimli getiri</h2>
        <div class="seg" role="radiogroup" aria-label="Görünüm" id="ptView">${[["x", "Kıyasa göre"], ["abs", "Mutlak"]].map(([v, l]) => `<button type="button" role="radio" data-v="${v}" aria-checked="${S.view === v}">${l}</button>`).join("")}</div></div>
      <svg viewBox="0 0 ${W} ${H}" class="k-ev-svg pt-svg" role="img" aria-label="Kâğıt portföy birikimli getiri">
        ${bands}
        ${ticks.map(t => `<line x1="${P.l}" x2="${W - P.r}" y1="${Y(t)}" y2="${Y(t)}" class="${t === 0 ? "z" : "g"}"/><text x="${P.l - 6}" y="${Y(t) + 4}" text-anchor="end">${t > 0 ? "+" : ""}${t}%</text>`).join("")}
        ${months.map(([i, d]) => `<text x="${X(i)}" y="${H - P.b + 16}" text-anchor="${i === 0 ? "start" : "middle"}">${fmt.date(d, { month: "short" })}</text>`).join("")}
        ${ser.map(([k, , c]) => `<path d="${line(s.nav[k])}" fill="none" stroke="${c}" stroke-width="${k === "ls" ? 2.6 : 2}" ${k === "ew" || k === "xu100" ? 'stroke-dasharray="5 4"' : ""}/>`).join("")}
        ${hov}
      </svg>
      <p class="br-leg">${ser.map(([, l, c]) => `<span><i style="background:${c}"></i>${l}</span>`).join("")}<span><i class="pt-inv-i"></i>olumlu bacakta yatırımlı günler</span></p>
      <p class="k-note">${S.view === "x" ? "Kıyasa göre: her bacağın yalnız yatırımlı olduğu günlerde eşit ağırlıklı BIST Tüm'den farkı birikir; nakitte beklenen günler düz. Olumsuz sürpriz çizgisinin aşağı gitmesi, bu hisselerin piyasadan kötü gittiğini (kısa bacak için kazanç) gösterir." : "Mutlak: nakitte beklenen günlerde getiri 0 (TL mevduat getirisi eklenmedi); kıyas çizgileri her gün yatırımlı."}</p>
    </section>`;
  }

  function trades(s) {
    const all = s.trades.filter(t => S.leg === "all" || t.leg === S.leg), rs = all.slice(0, S.limit);
    return `<section class="card card-flush" aria-labelledby="ptTrT">
      <div class="card-head"><h2 class="card-title" id="ptTrT">İşlemler</h2>
        <div class="seg" role="radiogroup" aria-label="Bacak" id="ptLeg">${[["all", "Tümü"], ["long", "Olumlu sürpriz"], ["short", "Olumsuz sürpriz"]].map(([v, l]) => `<button type="button" role="radio" data-v="${v}" aria-checked="${S.leg === v}">${l}</button>`).join("")}</div></div>
      <div class="tbl-scroll"><table class="tbl pt-tbl"><thead><tr><th>Giriş</th><th>Çıkış</th><th>Hisse</th><th>Dönem</th><th class="num" data-tip="Ölçekli sürpriz: reel net kârın geçen yılın aynı çeyreğinden farkı / son 4 çeyreğin ortalama kâr büyüklüğü">Sürpriz</th><th class="num">Brüt</th><th class="num">Net</th></tr></thead><tbody>
      ${rs.map(t => `<tr><td class="mono t3">${esc(t.in)}</td><td class="mono t3">${t.open ? `<span class="tag">açık</span>` : esc(t.out)}</td>
        <td><span class="${t.leg === "long" ? "up" : "down"}" aria-label="${t.leg === "long" ? "olumlu" : "olumsuz"}">${t.leg === "long" ? "▲" : "▼"}</span> <b>${esc(t.sym)}</b> <button type="button" class="tk-pi tk-open" data-sym="${esc(t.sym)}" aria-label="${esc(t.sym)} hisse paneli">◧</button></td>
        <td class="t3">${esc(t.period || "")}</td><td class="num">${t.su == null ? "—" : (t.su > 0 ? "+" : "−") + fmt.num(Math.abs(t.su), 2)}</td>
        <td class="num ${cls(t.ret)}">${pc(t.ret)}</td><td class="num ${cls(t.ret_net)}">${pc(t.ret_net)}</td></tr>`).join("")}
      </tbody></table></div>
      ${all.length > S.limit ? `<p class="card-foot"><button type="button" class="link-btn" id="ptMore">Daha fazla göster</button></p>` : ""}
    </section>`;
  }

  function method(s) {
    return `<details class="card br-meth"><summary class="card-title">Kurallar ve sınırlar</summary><ul>
      <li><b>Sinyal.</b> Finansal rapor yayımlandığında reel (TÜFE ile düzeltilmiş) net kâr geçen yılın aynı çeyreğiyle karşılaştırılır; fark son dört çeyreğin ortalama kâr büyüklüğünün %20'sinden fazlaysa olumlu, eksiyse olumsuz sürpriz. Aynı hisse ve dönem için tek işlem.</li>
      <li><b>Giriş ve çıkış.</b> Bildirim seans içindeyse aynı gün, seans dışındaysa ertesi seansın kapanışında giriş; ${s.hold} seans sonra kapanışta çıkış. Kapanışta girildiği için ilk günün tepkisinin bir kısmı kaçırılır: Olay Karnesi'ndeki 1 seanslık farkın çoğu burada yoktur. Bu bilinçli: gerçekte uygulanabilir olan bu.</li>
      <li><b>Portföy.</b> Açık pozisyonlar eşit ağırlıklı, her gün yeniden dengelenir; 10'dan az açık pozisyon varsa nakit. Maliyet alımda ve satımda ayrı ayrı %${fmt.num(S.doc.cost_side * 100, 1)} (komisyon + kayma). Nakitteki TL faiz getirisi eklenmez, bu yüzden mutlak getiri nakit ağırlıklı dönemlerde düşük görünür.</li>
      <li><b>Uzun − kısa.</b> Teorik: BIST'te açığa satış ve pay ödünç alma sınırlı, ödünç maliyeti yok sayıldı. Asıl soru, olumlu ve olumsuz sürpriz hisselerinin birbirinden ayrışıp ayrışmadığı.</li>
      <li><b>Okuma.</b> Bu bir yatırım önerisi değil; geriye dönük ve kâğıt üzerinde. Veri birikerek uzar (KAP geçmişi 2 yıla dolduruluyor); kısa dönemde sonuç tek bir piyasa rejimine (ör. küçük hisselerin sert düştüğü bir dönem) bağlı kalabilir.</li></ul></details>`;
  }

  function render() {
    const s = S.doc.strategies?.[S.k];
    if (!s) { $("#ptBody").innerHTML = sh.stateHTML({ kind: "info", title: "Henüz strateji verisi yok", msg: "" }); return; }
    const opts = Object.entries(S.doc.strategies).map(([k, v]) => [k, `${v.hold} seans tut`]);
    $("#ptBody").innerHTML = `<div class="toolbar ok-tb"><span class="t3">Strateji: <b>Bilanço sürprizi (PEAD)</b></span>
        <div class="seg" role="radiogroup" aria-label="Elde tutma" id="ptK">${opts.map(([k, l]) => `<button type="button" role="radio" data-v="${k}" aria-checked="${S.k === k}">${l}</button>`).join("")}</div>
        <span class="t3">${fmt.date(s.dates[0], { day: "numeric", month: "short", year: "numeric" })} – ${fmt.date(s.dates[s.dates.length - 1], { day: "numeric", month: "short", year: "numeric" })}</span></div>
      ${kpis(s)}${chart(s)}${trades(s)}${method(s)}
      <p class="src-line">Kaynak: KAP mali tabloları (sürpriz), olay veritabanı, fiyat Yahoo · ${fmt.date(S.doc.generated, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</p>`;
    const segB = (id, f) => { $$(`#${id} button`).forEach(b => b.onclick = () => { f(b.dataset.v); render(); }); sh.radioKeys($(`#${id}`)); };
    segB("ptK", v => { S.k = v; S.limit = 40; });
    segB("ptView", v => { S.view = v; });
    segB("ptLeg", v => { S.leg = v; S.limit = 40; });
    $("#ptMore")?.addEventListener("click", () => { S.limit += 80; render(); });
  }

  function exportCSV() {
    const ex = window.radarExport, s = S.doc.strategies[S.k];
    ex.download(`kagit_portfoy_${S.k}_${ex.stamp()}.csv`, ex.toCSV(s.trades.map(t => ({ bacak: t.leg === "long" ? "olumlu" : "olumsuz", hisse: t.sym, donem: t.period, surpriz: t.su,
      giris: t.in, cikis: t.out || "açık", brut_yuzde: t.ret, net_yuzde: t.ret_net }))), "text/csv;charset=utf-8");
  }
  sh.register("kagit-portfoy", {
    onShow() { S.loaded ? render() : S.error ? renderError() : load(); },
    async refresh() { await load(true); },
    exports: () => [{ label: "İşlemler (CSV)", hint: S.k, run: exportCSV, disabled: !S.loaded }],
    exportNote: "Kâğıt portföy henüz yüklenmedi",
  });
})();
