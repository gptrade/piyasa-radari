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
  const S = { data: null, loaded: false, error: null, scope: store.get("radar.resScope", "watch"), q: "", limit: 30 };
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
  function reportsCard(rs) {
    const w = watch();
    let xs = (rs || []).filter(r => sh.market === "ALL" || (r.cur === "USD" ? "US" : "BIST") === sh.market);
    if (scope() === "watch") xs = xs.filter(r => [...(r.tickers || []), ...(r.top_picks || []).map(p => p.t)].some(t => w.has(t)));
    if (S.q) xs = xs.filter(r => sh.match(`${r.broker} ${(r.tickers || []).join(" ")} ${r.sector} ${r.thesis}`, S.q));
    if (!(rs || []).length) return "";
    const tk = t => w.has(t) ? `<button type="button" class="tk-link" data-sym="${esc(t)}">${esc(t)}</button>` : esc(t);
    return `<section class="card" aria-labelledby="resRepT">
      <div class="card-head"><h2 class="card-title" id="resRepT">Kurum raporları</h2><span class="card-meta">${fmt.int(xs.length)} rapor · rapor kutusundan; ayrıntılı özet yalnız Telegram'da</span></div>
      ${xs.length ? xs.slice(0, 12).map(r => `<article class="res-out">
        <p class="res-out-h"><span class="tag">${KIND_TR[r.type] || "Rapor"}</span><b>${esc(r.broker)}</b>
          ${(r.tickers || []).length ? r.tickers.map(tk).join(" ") : r.sector ? esc(r.sector) : ""}
          ${r.rating ? `<span class="${r.rating === "AL" ? "up" : r.rating === "SAT" ? "down" : "flat"}">${esc(r.rating)}</span>` : ""}
          ${r.tp ? `<span class="t3">hedef</span> <b>${fmt.num(r.tp, 2)}${r.cur === "USD" ? " $" : " ₺"}</b>${r.prev && r.prev !== r.tp ? ` <span class="t3">← ${fmt.num(r.prev, 2)}</span>` : ""}` : ""}
          ${r.view ? `<span class="${VIEW[r.view] || ""}">sektör: ${esc(r.view)}</span>` : ""}
          <span class="t3">· ${esc(r.date || "")}</span></p>
        ${r.thesis ? `<p class="d-sum">${esc(r.thesis)}</p>` : ""}
        ${(r.est || []).length ? `<table class="doc-figs"><tbody>${r.est.map(e => `<tr><th scope="row">${esc(e.metric)}${e.period ? ` (${esc(e.period)})` : ""}</th><td>${[e.old, e.new].filter(Boolean).map(esc).join(" → ")}${e.change ? ` (${esc(e.change)})` : ""}</td></tr>`).join("")}</tbody></table>` : ""}
        ${(r.top_picks || []).length ? `<p class="tp-sub">Öne çıkanlar: ${r.top_picks.map(p => tk(p.t) + (p.tp ? ` <span class="t3">${fmt.num(p.tp, 2)}</span>` : "")).join(" · ")}</p>` : ""}
        ${(r.mp?.added || []).length || (r.mp?.removed || []).length ? `<p class="tp-sub">Model portföy: ${(r.mp.added || []).map(t => `<span class="up">+${esc(t)}</span>`).join(" ")} ${(r.mp.removed || []).map(t => `<span class="down">−${esc(t)}</span>`).join(" ")}</p>` : ""}
        ${(r.catalysts || []).length || (r.risks || []).length ? `<p class="doc-risks">${(r.catalysts || []).length ? `<b>Katalizörler:</b> ${r.catalysts.map(esc).join(" · ")}` : ""}${(r.risks || []).length ? ` <b>Riskler:</b> ${r.risks.map(esc).join(" · ")}` : ""}</p>` : ""}
      </article>`).join("") : `<p class="tp-empty">Bu filtrede rapor yok.</p>`}
    </section>`;
  }

  function outlookCard(os) {
    return `<section class="card" aria-labelledby="resOutT">
      <div class="card-head"><h2 class="card-title" id="resOutT">Kurum görünümleri</h2><span class="card-meta">J.P. Morgan Guide to the Markets (çeyreklik) · BlackRock haftalık yorum</span></div>
      ${os?.length ? os.slice(0, 4).map(o => `<article class="res-out">
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

  function render() {
    const box = $("#resBody");
    if (!box) return;
    if (!S.loaded) { box.innerHTML = sh.stateHTML ? sh.stateHTML({ kind: "loading", title: "Yükleniyor…" }) : "<p>Yükleniyor…</p>"; return; }
    if (S.error || !S.data) { box.innerHTML = `<section class="card"><p class="tp-empty">Araştırma verisi henüz yok. İlk tarama turundan sonra oluşur.</p></section>`; return; }
    const d = S.data;
    box.innerHTML = `<div class="res-grid"><div class="res-main">${synthesisCard(d.synthesis)}${targetMap(d.notes)}${reportsCard(d.reports)}${notesCard(d.notes)}</div>
      <div class="res-side">${consensusCard(d.consensus)}${outlookCard(d.outlooks)}</div></div>`;
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
