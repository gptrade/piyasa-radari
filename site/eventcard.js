/* Lyra Radar — Olay Karnesi.
   Veri: data/olay/karne.json (olay.yml → olay dalı; radar/eventstudy.py). Bütün BIST (ve izlenen ABD hisseleri) için
   olay tipine ve yöne göre olaydan sonraki 1/5/20 seans anormal getiri. BIST: eşit ağırlıklı BIST Tüm'e göre, ABD: S&P 500'e göre.
   Tablo tarayıcıda süzülüp toplanır (pazar, dönem, yön, güçlü, Benimkiler); 20 seanslık yol grafiği sunucuda hesaplanır. */
(() => {
  "use strict";
  const sh = window.shell;
  const { $, $$, esc, fmt } = sh;
  const SRC = "data/olay/karne.json";
  const S = { doc: null, rows: [], loaded: false, loading: false, error: null, missing: false,
    m: "BIST", days: 90, dir: "all", strong: false, sort: "n", sdir: 1, sel: "*", h: 20, limit: 40 };
  const DIRS = { all: "Tüm yönler", pos: "Olumlu", neg: "Olumsuz", zero: "Yönsüz" };
  const PERIODS = { 30: "30G", 90: "90G", 180: "6A", 365: "1Y" };
  const REACT = new Set(["borsa_tedbir"]);      // fiyat hareketinin sonucu olan olaylar (devre kesici): "Tüm olaylar"a girmez

  async function load(force = false) {
    if (S.loading || (S.loaded && !force)) return;
    S.loading = true; S.error = null; S.missing = false;
    if (!S.loaded) renderLoading();
    try {
      const r = await fetch(`${SRC}?t=${Date.now()}`, { cache: "no-store" });
      if (r.status === 404) { S.missing = true; throw new Error("veri henüz yayımlanmadı"); }
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      S.doc = await r.json();
      const c = S.doc.cols, ix = Object.fromEntries(c.map((k, i) => [k, i]));
      S.rows = S.doc.rows.map(a => { const o = {}; for (const k in ix) o[k] = a[ix[k]]; o.t = Date.parse(o.ts.replace(" ", "T") + ":00+03:00"); return o; });
      S.first = S.rows.reduce((m, r) => Math.min(m, r.t), Infinity);
      if (!isFinite(S.first)) S.first = null;
      S.loaded = true;
      sh.setUpdated("olay-karnesi", new Date(S.doc.generated), { label: "Hesaplandı", staleMin: 60 * 6 });
    } catch (e) { S.error = e.message || "veri okunamadı"; }
    finally { S.loading = false; }
    if (sh.route === "olay-karnesi") S.loaded ? render() : renderError();
  }

  // ─────────────────────────────── istatistik
  // Ortalama ve olay gününe göre kümelenmiş standart hata (aynı gündeki olaylar bağımsız sayılmaz)
  function cmean(xs, gs) {
    const n = xs.length;
    if (!n) return null;
    const m = xs.reduce((a, b) => a + b, 0) / n;
    if (n < 2) return { m, se: null, n };
    const by = new Map();
    xs.forEach((x, i) => by.set(gs[i], (by.get(gs[i]) || 0) + (x - m)));
    const G = by.size;
    let ss = 0; by.forEach(v => { ss += v * v; });
    const se = G > 1 ? Math.sqrt(G / (G - 1) * ss / (n * n)) : Math.sqrt(xs.reduce((a, x) => a + (x - m) ** 2, 0) / (n - 1) / n);
    return { m, se, n, hit: xs.filter(x => x > 0).length / n };
  }
  function filtered() {
    const since = Date.now() - S.days * 864e5, mine = sh.mine ? sh.mineSet() : null;
    return S.rows.filter(r => r.m === S.m && r.t >= since && (!mine || mine.has(r.sym)) && (!S.strong || r.strong) &&
      (S.dir === "all" || (S.dir === "pos" ? r.dir > 0 : S.dir === "neg" ? r.dir < 0 : !r.dir)));
  }
  function agg(rows) {
    const by = new Map();
    for (const r of rows) { if (!by.has(r.type)) by.set(r.type, []); by.get(r.type).push(r); }
    const one = (type, rs) => {
      const o = { type, n: rs.length, syms: new Set(rs.map(r => r.sym)).size };
      for (const h of [1, 5, 20]) { const ok = rs.filter(r => r["a" + h] != null); o["h" + h] = cmean(ok.map(r => r["a" + h]), ok.map(r => r.d0)); }
      const p = rs.filter(r => r.pre5 != null); o.pre = cmean(p.map(r => r.pre5), p.map(r => r.d0));
      return o;
    };
    const list = [...by].map(([t, rs]) => one(t, rs));
    return { all: one("*", rows.filter(r => !REACT.has(r.type))), list };
  }

  // ─────────────────────────────── görünüm
  function renderLoading() {
    $("#okBody").innerHTML = `<div class="kpi-grid">${Array.from({ length: 4 }, () => `<div class="kpi"><div class="skeleton sk-line w60"></div><div class="skeleton sk-line lg w40"></div></div>`).join("")}</div>
      <div class="skeleton sk-block" style="height:360px;margin-top:16px"></div>`;
  }
  function renderError() {
    $("#okBody").innerHTML = S.missing
      ? sh.stateHTML({ kind: "info", title: "Olay karnesi henüz yayımlanmadı", msg: "Olay veritabanı saatlik çalışıyor; karne bir sonraki yayında görünecek." })
      : sh.stateHTML({ kind: "error", title: "Olay karnesi yüklenemedi", msg: esc(S.error), action: "Tekrar dene", actionId: "okRetry" });
    $("#okRetry")?.addEventListener("click", () => load(true));
  }
  const lab = t => t === "*" ? "Tüm olaylar" : S.doc.labels[t] || t;
  const pc = (v, d = 1) => v == null || !isFinite(v) ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${fmt.num(Math.abs(v), d)}%`;
  const cls = s => !s || s.se == null ? "" : s.m - 1.96 * s.se > 0 ? "up" : s.m + 1.96 * s.se < 0 ? "down" : "flat";

  function controls() {
    const seg = (id, opts, cur, lbl) => `<div class="seg" role="radiogroup" aria-label="${lbl}" id="${id}">${Object.entries(opts).map(([v, l]) =>
      `<button type="button" role="radio" data-v="${v}" aria-checked="${String(cur) === v}">${l}</button>`).join("")}</div>`;
    return `<div class="toolbar ok-tb">${seg("okM", { BIST: "BIST", US: "ABD" }, S.m, "Pazar")}${seg("okP", PERIODS, S.days, "Dönem")}
      ${seg("okD", DIRS, S.dir, "Yön")}
      <button type="button" class="chip" id="okStrong" aria-pressed="${S.strong}" data-tip="AI sınıflandırıcının güveni ≥ %70 ve önemi orta/yüksek olan olaylar"><svg class="ck" viewBox="0 0 12 12"><path d="M2.5 6.2 5 8.5l4.5-5" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>Yalnız güçlü</button>
      ${seg("okH", { 1: "1 seans", 5: "5 seans", 20: "20 seans" }, S.h, "Sıralama ufku")}</div>`;
  }

  function kpis(rows, a) {
    const k = (label, value, sub = "", tip = "") => `<div class="kpi" ${tip ? `data-tip="${esc(tip)}"` : ""}><span class="kpi-label">${label}</span><span class="kpi-value">${value}</span>${sub ? `<span class="kpi-sub">${sub}</span>` : ""}</div>`;
    const days = new Set(rows.map(r => r.d0)).size, h = a.all["h" + S.h];
    return `<div class="kpi-grid">
      ${k("Olay", fmt.int(rows.length), `${fmt.int(a.all.syms)} hisse · ${fmt.int(days)} işlem günü`)}
      ${k("Kıyas", S.m === "BIST" ? "BIST Tüm (EA)" : "S&P 500", S.m === "BIST" ? "eşit ağırlıklı ortalama" : "endeks", "Anormal getiri = hisse getirisi − kıyas getirisi, olaydan önceki kapanıştan")}
      ${k(`Tüm olaylar · ${S.h} seans`, `<span class="${cls(h)}">${pc(h?.m, 2)}</span>`, h?.se != null ? `%95: ${pc(h.m - 1.96 * h.se)} … ${pc(h.m + 1.96 * h.se)}` : "")}
      ${k("Veri başlangıcı", S.first ? fmt.date(S.first, { day: "numeric", month: "short", year: "numeric" }) : "—", "en eski olay (kâr payı kararları daha eski); KAP bildirimleri 90 gün geriden başlar, birikerek uzar")}
    </div>`;
  }

  function cell(s, h) {
    if (!s) return `<td class="num t3 hz${h}">—</td>`;
    const lo = s.se != null ? s.m - 1.96 * s.se : null, hi = s.se != null ? s.m + 1.96 * s.se : null;
    const R = h === 20 ? 12 : h === 5 ? 6 : 3, X = v => (50 + Math.max(-R, Math.min(R, v)) / R * 50).toFixed(1);
    const bar = lo != null ? `<span class="ok-ci" aria-hidden="true"><i class="ok-ci0"></i><i class="ok-cir" style="left:${X(lo)}%;width:${(X(hi) - X(lo)).toFixed(1)}%"></i><i class="ok-cid ${cls(s)}" style="left:${X(s.m)}%"></i></span>` : "";
    return `<td class="num ok-c hz${h}" data-tip="${esc(`ortalama ${pc(s.m, 2)}${lo != null ? ` · %95 aralık ${pc(lo, 2)} … ${pc(hi, 2)}` : ""} · olumlu getiri payı %${fmt.num(s.hit * 100, 0)} · n=${s.n}`)}"><b class="${cls(s)}">${pc(s.m)}</b>${bar}<span class="t3 ok-n">n=${fmt.int(s.n)}</span></td>`;
  }

  function table(a) {
    const key = { n: o => o.n, type: o => lab(o.type), h: o => o["h" + S.h]?.m ?? -1e9, pre: o => o.pre?.m ?? -1e9 }[S.sort];
    const list = [...a.list].filter(o => o.n >= 5).sort((x, y) => { const p = key(x), q = key(y); return (p < q ? 1 : p > q ? -1 : 0) * S.sdir; });
    const th = (k, l, tip = "", num = true) => `<th scope="col" class="${num ? "num" : ""}" ${tip ? `data-tip="${esc(tip)}"` : ""}><button type="button" class="th-sort" data-k="${k}">${l}${S.sort === k ? (S.sdir > 0 ? " ↓" : " ↑") : ""}</button></th>`;
    const row = o => `<tr class="${S.sel === o.type ? "is-sel" : ""}" data-t="${esc(o.type)}">
      <td><b>${esc(lab(o.type))}</b>${o.type === "*" ? "" : `<span class="t3 ok-sub">${fmt.int(o.syms)} hisse</span>`}</td>
      <td class="num">${fmt.int(o.n)}</td>${cell(o.h1, 1)}${cell(o.h5, 5)}${cell(o.h20, 20)}
      <td class="num ${o.pre && Math.abs(o.pre.m) > 1.5 ? "warn-t" : "t3"}" data-tip="Olaydan önceki 5 seansta kıyasa göre fark. Büyükse olay öncesinde bilgi fiyata girmiş olabilir ya da olay fiyat hareketinin sonucudur (ör. devre kesici).">${pc(o.pre?.m)}</td></tr>`;
    const few = a.list.filter(o => o.n < 5).length;
    return `<section class="card card-flush" aria-labelledby="okTbT">
      <div class="card-head"><h2 class="card-title" id="okTbT">Olay tipine göre anormal getiri</h2><span class="card-meta">satıra tıkla: yol grafiği ve son olaylar${few ? ` · ${few} tip 5 olaydan az, gizli` : ""}</span></div>
      <div class="tbl-scroll"><table class="tbl ok-tbl" data-h="${S.h}"><thead><tr>${th("type", "Olay tipi", "", false)}${th("n", "Olay")}<th class="num hz1">1 seans</th><th class="num hz5">5 seans</th><th class="num hz20">20 seans</th>${th("pre", "Öncesi (5)")}</tr></thead>
      <tbody>${row(a.all)}${list.map(row).join("")}</tbody></table></div>
      <p class="card-foot ok-foot">"Tüm olaylar" Borsa tedbirlerini (çoğu devre kesici: fiyat hareketinin sonucu) içermez. Renk yalnız %95 aralık sıfırı dışarıda bırakınca: <span class="up">yeşil</span> kıyastan iyi, <span class="down">kırmızı</span> kötü. Aralıklar olay gününe göre kümelenmiş: piyasanın genel düştüğü bir günde onlarca olay tek bir gözlem gibi ağırlık taşır. Sıralama: ${S.h} seans.</p>
    </section>`;
  }

  function pathChart() {
    const P = S.doc.paths || {}, k = d => P[`${S.m}|${S.sel}|${d}`];
    const ser = S.dir === "all" ? [["pos", "Olumlu", "up"], ["neg", "Olumsuz", "down"], ["all", "Tümü", "acc"]].filter(([d]) => k(d)) :
      S.dir === "pos" || S.dir === "neg" ? [[S.dir, DIRS[S.dir], S.dir === "pos" ? "up" : "down"]].filter(([d]) => k(d)) : [];
    const head = `<div class="k-ev-h"><h3 class="d-sub k-sub" style="margin:0">${esc(lab(S.sel))}: olaydan sonra ortalama yol</h3><span class="card-meta">${S.m === "BIST" ? "BIST Tüm'e (eşit ağırlıklı)" : "S&P 500'e"} göre · son 1 yıl, tüm hisseler</span></div>`;
    const show = S.dir === "all" ? ser.filter(([d]) => d !== "all").length ? ser.filter(([d]) => d !== "all") : ser : ser;
    if (!show.length) return `<section class="k-ev">${head}<p class="k-note">Bu seçim için yol grafiği yok (yön başına en az 20 olay gerekir${S.dir === "zero" ? "; yönsüz olaylar için çizilmez" : ""}).</p></section>`;
    const W = 860, H = 272, Pd = { l: 48, r: 104, t: 14, b: 44 }, N = 20;
    const vals = show.flatMap(([d]) => [...k(d).lo, ...k(d).hi]).concat(0);
    let y0 = Math.min(...vals), y1 = Math.max(...vals); const pad = (y1 - y0) * 0.08 || 1; y0 -= pad; y1 += pad;
    const X = i => Pd.l + i / N * (W - Pd.l - Pd.r), Y = v => Pd.t + (y1 - v) / (y1 - y0) * (H - Pd.t - Pd.b);
    const step = (y1 - y0) > 16 ? 4 : (y1 - y0) > 8 ? 2 : (y1 - y0) > 4 ? 1 : 0.5, ticks = []; for (let t = Math.ceil(y0 / step) * step; t <= y1; t += step) ticks.push(+t.toFixed(2));
    const line = a => a.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join("");
    const band = s => `M${s.hi.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join("L")}L${s.lo.map((v, i) => [i, v]).reverse().map(([i, v]) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join("L")}Z`;
    const lbls = show.map(([d, l, c]) => { const s = k(d), j = s.m.length - 1; return { y: Y(s.m[j]), x: X(j), t: `${l} ${pc(s.m[j])}`, c }; }).sort((a, b) => a.y - b.y);
    if (lbls.length === 2 && lbls[1].y - lbls[0].y < 14) { lbls[0].y -= 7; lbls[1].y += 7; }
    const hov = Array.from({ length: N + 1 }, (_, i) => { const tip = `<b>${i}. seans</b>` + show.map(([d, l]) => { const s = k(d); return s.m[i] != null ? `<br>${l}: ${pc(s.m[i], 2)} <span class='t3'>(%95: ${pc(s.lo[i])} … ${pc(s.hi[i])} · n=${s.n[i]})</span>` : ""; }).join("");
      return `<rect x="${X(i) - (W - Pd.l - Pd.r) / N / 2}" y="${Pd.t}" width="${(W - Pd.l - Pd.r) / N}" height="${H - Pd.t - Pd.b}" class="k-ev-hit" data-tip="${esc(tip)}"/>`; }).join("");
    const filt = sh.mine || S.strong || S.days !== 365;
    return `<section class="k-ev">${head}
      <svg viewBox="0 0 ${W} ${H}" class="k-ev-svg" role="img" aria-label="${esc(lab(S.sel))} olaylarından sonraki 20 seans boyunca kıyasa göre ortalama getiri">
        ${ticks.map(t => `<line x1="${Pd.l}" x2="${W - Pd.r}" y1="${Y(t)}" y2="${Y(t)}" class="${t === 0 ? "z" : "g"}"/><text x="${Pd.l - 6}" y="${Y(t) + 4}" text-anchor="end">${t > 0 ? "+" : ""}${fmt.num(t, step < 1 ? 1 : 0)}%</text>`).join("")}
        ${[0, 1, 5, 10, 15, 20].map(i => `<text x="${X(i)}" y="${H - Pd.b + 16}" text-anchor="middle">${i}</text>`).join("")}
        <text x="${(W - Pd.r + Pd.l) / 2}" y="${H - 4}" text-anchor="middle" class="ax">olaydan sonraki seans</text>
        ${show.map(([d, , c]) => `<path d="${band(k(d))}" class="band ${c}"/>`).join("")}
        ${show.map(([d, , c]) => `<path d="${line(k(d).m)}" class="ln ${c}"/>`).join("")}
        ${show.map(([d, , c]) => [1, 5, 20].filter(i => k(d).m[i] != null).map(i => `<circle cx="${X(i)}" cy="${Y(k(d).m[i])}" r="3.5" class="pt ${c}"/>`).join("")).join("")}
        ${lbls.map(l => `<text x="${l.x + 8}" y="${l.y + 4}" class="lbl ${l.c}">${esc(l.t)}</text>`).join("")}
        ${hov}
      </svg>
      <p class="k-note">Gölge: %95 aralık (gün kümelenmiş). Yön, AI sınıflandırıcıdan ya da kuraldan gelir (ör. gerçekleşen geri alım olumlu, kâr payı dağıtmama olumsuz; finansal raporda reel net kârın geçen yılın aynı çeyreğine göre sürprizi); yönsüz olaylar "Tümü" çizgisine girer.${filt ? " Yol grafiği seçili dönem, Benimkiler ve güçlü süzgecinden bağımsız: son 1 yılın bütün olayları." : ""}</p></section>`;
  }

  function recent(rows) {
    const rs = rows.filter(r => (S.sel === "*" || r.type === S.sel) && r.title).slice(0, S.limit);
    if (!rs.length) return "";
    const dd = d => d > 0 ? `<span class="up" aria-label="olumlu">▲</span>` : d < 0 ? `<span class="down" aria-label="olumsuz">▼</span>` : `<span class="t3" aria-label="yönsüz">●</span>`;
    const v = x => x == null ? `<td class="num t3">—</td>` : `<td class="num ${x > 0 ? "up" : x < 0 ? "down" : ""}">${pc(x)}</td>`;
    const more = rows.filter(r => (S.sel === "*" || r.type === S.sel) && r.title).length > S.limit;
    return `<section class="card card-flush" aria-labelledby="okRcT">
      <div class="card-head"><h2 class="card-title" id="okRcT">Son olaylar · ${esc(lab(S.sel))}</h2><span class="card-meta">yalnız son ${fmt.int(800)} olayın başlığı saklanır</span></div>
      <div class="tbl-scroll"><table class="tbl ok-rc"><thead><tr><th>Tarih</th><th>Hisse</th><th>Olay</th><th class="num">1</th><th class="num">5</th><th class="num">20</th></tr></thead><tbody>
      ${rs.map(r => `<tr><td class="mono t3">${esc(r.ts.slice(5, 16).replace("-", "."))}</td>
        <td><b>${esc(r.sym)}</b> <button type="button" class="tk-pi tk-open" data-sym="${esc(r.sym)}" aria-label="${esc(r.sym)} hisse paneli">◧</button></td>
        <td class="ok-tt">${dd(r.dir)} ${r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title)}</a>` : esc(r.title)}<span class="t3 ok-sub">${esc(lab(r.type))}${r.sub ? " · " + esc(r.sub) : ""}</span></td>
        ${v(r.a1)}${v(r.a5)}${v(r.a20)}</tr>`).join("")}</tbody></table></div>
      ${more ? `<p class="card-foot"><button type="button" class="link-btn" id="okMore">Daha fazla göster</button></p>` : ""}
    </section>`;
  }

  function method() {
    return `<details class="card br-meth"><summary class="card-title">Yöntem ve sınırlar</summary><ul>
      <li><b>Olaylar.</b> KAP bildirimlerinin tamamı (idari ve rutin bildirimler hariç), panelin haber ve sinyal akışı, aracı kurum notlarının kamuya açık özetleri, gerçekleşen geri alımlar ve kâr payı kararları tek tabloda. Aynı gün aynı hisse için başlığı neredeyse aynı olaylar (aynı haberin birkaç kaynağı, konsolide + solo rapor) tek olay sayılır.</li>
      <li><b>Getiri.</b> Olaydan önceki son kapanıştan 1, 5 ve 20 seans sonraki kapanışa; seans dışı olaylar sonraki seanstan başlar. BIST'te kıyas eşit ağırlıklı BIST Tüm: dönemde küçük ve orta hisseler XU100'den belirgin zayıf kaldığı için XU100'e göre fark her olayı olumsuz gösterirdi. Yahoo'da düzeltilmemiş bölünme/bedelsiz izi taşıyan pencereler dışarıda.</li>
      <li><b>Bilanço sürprizi.</b> Analist konsensüsü ücretsiz ve lisanslı olmadığından beklenti = geçen yılın aynı çeyreğinin reel (TÜFE ile düzeltilmiş) net kârı. Sürpriz, farkın son dört çeyreğin ortalama kâr büyüklüğüne oranı; +0,2 üstü olumlu, −0,2 altı olumsuz. Aynı gün yayımlanan faaliyet raporu ve konsolide/solo rapor aynı yönü alır.</li>
      <li><b>Belirsizlik.</b> %95 aralık olay gününe göre kümelenmiş standart hatayla. Geri alım gibi ardışık günlerde tekrarlanan bildirimlerde pencereler çakışır; aralık yine de biraz dar kalabilir.</li>
      <li><b>Okuma.</b> Bu geçmişin ortalaması, bir alım-satım kuralı değil. İşlem maliyeti, likidite ve açılış boşluğu yok sayılır. ABD tarafında yalnız izlenen hisseler var (seçim yanlılığı: izlenen hisseler son dönemin güçlü hisseleri olabilir). "Öncesi (5)" sütunu büyükse olay, fiyat hareketinin sonucu olabilir (ör. devre kesici).</li>
      <li><b>Kaynak.</b> Fiyat: Yahoo Finance (kişisel kullanım). Veri saatlik güncellenir; KAP geçmişi 90 gün geriye dolduruldu ve birikerek uzar.</li></ul></details>`;
  }

  function render() {
    const rows = filtered(), a = agg(rows);
    if (S.sel !== "*" && !a.list.some(o => o.type === S.sel)) S.sel = "*";
    $("#okBody").innerHTML = `${controls()}${kpis(rows, a)}${rows.length ? table(a) + pathChart() + recent(rows) : sh.stateHTML({ kind: "empty", title: "Bu süzgeçle olay yok", msg: sh.mine ? "Benimkiler açık: izleme listesi ve portföy hisselerinde bu dönemde olay yok." : "" })}${method()}
      <p class="src-line">Kaynak: KAP, panel akışı, aracı kurum duyuruları, kap-geri-alim-takibi · fiyat Yahoo · ${fmt.date(S.doc.generated, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</p>`;
    bind();
  }

  function bind() {
    const segB = (id, f) => { $$(`#${id} button`).forEach(b => b.onclick = () => { f(b.dataset.v); render(); }); sh.radioKeys($(`#${id}`)); };
    segB("okM", v => { S.m = v; S.sel = "*"; S.limit = 40; });
    segB("okP", v => { S.days = +v; S.limit = 40; });
    segB("okD", v => { S.dir = v; S.limit = 40; });
    segB("okH", v => { S.h = +v; S.sort = "h"; S.sdir = 1; });
    $("#okStrong").onclick = () => { S.strong = !S.strong; render(); };
    $$("#okBody .th-sort").forEach(b => b.onclick = () => { const k = b.dataset.k; S.sdir = S.sort === k ? -S.sdir : (k === "type" ? -1 : 1); S.sort = k; render(); });
    $$("#okBody .ok-tbl tbody tr").forEach(tr => tr.onclick = () => { S.sel = tr.dataset.t; S.limit = 40; render(); $(".k-ev")?.scrollIntoView({ block: "nearest", behavior: "smooth" }); });
    $("#okMore")?.addEventListener("click", () => { S.limit += 60; render(); });
  }

  function exportCSV() {
    const ex = window.radarExport, a = agg(filtered());
    const out = [a.all, ...a.list].map(o => ({ olay_tipi: lab(o.type), olay: o.n, hisse: o.syms,
      ...Object.fromEntries([1, 5, 20].flatMap(h => [[`ort_${h}s`, o["h" + h]?.m?.toFixed(3)], [`se_${h}s`, o["h" + h]?.se?.toFixed(3)], [`n_${h}s`, o["h" + h]?.n]])),
      oncesi_5s: o.pre?.m?.toFixed(3), pazar: S.m, donem_gun: S.days, yon: DIRS[S.dir], guclu: S.strong ? "evet" : "", benimkiler: sh.mine ? "evet" : "" }));
    ex.download(`olay_karnesi_${S.m}_${S.days}g_${ex.stamp()}.csv`, ex.toCSV(out), "text/csv;charset=utf-8");
  }

  addEventListener("minechange", () => { if (sh.route === "olay-karnesi" && S.loaded) render(); });
  sh.register("olay-karnesi", {
    onShow() { S.loaded ? render() : S.error ? renderError() : load(); },
    async refresh() { await load(true); },
    exports: () => [{ label: "Olay tipleri (CSV)", hint: `${S.m} · ${PERIODS[S.days]} · süzgece göre`, run: exportCSV, disabled: !S.loaded }],
    exportNote: "Olay karnesi henüz yüklenmedi",
  });
})();
