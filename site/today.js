/* Piyasa Radarı — Bugün: her sekmeden günün en önemli birkaç şeyi tek ekranda.
   Kaynaklar sitenin kendi veri dosyaları: feed/digest/macro/research (Sinyal), calendar (Takvim), portföy (bu tarayıcı). Her kart ilgili sekmeye götürür. */
(() => {
  "use strict";
  const sh = window.shell;
  const { $, esc, fmt, glyph, dirCls } = sh;
  const DAY = 864e5;
  const MAT_W = { low: 1, medium: 2, high: 3 };
  const S = { cal: null, loaded: false };

  async function getJSON(p) {
    try { const r = await fetch(`${p}?t=${Date.now()}`, { cache: "no-store" }); return r.ok ? await r.json() : null; } catch { return null; }
  }
  async function load() {
    const cal = await getJSON("data/calendar.json");
    Object.assign(S, { cal, loaded: true });
    await Promise.race([window.radar?.ready, new Promise(r => setTimeout(r, 8000))]);
    const st = window.radar?.state;
    sh.setUpdated("bugun", st?.feed?.generated || new Date(), { label: "Son tarama", staleMin: 45 });
    render();
  }

  // ─────────────────────────────── parçalar
  const todayKey = () => fmt.dayKey(Date.now());
  const ageH = t => (Date.now() - new Date(t)) / 36e5;
  const card = (id, title, href, body, meta = "") => `<section class="card td-card" aria-labelledby="${id}">
    <div class="card-head"><h2 class="card-title" id="${id}">${title}</h2>${href ? `<a class="link-btn" href="#${href}">Tümü →</a>` : meta ? `<span class="card-meta">${meta}</span>` : ""}</div>${body}</section>`;
  const empty = msg => `<p class="td-empty">${msg}</p>`;

  function digest() {
    const d = window.radar?.state?.digest;
    if (!d?.headline) return "";
    const mood = { olumlu: "up", olumsuz: "down", "karışık": "flat" }[d.mood] || "flat";
    return `<section class="card td-digest" aria-labelledby="tdDg">
      <div class="td-dg-top"><span class="tag ${mood}">${esc(d.mood || "")}</span><span class="card-meta">son ${d.window_hours || 2} saatin özeti · ${fmt.ago(d.generated, true)}</span></div>
      <h2 class="td-dg-h" id="tdDg">${esc(d.headline)}</h2><p class="td-dg-s">${esc(d.summary || "")}</p>
      ${(d.ideas || []).length ? `<div class="td-ideas">${d.ideas.slice(0, 4).map(i => `<button type="button" class="td-idea" data-tk="${esc(i.ticker)}" data-tip="${esc(i.rationale || "")}${i.risk ? `<br><b>Risk:</b> ${esc(i.risk)}` : ""}">
        <b>${esc(i.ticker)}</b><span class="tag">${esc(i.stance || "")}</span><span class="td-idea-t">${esc(i.title || "")}</span>${i.conviction ? `<span class="meta">%${i.conviction}</span>` : ""}</button>`).join("")}</div>` : ""}</section>`;
  }
  function kpis() {
    const st = window.radar?.state, ser = st?.macro?.series || [];
    const k = (label, value, sub = "", cls = "") => `<div class="kpi"><span class="kpi-label">${label}</span><span class="kpi-value">${value}</span>${sub ? `<span class="kpi-sub ${cls}">${sub}</span>` : ""}</div>`;
    const m = code => ser.find(s => s.code === code);
    const out = [];
    for (const [code, label, d] of [["TP.DK.USD.A.YTL", "USD/TRY", 4], ["TP.DK.EUR.A.YTL", "EUR/TRY", 4], ["TP.APIFON4", "TCMB fonlama (%)", 2]]) {
      const s = m(code);
      if (s) out.push(k(label, fmt.num(s.last, d), s.change_pct != null ? `${glyph(s.change_pct)} ${fmt.pct(s.change_pct, 2)}` : "", dirCls(s.change_pct)));
    }
    const pf = window.radarPortfolio?.summary?.();
    if (pf?.n) out.push(k("Portföy", pf.value != null ? fmt.num(pf.value, 0) + " ₺" : "—", pf.dayPct != null ? `bugün ${glyph(pf.dayPct)} ${fmt.pct(pf.dayPct, 2)}` : `${pf.n} pozisyon`, dirCls(pf.dayPct)));
    const evs = calEvents(0);
    out.push(k("Bugün önemli olay", fmt.int(evs.filter(e => e.importance >= 3).length), `${evs.length} olay`));
    const sig = signals(48).length;
    out.push(k("Güçlü sinyal (24 sa)", fmt.int(signals(24).length), `48 sa: ${sig}`));
    return `<div class="kpi-grid">${out.join("")}</div>`;
  }
  function signals(hours) {
    const items = window.radar?.state?.feed?.items || [];
    return items.filter(i => { const a = i.analysis; return a && a.sentiment !== "neutral" && a.confidence >= 70 && a.materiality !== "low" && ageH(i.published) <= hours; })
      .sort((x, y) => score(y) - score(x));
  }
  const score = it => { const a = it.analysis; return MAT_W[a.materiality] * a.confidence * Math.max(0.2, 1 - ageH(it.published) / 48) * (1 + Math.min(it.dups || 0, 10) * 0.05); };
  function signalCard() {
    const held = window.radarPortfolio?.held?.() || new Set();
    const rows = signals(24).slice(0, 7);
    const body = rows.length ? `<ul class="td-list">${rows.map(it => { const a = it.analysis, d = a.sentiment === "bullish" ? 1 : -1;
      return `<li><button type="button" class="td-row" data-item="${esc(it.id)}"><span class="td-dir ${dirCls(d)}">${glyph(d)}</span>
        <span class="td-tk">${esc((it.tickers || [])[0] || it.market)}${held.has((it.tickers || [])[0]) ? ` <span class="mine-dot" data-tip="Portföyünde">●</span>` : ""}</span>
        <span class="td-t">${a.materiality === "high" ? `<span class="tag warn">önemli</span> ` : ""}${esc(a.headline_tr || it.title)}</span><span class="td-age">${fmt.ago(it.published)}</span></button></li>`; }).join("")}</ul>`
      : empty("Son 24 saatte güçlü sinyal yok.");
    return card("tdSig", "Öne çıkan sinyaller", "sinyal", body);
  }
  function calEvents(dayOffset) {
    const evs = S.cal?.events || [];
    const key = fmt.dayKey(Date.now() + dayOffset * DAY);
    return evs.filter(e => e.date === key && (e.importance || 0) >= 2).sort((a, b) => (a.when || "").localeCompare(b.when || ""));
  }
  function calCard() {
    const row = e => `<li class="td-ev"><span class="td-time">${e.timed && e.when ? esc(fmt.clock(e.when)) : "gün içi"}</span>
      <span class="td-imp i${e.importance}" aria-label="önem ${e.importance}"></span><span class="td-t">${esc(e.title)}</span><span class="td-mk">${esc(e.region || e.market || "")}</span></li>`;
    const t = calEvents(0), y = calEvents(1);
    const body = (t.length ? `<h3 class="td-h3">Bugün</h3><ul class="td-list">${t.slice(0, 8).map(row).join("")}</ul>` : empty("Bugün önemli olay yok.")) +
      (y.length ? `<h3 class="td-h3">Yarın</h3><ul class="td-list">${y.slice(0, 5).map(row).join("")}</ul>` : "");
    return card("tdCal", "Takvim", "takvim", body);
  }
  function pfCard() {
    const pf = window.radarPortfolio?.summary?.();
    if (!pf?.n) return card("tdPf", "Portföy", "portfoy", empty(`Portföy boş. <a href="#portfoy">Pozisyon ekle</a>; stop ve hedef uyarıları burada görünür.`));
    const al = pf.alerts.map(a => `<li><span class="td-tk">${esc(a.sym)}</span><span class="tag ${a.c}">${esc(a.t)}</span><span class="td-t">${fmt.num(a.last, 2)}</span></li>`).join("");
    const mv = pf.movers.map(m => `<li><button type="button" class="td-row" data-tk="${esc(m.sym)}"><span class="td-tk">${esc(m.sym)}</span><span class="td-t ${dirCls(m.chg)}">${glyph(m.chg)} ${fmt.pct(m.chg, 2)}</span>
      <span class="td-age">${m.w != null ? "%" + fmt.num(m.w, 1) + " ağırlık" : ""}</span></button></li>`).join("");
    return card("tdPf", "Portföy", "portfoy", (al ? `<h3 class="td-h3">Uyarılar</h3><ul class="td-list">${al}</ul>` : "") +
      `<h3 class="td-h3">Günün en çok hareket edenleri</h3>${mv ? `<ul class="td-list">${mv}</ul>` : empty("Fiyatlar henüz yüklenmedi.")}`);
  }
  function researchCard() {
    const notes = (window.radar?.state?.research?.notes || []).filter(n => ageH(n.ts) <= 48).slice(0, 6);
    if (!notes.length) return "";
    const act = { up: "hedef ↑", down: "hedef ↓", init: "kapsama başladı", upgrade: "tavsiye ↑", downgrade: "tavsiye ↓", keep: "korundu", reiterate: "korundu", maintain: "korundu" };
    return card("tdRs", "Aracı kurum notları (48 sa)", "arastirma", `<ul class="td-list">${notes.map(n => `<li><a class="td-row" href="${esc(n.url)}" target="_blank" rel="noopener">
      <span class="td-tk">${esc(n.t || n.name || "")}</span><span class="td-t">${esc(n.broker || "")}${n.action ? ` · ${esc(act[n.action] || n.action)}` : ""}${n.tp ? ` · ${fmt.num(n.tp, 2)} ${esc(n.cur || "")}` : ""}${n.rating ? ` · ${esc(n.rating)}` : ""}</span>
      <span class="td-age">${fmt.ago(n.ts)}</span></a></li>`).join("")}</ul>`);
  }

  function render() {
    if (sh.route !== "bugun") return;
    const body = $("#tdBody");
    if (!S.loaded) { body.innerHTML = `<div class="view" aria-busy="true"><div class="kpi-grid">${Array.from({ length: 6 }, () => `<div class="kpi"><div class="skeleton sk-line w60"></div><div class="skeleton sk-line lg w40"></div></div>`).join("")}</div></div>`; return; }
    const d = new Date().toLocaleDateString("tr-TR", { timeZone: sh.TZ, weekday: "long", day: "numeric", month: "long", year: "numeric" });
    $("#tdDate").textContent = d;
    body.innerHTML = `<div class="view" style="gap:var(--s-4)">${kpis()}${digest()}
      <div class="td-grid">${signalCard()}${calCard()}${pfCard()}${researchCard()}</div></div>`;
  }

  $("#tdBody").addEventListener("click", e => {
    const it = e.target.closest("[data-item]"), tk = e.target.closest("[data-tk]");
    if (it) window.radar?.openItem?.(it.dataset.item, it);
    else if (tk) window.radar?.openTicker?.(tk.dataset.tk, tk);
  });
  addEventListener("radar:pf", () => render());
  addEventListener("themechange", render);

  sh.register("bugun", {
    onShow() { S.loaded ? render() : (render(), load()); },
    async refresh() { await window.radar?.poll?.(); await load(); },
    exports: () => [],
    exportNote: "Bugün sayfası özet; dışa aktarma ilgili sekmelerden yapılır",
  });
})();
