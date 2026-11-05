/* Lyra Radar — Araştırma sekmesi.
   Veri: data/research.json (pipeline: radar/research.py)
   - synthesis: günlük AI sentezi (aracı kurum notları + kurum görünümleri + makro gelişmeler)
   - outlooks: J.P. Morgan Guide to the Markets, BlackRock haftalık yorum özetleri
   - notes: aracı kurum notları (kamuya duyurulan başlıklardan: kurum, hisse, tavsiye, hedef fiyat)
   - consensus: izleme listesi için kurum başına son not üzerinden medyan hedef ve tavsiye dağılımı */
(() => {
  "use strict";
  const sh = window.shell;
  const { $, $$, esc, fmt, store } = sh;
  const S = { data: null, loaded: false, error: null, scope: store.get("radar.resScope", "watch"), q: "", limit: 30,
    tab: store.get("radar.resTab", "ozet"), win: 30, kind: "", broker: "", thin: false };
  const TABS = { ozet: "Özet", strateji: "Strateji", notlar: "Hisse notları", gorunum: "Kurum görünümleri" };
  if (!TABS[S.tab]) S.tab = "ozet";
  const RAT = { AL: "up", SAT: "down", TUT: "flat" };
  const ACT = { up: "▲ yükseltti", down: "▼ düşürdü", init: "kapsama başladı", keep: "korudu", set: "belirledi", add: "model portföye ekledi", remove: "model portföyden çıkardı" };
  const STANCE = { olumlu: "up", olumsuz: "down", "nötr": "flat", "karışık": "" };

  async function load() {
    try {
      const r = await fetch(`data/research.json?t=${Date.now()}`);
      if (!r.ok) throw new Error(`data/research.json okunamadı (HTTP ${r.status})`);
      S.data = await r.json(); S.error = null;
      if (!window.radar?.state?.macro) S.macro = await fetch(`data/macro.json?t=${Date.now()}`).then(x => x.ok ? x.json() : null).catch(() => null);
    } catch (e) { S.error = e; }
    S.loaded = true;
    if (S.data) sh.setUpdated("arastirma", S.data.generated, { label: "Araştırma güncellendi", staleMin: 120 });
    if (sh.route === "arastirma") render();
  }
  const watch = () => { if (sh.mine) return sh.mineSet(); const wl = window.radar?.state?.feed?.watchlist; return new Set(wl ? wl.map(w => w.symbol) : Object.keys(S.data?.consensus || {})); };
  const scope = () => sh.mine ? "watch" : S.scope;            // üst çubuktaki "Benimkiler" açıksa her zaman izleme listesi + portföy
  const inMarket = n => sh.market === "ALL" || n.m === sh.market;
  const CUR = { USD: " $", TRY: " ₺", EUR: " €" };
  // "Google News" yerine başlıktaki yayın adı (… - Investing.com Türkiye)
  const srcName = n => { const m = (n.title || "").match(/\s-\s([^-]{2,30})$/); return n.src === "Google News" && m ? m[1].replace(/ Türkiye$/, "") : n.src; };
  const price = t => window.radarResearch?.prices?.[t]?.last || window.radarFundamentals?.row?.(t)?.price || null;
  // Reel potansiyel eşiği (TL hedefleri için): 12 ay sonrası TÜFE beklentisi (TCMB Piyasa Katılımcıları Anketi), yoksa TCMB fonlama faizi
  const HURDLE = [["TP.PKAUO.S01.E.U", "12 ay sonrası TÜFE beklentisi (TCMB Piyasa Katılımcıları Anketi)", "enflasyon beklentisi"],
    ["TP.APIFON4", "TCMB ağırlıklı ortalama fonlama maliyeti (yıllık)", "politika faizi"]];
  function hurdle() {
    const ser = (window.radar?.state?.macro || S.macro)?.series || [];
    for (const [code, name, short] of HURDLE) { const x = ser.find(s => s.code === code); if (x?.last != null) return { v: x.last / 100, name, short, date: x.date }; }
    return null;
  }

  function synthesisCard(s) {
    if (!s) return `<section class="card"><h2 class="card-title">Sentez</h2><p class="tp-empty">Henüz sentez yok. Yeterli not ve görünüm biriktiğinde günde bir üretilir.</p></section>`;
    const list = (title, xs) => xs?.length ? `<p class="d-sub">${title}</p><ul class="res-list">${xs.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
    return `<section class="card res-syn" aria-labelledby="resSynT">
      <div class="card-head"><h2 class="card-title" id="resSynT">Sentez · son 7 gün</h2>
        <span class="card-meta">${fmt.ago(s.generated, true)} · ${s.inputs ? `${s.inputs.notes} kurum notu, ${s.inputs.outlooks} görünüm, ${s.inputs.macro} makro gelişme` : ""}</span></div>
      <p class="res-head">${esc(s.headline)}</p>
      <p class="d-sum">${esc(s.summary)}</p>
      <div class="res-cols">
        <div>${list("Kurumların hemfikir olduğu", s.consensus)}</div>
        <div>${list("Ayrıştıkları", s.divergences)}</div>
      </div>
      ${s.watchlist?.length ? `<p class="d-sub">İzleme listesi için</p><table class="tx res-wl"><tbody>${s.watchlist.map(w => `
        <tr><td><button type="button" class="tk-link" data-sym="${esc(w.ticker)}">${esc(w.ticker)}</button></td>
        <td><span class="${STANCE[w.stance] ?? ""}">${esc(w.stance)}</span></td><td>${esc(w.why)}</td></tr>`).join("")}</tbody></table>` : ""}
      <div class="res-cols">
        <div>${list("Riskler", s.risks)}</div>
        <div>${list("İzlenecekler", s.watch_next)}</div>
      </div>
      <p class="card-foot">AI sentezi; kurumların görüşlerini özetler, yatırım tavsiyesi değildir. Dayandığı notlar ve görünümler aşağıda · ${window.radarMethod?.link("arastirma") || ""}</p>
    </section>`;
  }

  // Kullanıcının gizli rapor kutusundan okunan raporlar (yalnız yapılandırılmış alanlar ve kısa tez)
  const KIND_TR = { sirket: "Şirket", sektor: "Sektör", strateji: "Strateji" };
  const VIEW = { olumlu: "up", olumsuz: "down", "nötr": "flat" };
  function outlookCard(os) {
    return `<section class="card" aria-labelledby="resOutT">
      <div class="card-head"><h2 class="card-title" id="resOutT">Kurum görünümleri</h2><span class="card-meta">J.P. Morgan Guide to the Markets (çeyreklik) · BlackRock haftalık yorum</span></div>
      ${os?.length ? os.slice(0, 10).map(o => `<article class="res-out">
        <p class="res-out-h"><b>${esc(o.house)}</b> · ${esc(o.title)} <span class="t3">· ${fmt.date(o.ts)}</span>
          ${o.url ? `<a href="${esc(o.url)}" target="_blank" rel="noopener">Belge ↗</a>` : ""}</p>
        ${o.summary ? `<p class="d-sum">${esc(o.summary)}</p>` : ""}
        ${o.key_points?.length ? `<ul class="res-list">${o.key_points.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
        ${o.risks?.length ? `<p class="doc-risks"><b>Riskler:</b> ${o.risks.map(esc).join(" · ")}</p>` : ""}
      </article>`).join("") : `<p class="tp-empty">Henüz görünüm özeti yok; yeni sayı yayımlandığında eklenir.</p>`}
    </section>`;
  }

  function consensusCard(c) {
    const rows = Object.entries(c || {}).filter(([t]) => sh.market === "ALL" || (window.radarResearch?.prices?.[t]?.market || "BIST") === sh.market);
    if (!rows.length) return "";
    return `<section class="card" aria-labelledby="resConT">
      <div class="card-head"><h2 class="card-title" id="resConT">İzleme listesi · kurum konsensüsü</h2><span class="card-meta">her kurumun son notu · 120 gün</span></div>
      <table class="tx"><thead><tr><th>Hisse</th><th class="num">Kurum</th><th>Dağılım</th><th class="num">Medyan hedef</th><th class="num">Potansiyel</th></tr></thead><tbody>${rows.map(([t, x]) => {
        const p = price(t), up = x.median_tp && p ? (x.median_tp / p - 1) * 100 : null;
        return `<tr><td><button type="button" class="tk-link" data-sym="${esc(t)}">${esc(t)}</button></td><td class="num">${fmt.int(x.n)}</td>
          <td><span class="up">${x.dist.AL} AL</span> · ${x.dist.TUT} TUT · <span class="down">${x.dist.SAT} SAT</span></td>
          <td class="num">${x.median_tp ? fmt.num(x.median_tp, 2) : "—"}</td><td class="num">${up == null ? "—" : `<span class="${up > 0 ? "up" : "down"}">${fmt.pct(up)}</span>`}</td></tr>`;
      }).join("")}</tbody></table>
    </section>`;
  }

  // Hedef fiyat haritası: her hissede son 90 günde her kurumun SON hedefi bir nokta (güncel fiyata göre potansiyel),
  // dikey çizgi medyan; izleme listesinde Yahoo analist hedef aralığı (en düşük–en yüksek) açık şerit olarak.
  function targetMap(notes) {
    const w = watch(), cut = Date.now() - 90 * 864e5, last = new Map();
    for (const n of (notes || []).filter(inMarket)) {
      if (!n.t || !n.tp || Date.parse(n.ts) < cut || (scope() === "watch" && !w.has(n.t))) continue;
      const k = `${n.t}|${n.broker}`, o = last.get(k);
      if (!o || Date.parse(n.ts) > Date.parse(o.ts)) last.set(k, n);
    }
    const by = new Map();
    for (const n of last.values()) { if (!by.has(n.t)) by.set(n.t, []); by.get(n.t).push(n); }
    let rows = [...by].map(([t, xs]) => { const p = price(t); if (!p) return null;
      const pots = xs.map(n => ({ n, v: n.tp / p - 1 })).filter(o => o.v > -0.9 && o.v < 5).sort((a, b) => a.v - b.v);
      if (!pots.length) return null;
      const med = pots[Math.floor((pots.length - 1) / 2)].v + (pots.length % 2 ? 0 : (pots[pots.length / 2].v - pots[pots.length / 2 - 1].v) / 2);
      const an = window.radar?.state?.prices?.[t]?.analyst?.targets;
      return { t, p, pots, med, yr: an?.low && an?.high ? [an.low / p - 1, an.high / p - 1] : null };
    }).filter(Boolean).sort((a, b) => b.pots.length - a.pots.length || b.med - a.med);
    if (!rows.length) return "";
    const total = rows.length; rows = rows.slice(0, S.tmAll ? 80 : 14);
    const LO = -0.4, HI = 1.2, X = v => ((Math.max(LO, Math.min(HI, v)) - LO) / (HI - LO) * 100).toFixed(2);
    const col = r => r === "AL" ? "var(--up)" : r === "SAT" ? "var(--down)" : "var(--text-3)";
    const ticks = [-0.4, -0.2, 0, 0.2, 0.4, 0.6, 0.8, 1, 1.2];
    return `<section class="card" aria-labelledby="resTmT"><div class="card-head"><h2 class="card-title" id="resTmT">Hedef fiyat haritası</h2>
        <span class="card-meta">son 90 gün · her kurumun son hedefi · güncel fiyata göre potansiyel</span></div>
      <div class="rt-axis"><span></span><div class="rt-scale">${ticks.map(v => `<i style="left:${X(v)}%">${v === 0 ? "fiyat" : `${v > 0 ? "+" : "−"}%${Math.abs(v * 100)}`}</i>`).join("")}</div><span></span></div>
      ${rows.map(r => `<div class="rt-row"><button type="button" class="tk-link mono" data-sym="${esc(r.t)}">${esc(r.t)}</button>
        <div class="rt-track"><i class="rt-zero" style="left:${X(0)}%"></i>${r.yr ? `<i class="rt-yr" style="left:${X(r.yr[0])}%;width:${X(r.yr[1]) - X(r.yr[0])}%" data-tip="Yahoo analist hedef aralığı: ${fmt.pct(r.yr[0] * 100, 0)} … ${fmt.pct(r.yr[1] * 100, 0)}"></i>` : ""}
          <i class="rt-med" style="left:${X(r.med)}%" data-tip="Medyan potansiyel ${fmt.pct(r.med * 100, 0)}"></i>
          ${r.pots.map(o => `<i class="rt-dot" style="left:${X(o.v)}%;background:${col(o.n.rating)}" data-tip="${esc(`${o.n.broker} · ${o.n.rating || "—"} · hedef ${fmt.num(o.n.tp, 2)} (${fmt.pct(o.v * 100, 0)}) · ${fmt.date(o.n.ts)}`)}"></i>`).join("")}</div>
        <span class="rt-v ${r.med > 0 ? "up" : "down"}">${fmt.pct(r.med * 100, 0)} <small class="t3">${r.pots.length} kurum</small></span></div>`).join("")}
      <p class="t3 gc-foot"><span class="rt-key"><i style="background:var(--up)"></i>AL <i style="background:var(--text-3)"></i>TUT <i style="background:var(--down)"></i>SAT <i class="rt-k-med"></i>medyan <i class="rt-k-yr"></i>Yahoo analist aralığı</span>
        ${total > rows.length || S.tmAll ? ` · <button type="button" class="link-btn" id="resTmAll">${S.tmAll ? "En çok kapsananlar" : `Tümü (${total})`}</button>` : ""} · −%40 ve +%120 dışı kenarda gösterilir.</p></section>`;
  }

  function notesCard(notes) {
    const w = watch();
    let xs = (notes || []).filter(inMarket);
    if (scope() === "watch") xs = xs.filter(n => w.has(n.t));
    if (S.q) xs = xs.filter(n => sh.match(`${n.t || ""} ${n.name || ""} ${n.broker} ${n.title}`, S.q));
    const shown = xs.slice(0, S.limit), H = hurdle();
    return `<section class="card card-flush" aria-labelledby="resNotT">
      <div class="card-head"><h2 class="card-title" id="resNotT">Aracı kurum notları</h2>
        <span class="card-meta">${fmt.int(xs.length)} not · kamuya duyurulan başlıklardan (AA, Bloomberg HT, Foreks, Yahoo…) çıkarılır, raporların kendisi okunmaz</span></div>
      ${shown.length ? `<div class="res-tw"><table class="tx res-notes"><thead><tr><th>Tarih</th><th>Hisse</th><th class="num">Hedef</th>
        <th class="num" data-tip="Hedef ÷ güncel fiyat">Potansiyel</th>
        <th class="num" data-tip="${esc(H ? `TL hedeflerde: (1 + potansiyel) ÷ (1 + ${H.name} %${fmt.num(H.v * 100, 1)}) − 1. Negatifse hedef, ${H.short} kadar bile getiri vaat etmiyor.` : "Eşik verisi yok")}">${H ? (H.short === "enflasyon beklentisi" ? "Reel" : "Faiz üstü") : "Reel"}</th>
        <th>Tavsiye</th><th>Değişim</th><th>Kurum</th><th>Kaynak</th></tr></thead><tbody>${shown.map(n => { const px = n.t ? price(n.t) : null, pot = n.tp && px ? n.tp / px - 1 : null,
          rev = n.tp && n.prev && n.prev !== n.tp ? n.tp / n.prev - 1 : null, real = pot != null && H && (n.cur || "TRY") === "TRY" && n.m !== "US" ? (1 + pot) / (1 + H.v) - 1 : null;
          const pc = v => fmt.pct(v * 100, Math.abs(v) < 0.01 ? 1 : 0); return `
        <tr><td>${fmt.date(n.ts)}</td><td>${n.t ? `<button type="button" class="tk-link" data-sym="${esc(n.t)}">${esc(n.t)}</button>` : esc(n.name || "—")}</td>
        <td class="num">${n.tp ? fmt.num(n.tp, 2) + (CUR[n.cur] || "") : "—"}${n.prev && n.tp && n.prev !== n.tp ? `<span class="t3" data-tip="önceki hedef"> ← ${fmt.num(n.prev, 2)}</span>` : ""}</td>
        <td class="num">${pot == null ? "—" : `<span class="${pot > 0 ? "up" : "down"}" data-tip="fiyat ${fmt.num(px, 2)}">${pc(pot)}</span>`}</td>
        <td class="num">${real == null ? "—" : `<span class="${real > 0 ? "up" : "down"}">${pc(real)}</span>`}</td>
        <td><span class="${RAT[n.rating] || ""}">${esc(n.rating || "—")}</span></td><td>${esc(ACT[n.action] || "")}${rev != null ? ` <span class="${rev > 0 ? "up" : "down"}" data-tip="Yeni hedef ÷ aynı kurumun önceki hedefi">${pc(rev)}</span>` : ""}</td>
        <td>${esc(n.broker)}</td>
        <td>${n.url ? `<a href="${esc(n.url)}" target="_blank" rel="noopener" data-tip="${esc(n.title)}">${esc(srcName(n))} ↗</a>` : esc(srcName(n))}</td></tr>`; }).join("")}</tbody></table></div>
        ${H ? `<p class="res-more t3">${H.short === "enflasyon beklentisi" ? "Reel potansiyel" : "Faiz üstü potansiyel"}: ${esc(H.name)} %${fmt.num(H.v * 100, 1)}${H.date ? ` (${esc(H.date)})` : ""} düşülerek; hedefler genelde 12 aylıktır. Fiyat: izleme listesinde canlı, diğerlerinde temel analizdeki son kapanış.</p>` : ""}
        ${xs.length > shown.length ? `<p class="res-more"><button type="button" class="link-btn" id="resMore">${Math.min(30, xs.length - shown.length)} not daha göster</button></p>` : ""}`
        : `<p class="tp-empty res-pad">Bu filtrede not yok.</p>`}
    </section>`;
  }

  // ─────────────────────────────── Strateji sekmesi (rapor kutusundaki strateji / sektör / şirket raporlarından)
  const DAY = 864e5, dayKey = t => (t || "").slice(0, 10);
  const SENT = { bullish: ["olumlu", "up"], bearish: ["olumsuz", "down"], neutral: ["nötr", "flat"] };
  const sentOf = r => r.sentiment || ({ olumlu: "bullish", olumsuz: "bearish", "nötr": "neutral" })[r.view] || null;
  const repDate = r => r.date || dayKey(r.ts);
  const reports = () => (S.data?.reports || []).filter(r => sh.market === "ALL" || (r.cur === "USD" ? "US" : "BIST") === sh.market);
  function feedStatus(rs) {
    if (!rs.length) return `<p class="rs-status t3">Rapor kutusunda henüz rapor yok. Raporları rapor@ adresine ilet; konu satırına [şirket], [sektör] ya da [strateji] yazarsan tür o olur.</p>`;
    const last = rs.reduce((m, r) => (r.ts > m ? r.ts : m), ""), wk = rs.filter(r => Date.now() - Date.parse(r.ts) < 7 * DAY);
    const age = (Date.now() - Date.parse(last)) / 36e5, wd = new Date().getDay(), stale = age > 48 && wd > 0 && wd < 6;
    const by = k => wk.filter(r => r.type === k).length;
    return `<p class="rs-status ${stale ? "warn" : ""}"><span class="rs-dot" aria-hidden="true"></span>Rapor kutusu: son rapor <b>${fmt.ago(last)}</b> · bu hafta ${wk.length} rapor
      (${by("strateji")} strateji, ${by("sektor")} sektör, ${by("sirket")} şirket)${stale ? ` · <b>2 günden uzun süredir yeni rapor gelmedi</b>; rapor@ iletimini kontrol et` : ""}</p>`;
  }
  // Kurum görüşü zaman çizelgesi: satır = kurum, sütun = gün (son 30 gün), renk = piyasaya/sektöre bakış
  function viewTimeline(rs) {
    const N = 30, end = new Date(dayKey(new Date().toISOString()) + "T12:00:00Z"), days = [...Array(N)].map((_, i) => new Date(end - (N - 1 - i) * DAY).toISOString().slice(0, 10));
    const xs = rs.filter(r => r.type !== "sirket" && !r.thin && sentOf(r) && r.broker !== "Kurum belirtilmemiş" && repDate(r) >= days[0]);
    if (xs.length < 2) return "";
    const by = new Map();
    xs.forEach(r => { if (!by.has(r.broker)) by.set(r.broker, new Map()); const m = by.get(r.broker), d = repDate(r); (m.get(d) || m.set(d, []).get(d)).push(r); });
    const rows = [...by].sort((a, b) => b[1].size - a[1].size).slice(0, 12);
    const wk = xs.filter(r => repDate(r) >= days[N - 7]), cnt = k => wk.filter(r => sentOf(r) === k).length;
    const cell = (b, d) => { const v = by.get(b).get(d); if (!v) return `<i class="vt-c"></i>`;
      const r = v[v.length - 1], st = SENT[sentOf(r)] || SENT.neutral;
      return `<i class="vt-c ${st[1]}" data-tip="${esc(`${b} · ${fmt.date(d + "T12:00:00Z")} · ${st[0]}${v.length > 1 ? ` (${v.length} rapor)` : ""}<br>${(r.thesis || "").slice(0, 180)}`)}"></i>`; };
    return `<section class="card" aria-labelledby="vtT"><div class="card-head"><h2 class="card-title" id="vtT">Kurumların piyasa görüşü</h2>
        <span class="card-meta">son 30 gün · strateji ve sektör raporları · son 7 günde <span class="up">${cnt("bullish")} olumlu</span>, ${cnt("neutral")} nötr, <span class="down">${cnt("bearish")} olumsuz</span></span></div>
      <div class="vt" style="--n:${N}">${rows.map(([b]) => `<span class="vt-b" title="${esc(b)}">${esc(b)}</span><span class="vt-r">${days.map(d => cell(b, d)).join("")}</span>`).join("")}
        <span></span><span class="vt-r vt-ax">${days.map((d, i) => `<i>${i % 7 === 0 || i === N - 1 ? +d.slice(8) : ""}</i>`).join("")}</span></div>
      <p class="t3 gc-foot"><span class="vt-key"><i class="vt-c up"></i>olumlu <i class="vt-c flat"></i>nötr <i class="vt-c down"></i>olumsuz</span> · kurumun o günkü raporundaki kısa vadeli piyasa/sektör görüşü (AI'ın rapordan çıkardığı) · kutuya gel: tez</p></section>`;
  }
  // En çok öne çıkarılan hisseler: raporlardaki öne çıkanlar + model portföye eklenenler
  function topPicks(rs) {
    const cut = new Date(Date.now() - S.win * DAY).toISOString().slice(0, 10), m = new Map();
    for (const r of rs) {
      if (repDate(r) < cut) continue;
      const add = (t, tp, how) => { t = String(t || "").toUpperCase(); if (!t || /^X[A-Z]{2,4}$/.test(t)) return;
        const o = m.get(t) || { t, b: new Map(), tps: [], last: "" }; o.b.set(r.broker, how); if (tp) o.tps.push(tp); if (repDate(r) > o.last) o.last = repDate(r); m.set(t, o); };
      (r.top_picks || []).forEach(p => add(p.t, p.tp, "öne çıkardı"));
      (r.mp?.added || []).forEach(t => add(t, null, "model portföye ekledi"));
      if (r.type === "sirket" && r.rating === "AL" && r.tickers?.[0]) add(r.tickers[0], r.tp, "AL raporu");
    }
    const rows = [...m.values()].sort((a, b) => b.b.size - a.b.size || b.last.localeCompare(a.last)).slice(0, 15);
    if (!rows.length) return "";
    const mx = Math.max(...rows.map(r => r.b.size)), med = a => { const s = [...a].sort((x, y) => x - y); return s.length ? s[Math.floor((s.length - 1) / 2)] : null; };
    return `<section class="card card-flush" aria-labelledby="tpT"><div class="card-head"><h2 class="card-title" id="tpT">Kurumların öne çıkardığı hisseler</h2>
        <div class="seg seg-sm" role="radiogroup" aria-label="Dönem" id="rsWin">${[[7, "7 gün"], [30, "30 gün"]].map(([v, l]) => `<button type="button" role="radio" data-v="${v}" aria-checked="${S.win === v}">${l}</button>`).join("")}</div></div>
      <div class="tbl-scroll"><table class="tx rs-tp"><thead><tr><th>Hisse</th><th>Kurum sayısı</th><th>Kurumlar</th><th class="num">Medyan hedef</th><th class="num">Potansiyel</th><th class="num">Son</th></tr></thead><tbody>
      ${rows.map(o => { const tp = med(o.tps), p = price(o.t), pot = tp && p ? tp / p - 1 : null;
        return `<tr><td><button type="button" class="tk-link mono" data-sym="${esc(o.t)}">${esc(o.t)}</button></td>
          <td class="nw"><span class="rs-bar"><i style="width:${(o.b.size / mx * 100).toFixed(0)}%"></i></span> <b class="mono">${o.b.size}</b></td>
          <td class="t3 rs-brk">${[...o.b].map(([b, h]) => `<span data-tip="${esc(h)}">${esc(b)}</span>`).join(", ")}</td>
          <td class="num">${tp ? fmt.num(tp, 2) : "—"}</td><td class="num">${pot == null ? "—" : `<span class="${pot > 0 ? "up" : "down"}">${fmt.pct(pot * 100, 0)}</span>`}</td>
          <td class="num t3">${fmt.date(o.last + "T12:00:00Z", { day: "numeric", month: "short" })}</td></tr>`; }).join("")}</tbody></table></div>
      <p class="t3 gc-foot" style="padding:0 var(--s-4) var(--s-3)">Strateji/sektör raporlarında öne çıkarılan, model portföye eklenen ya da şirket raporunda AL verilen hisseler · kurum başına bir kez sayılır.</p></section>`;
  }
  // Ortak temalar: raporlardaki katalizör ve risk başlıklarının konulara göre sayımı (son 14 gün, rapor başına bir kez)
  const THEMES = [["Enflasyon", /enflasyon|tüfe|üfe|fiyat artış/i], ["Faiz / TCMB", /faiz|tcmb|ppk|para politika|sıkı(laş)?ma|gevşe/i],
    ["Fed / ABD faizi", /\bfed\b|fomc|abd faiz|tahvil getiri/i], ["Jeopolitik", /jeopolitik|orta doğu|ortadoğu|savaş|israil|iran|rusya|ukrayna|gerilim/i],
    ["Petrol / emtia", /petrol|brent|emtia|doğalgaz|doğal gaz|altın/i], ["Bilançolar", /bilanço|3ç|çeyrek|kâr|kar marj|finansal sonuç/i],
    ["ABD seçimi / politika", /seçim|kongre|gümrük|tarife/i], ["Büyüme / talep", /pmi|büyüme|gsyh|talep|resesyon|sanayi üretim/i],
    ["Kur / TL", /\bkur\b|\bkurlar|dolar|\btl\b|döviz|usd\/try|türk lirası/i], ["Yabancı akımı", /yabancı|fon akım|portföy akım|msci/i],
    ["Borçlanma / likidite", /borçlanma|hazine|likidite|kredi/i], ["Teknik görünüm", /destek|direnç|teknik|ortalama|hacim/i], ["Yapay zekâ / teknoloji", /yapay zek|\bai\b|teknoloji|çip|yarı iletken/i]];
  function themes(rs) {
    const cut = new Date(Date.now() - 14 * DAY).toISOString().slice(0, 10), xs = rs.filter(r => repDate(r) >= cut && !r.thin);
    const count = key => THEMES.map(([l, rx]) => [l, xs.filter(r => (r[key] || []).some(x => rx.test(x))).length]).filter(x => x[1]).sort((a, b) => b[1] - a[1]).slice(0, 7);
    const c = count("catalysts"), k = count("risks");
    if (!c.length && !k.length) return "";
    const list = (xs, cls) => { const mx = Math.max(...xs.map(x => x[1]), 1); return `<ul class="rs-th">${xs.map(([l, n]) => `<li><span>${esc(l)}</span><span class="rs-bar ${cls}"><i style="width:${(n / mx * 100).toFixed(0)}%"></i></span><b class="mono">${n}</b></li>`).join("")}</ul>`; };
    return `<section class="card" aria-labelledby="thT"><div class="card-head"><h2 class="card-title" id="thT">Ortak temalar</h2><span class="card-meta">son 14 gün · ${xs.length} rapor · kaç raporda geçtiği</span></div>
      <div class="res-cols"><div><p class="d-sub">Katalizörler</p>${list(c, "")}</div><div><p class="d-sub">Riskler</p>${list(k, "neg")}</div></div></section>`;
  }
  function sectorViews(rs) {
    const m = new Map();
    rs.filter(r => r.view && r.sector && !GENERIC.test(r.sector)).forEach(r => { const k = `${r.sector}|${r.broker}`; if (!m.has(k) || repDate(r) > repDate(m.get(k))) m.set(k, r); });
    const xs = [...m.values()].sort((a, b) => repDate(b).localeCompare(repDate(a))).slice(0, 12);
    if (!xs.length) return "";
    return `<section class="card" aria-labelledby="svT"><div class="card-head"><h2 class="card-title" id="svT">Sektör görüşleri</h2><span class="card-meta">her sektör × kurum için son görüş</span></div>
      <table class="tx"><tbody>${xs.map(r => `<tr><th scope="row">${esc(r.sector)}</th><td>${esc(r.broker)}</td><td><span class="tag ${VIEW[r.view] || "na"}">${esc(r.view)}</span></td><td class="num t3">${fmt.date(repDate(r) + "T12:00:00Z", { day: "numeric", month: "short" })}</td></tr>`).join("")}</tbody></table></section>`;
  }
  const GENERIC = /genel|piyasa|strateji|çoklu|makro|global|küresel/i;
  function mpChanges(rs) {
    const xs = rs.filter(r => (r.mp?.added || []).length || (r.mp?.removed || []).length).slice(0, 10);
    if (!xs.length) return "";
    return `<section class="card" aria-labelledby="mpT"><div class="card-head"><h2 class="card-title" id="mpT">Model portföy değişiklikleri</h2></div>
      <ul class="tn-list">${xs.map(r => `<li class="tn-row"><span class="tn-b">${esc(r.broker)}</span>${(r.mp.added || []).map(t => `<span class="up mono">+${esc(t)}</span>`).join(" ")} ${(r.mp.removed || []).map(t => `<span class="down mono">−${esc(t)}</span>`).join(" ")}<span class="td-age">${fmt.date(repDate(r) + "T12:00:00Z", { day: "numeric", month: "short" })}</span></li>`).join("")}</ul></section>`;
  }
  function reportList(rs) {
    const w = watch(), nThin = rs.filter(r => r.thin).length;
    let xs = rs.filter(r => (S.thin || !r.thin) && (!S.kind || r.type === S.kind) && (!S.broker || r.broker === S.broker));
    if (S.q) xs = xs.filter(r => sh.match(`${r.broker} ${(r.tickers || []).join(" ")} ${(r.top_picks || []).map(p => p.t).join(" ")} ${r.sector} ${r.thesis}`, S.q));
    const brs = [...new Set(rs.map(r => r.broker))].sort((a, b) => a.localeCompare(b, "tr"));
    const tk = t => `<button type="button" class="tk-link" data-sym="${esc(t)}">${esc(t)}</button>${w.has(t) ? `<span class="mine-dot">●</span>` : ""}`;
    return `<section class="card" aria-labelledby="rlT"><div class="card-head"><h2 class="card-title" id="rlT">Raporlar</h2>
        <div class="rl-tools"><div class="seg seg-sm" role="radiogroup" aria-label="Tür" id="rsKind">${[["", "Tümü"], ["strateji", "Strateji"], ["sektor", "Sektör"], ["sirket", "Şirket"]].map(([k, l]) => `<button type="button" role="radio" data-v="${k}" aria-checked="${S.kind === k}">${l}</button>`).join("")}</div>
        <select id="rsBroker" class="rl-sel" aria-label="Kurum"><option value="">Tüm kurumlar</option>${brs.map(b => `<option ${S.broker === b ? "selected" : ""}>${esc(b)}</option>`).join("")}</select></div></div>
      ${xs.length ? `<div class="rl">${xs.slice(0, 40).map(r => { const st = SENT[sentOf(r)];
        return `<details class="rl-i"><summary><span class="tag">${KIND_TR[r.type] || "Rapor"}</span><b>${esc(r.broker)}</b>
          <span class="rl-sum">${r.type === "sirket" && r.tickers?.[0] ? `${esc(r.tickers[0])}${r.rating ? ` <span class="${RAT[r.rating] || ""}">${esc(r.rating)}</span>` : ""}${r.tp ? ` · hedef ${fmt.num(r.tp, 2)}${CUR[r.cur] || " ₺"}` : ""}`
            : esc(r.sector && !GENERIC.test(r.sector) ? r.sector : (r.thesis || "").slice(0, 90) + ((r.thesis || "").length > 90 ? "…" : ""))}</span>
          ${st ? `<span class="${st[1]} rl-st">${st[0]}</span>` : ""}${(r.top_picks || []).length ? `<span class="t3">${r.top_picks.length} öne çıkan</span>` : ""}
          <span class="td-age">${fmt.date(repDate(r) + "T12:00:00Z", { day: "numeric", month: "short" })}</span></summary>
          <div class="rl-b">${r.thesis ? `<p class="d-sum">${esc(r.thesis)}</p>` : ""}
            ${(r.top_picks || []).length ? `<p class="tp-sub">Öne çıkanlar: ${r.top_picks.map(p => tk(p.t) + (p.tp ? ` <span class="t3">${fmt.num(p.tp, 2)}</span>` : "")).join(" · ")}</p>` : ""}
            ${(r.tickers || []).length && r.type !== "sirket" ? `<p class="tp-sub t3">Geçen hisseler: ${r.tickers.map(tk).join(" ")}</p>` : ""}
            ${(r.est || []).length ? `<table class="doc-figs"><tbody>${r.est.map(e => `<tr><th scope="row">${esc(e.metric)}${e.period ? ` (${esc(e.period)})` : ""}</th><td>${[e.old, e.new].filter(Boolean).map(esc).join(" → ")}${e.change ? ` (${esc(e.change)})` : ""}</td></tr>`).join("")}</tbody></table>` : ""}
            ${(r.catalysts || []).length || (r.risks || []).length ? `<p class="doc-risks">${(r.catalysts || []).length ? `<b>Katalizörler:</b> ${r.catalysts.map(esc).join(" · ")}` : ""}${(r.risks || []).length ? ` <b>Riskler:</b> ${r.risks.map(esc).join(" · ")}` : ""}</p>` : ""}
            ${r.src ? `<p class="t3 rl-src">Türü ${r.src === "etiket" ? "konu satırı etiketi" : "yapay zekâ"} belirledi</p>` : ""}</div></details>`; }).join("")}</div>`
        : `<p class="tp-empty">Bu filtrede rapor yok.</p>`}
      <p class="t3 gc-foot">${xs.length > 40 ? `${xs.length} rapordan en yeni 40'ı · ` : ""}${nThin ? `<button type="button" class="link-btn" id="rsThin">${S.thin ? "İçi boş bültenleri gizle" : `İçi boş ${nThin} bülteni göster`}</button> · ` : ""}Rapor metni yayımlanmaz; yalnız kurum, hisse, tavsiye, hedef ve AI'ın kendi cümleleriyle tez. Ayrıntılı özet Telegram'da.</p></section>`;
  }
  function strategyTab() {
    const rs = reports();
    if (!rs.length) return feedStatus(rs);
    return `${feedStatus(rs)}${viewTimeline(rs)}<div class="rs-grid">${topPicks(rs)}<div class="rs-side">${themes(rs)}${sectorViews(rs)}${mpChanges(rs)}</div></div>${reportList(rs)}`;
  }
  // Özet sekmesinde strateji önizlemesi
  function stratMini() {
    const rs = reports(), cut = new Date(Date.now() - 7 * DAY).toISOString().slice(0, 10), wk = rs.filter(r => repDate(r) >= cut && !r.thin);
    if (!wk.length) return "";
    const m = new Map(); wk.forEach(r => (r.top_picks || []).forEach(p => { const o = m.get(p.t) || new Set(); o.add(r.broker); m.set(p.t, o); }));
    const top = [...m].sort((a, b) => b[1].size - a[1].size).slice(0, 8), c = k => wk.filter(r => sentOf(r) === k).length;
    return `<section class="card rs-mini" aria-labelledby="smT"><div class="card-head"><h2 class="card-title" id="smT">Strateji raporları · bu hafta</h2><button type="button" class="link-btn" data-go-tab="strateji">Strateji sekmesi →</button></div>
      <p class="t2">${wk.length} rapor · kurum görüşü <span class="up">${c("bullish")} olumlu</span>, ${c("neutral")} nötr, <span class="down">${c("bearish")} olumsuz</span></p>
      ${top.length ? `<p class="tp-sub">En çok öne çıkarılan: ${top.map(([t, b]) => `<button type="button" class="tk-link mono" data-sym="${esc(t)}">${esc(t)}</button> <span class="t3">${b.size}</span>`).join(" · ")}</p>` : ""}</section>`;
  }

  function render() {
    const box = $("#resBody");
    if (!box) return;
    if (!S.loaded) { box.innerHTML = sh.stateHTML ? sh.stateHTML({ kind: "loading", title: "Yükleniyor…" }) : "<p>Yükleniyor…</p>"; return; }
    if (S.error || !S.data) { box.innerHTML = `<section class="card"><p class="tp-empty">Araştırma verisi henüz yok. İlk tarama turundan sonra oluşur.</p></section>`; return; }
    const d = S.data;
    const tabs = `<div class="seg res-tabs" role="tablist" aria-label="Araştırma bölümleri">${Object.entries(TABS).map(([k, l]) => `<button type="button" role="tab" data-tab="${k}" aria-selected="${S.tab === k}">${l}${k === "strateji" && (d.reports || []).length ? ` <span class="n">${reports().filter(r => !r.thin).length}</span>` : ""}</button>`).join("")}</div>`;
    const body = S.tab === "strateji" ? strategyTab()
      : S.tab === "notlar" ? `${targetMap(d.notes)}${notesCard(d.notes)}`
      : S.tab === "gorunum" ? `<div class="res-out-grid">${outlookCard(d.outlooks)}</div>`
      : `<div class="res-grid"><div class="res-main">${feedStatus(reports())}${synthesisCard(d.synthesis)}${stratMini()}</div><div class="res-side">${consensusCard(d.consensus)}</div></div>`;
    box.innerHTML = `${tabs}<div class="view res-body" style="gap:var(--s-4)">${body}</div>`;
    $$(".res-tabs [data-tab]", box).forEach(b => b.onclick = () => { S.tab = b.dataset.tab; store.set("radar.resTab", S.tab); render(); $(`.res-tabs [data-tab="${S.tab}"]`)?.focus(); });
    $$("[data-go-tab]", box).forEach(b => b.onclick = () => { S.tab = b.dataset.goTab; store.set("radar.resTab", S.tab); render(); scrollTo({ top: 0 }); });
    $$("#rsWin button", box).forEach(b => b.onclick = () => { S.win = +b.dataset.v; render(); });
    $$("#rsKind button", box).forEach(b => b.onclick = () => { S.kind = b.dataset.v; render(); });
    const sel = $("#rsBroker"); if (sel) sel.onchange = () => { S.broker = sel.value; render(); };
    const th = $("#rsThin"); if (th) th.onclick = () => { S.thin = !S.thin; render(); };
    $$(".tk-link", box).forEach(b => b.onclick = () => window.radar?.openTicker(b.dataset.sym, b));
    const more = $("#resMore"); if (more) more.onclick = () => { S.limit += 30; render(); };
    const tma = $("#resTmAll"); if (tma) tma.onclick = () => { S.tmAll = !S.tmAll; render(); };
  }

  function bindTools() {
    $$("#resScope button").forEach(b => {
      b.setAttribute("aria-checked", String(b.dataset.s === scope()));
      b.disabled = sh.mine && b.dataset.s !== "watch";
      b.dataset.tip = sh.mine && b.dataset.s !== "watch" ? "Üst çubukta “Benimkiler” açık" : "";
      b.onclick = () => { S.scope = b.dataset.s; store.set("radar.resScope", S.scope); S.limit = 30; bindTools(); render(); };
    });
    const q = $("#resQ"); if (q) q.oninput = () => { S.q = q.value.trim(); S.limit = 30; render(); };
  }
  function exportCSV() {
    const rows = [["tarih", "hisse", "kurum", "tavsiye", "degisim", "hedef", "onceki", "para", "kaynak", "baglanti"],
      ...(S.data?.notes || []).map(n => [n.ts, n.t || n.name || "", n.broker, n.rating || "", n.action || "", n.tp ?? "", n.prev ?? "", n.cur || "", n.src, n.url])];
    const csv = rows.map(r => r.map(v => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\n");
    const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv" })); a.download = "araci-kurum-notlari.csv"; a.click();
  }
  bindTools();
  addEventListener("marketchange", () => { S.limit = 30; if (sh.route === "arastirma") render(); });
  addEventListener("minechange", () => { S.limit = 30; bindTools(); if (sh.route === "arastirma") render(); });
  sh.register("arastirma", {
    onShow() { S.loaded ? render() : (render(), load()); },
    async refresh() { S.loaded = false; render(); await load(); },
    exports: () => [{ label: "Aracı kurum notları (CSV)", hint: "tüm notlar, 120 gün", run: exportCSV, disabled: !S.data }],
    exportInfo: () => S.data ? `${(S.data.notes || []).length} not` : "",
    exportNote: "Araştırma verisi henüz yüklenmedi",
  });
})();
