/* Piyasa Radarı — Takvim sekmesi (katalizörler).
   Veri: data/calendar.json (pipeline: config/calendar.yml makro takvim + hesaplanan vade sonları + Yahoo bilanço/temettü). */
(() => {
  "use strict";
  const sh = window.shell;
  const { $, $$, esc, fmt, store } = sh;
  const DAY = 86400000;
  const KIND = {
    cb: { l: "Merkez bankası", s: "MB" }, macro: { l: "Makro veri", s: "Veri" }, report: { l: "Rapor", s: "Rapor" },
    earnings: { l: "Bilanço", s: "Bilanço" }, agm: { l: "Genel kurul", s: "GK" }, dividend: { l: "Temettü", s: "Temettü" }, expiry: { l: "Vade sonu", s: "Vade" },
  };
  const RANGE = { 14: "2 hafta", 30: "1 ay", 60: "2 ay" };
  const S = { cal: null, loaded: false, error: null, kinds: new Set(store.get("radar.calKinds", [])),
    days: store.get("radar.calDays", 30), important: store.get("radar.calImp", false), watch: new Set() };

  async function load() {
    try {
      const r = await fetch(`data/calendar.json?t=${Date.now()}`);
      if (!r.ok) throw new Error(`data/calendar.json okunamadı (HTTP ${r.status})`);
      S.cal = await r.json(); S.error = null;
    } catch (e) { S.error = e; }
    S.loaded = true;
    if (S.cal) sh.setUpdated("takvim", S.cal.generated, { label: "Takvim güncellendi", staleMin: 180 });
    badge();
    if (sh.route === "takvim") render();
  }
  const istDate = d => new Date(d).toLocaleDateString("en-CA", { timeZone: "Europe/Istanbul" });   // YYYY-MM-DD
  const todayISO = () => istDate(Date.now());
  const daysTo = iso => Math.round((Date.parse(iso + "T00:00:00Z") - Date.parse(todayISO() + "T00:00:00Z")) / DAY);
  const inMarket = e => sh.market === "ALL" || e.market === "ALL" || e.market === sh.market;
  function visible() {
    const lim = todayISO(), hi = new Date(Date.parse(lim) + S.days * DAY).toISOString().slice(0, 10);
    return (S.cal?.events || []).filter(e => inMarket(e) && e.date >= lim && e.date <= hi
      && (!S.kinds.size || S.kinds.has(e.kind)) && (!S.important || e.importance >= 3));
  }
  function rel(n) { return n === 0 ? "bugün" : n === 1 ? "yarın" : `${n} gün sonra`; }
  function dayHead(iso) {
    const d = new Date(iso + "T12:00:00Z"), n = daysTo(iso);
    const lbl = d.toLocaleDateString("tr-TR", { weekday: "long", day: "numeric", month: "long", timeZone: "UTC" });
    return `<span class="cal-day-name">${esc(lbl)}</span><span class="cal-rel${n <= 1 ? " soon" : ""}">${rel(n)}</span>`;
  }
  const timeOf = e => e.timed ? new Date(e.when).toLocaleTimeString("tr-TR", { timeZone: "Europe/Istanbul", hour: "2-digit", minute: "2-digit" })
    : ["earnings", "dividend", "agm"].includes(e.kind) ? "—" : "gün boyu";
  const imp = n => `<span class="meter" data-l="${n}" role="img" aria-label="Önem ${n === 3 ? "yüksek" : n === 2 ? "orta" : "düşük"}"><i></i><i></i><i></i></span>`;
  const mk = m => m === "ALL" ? "" : `<span class="tag mk">${m === "US" ? "ABD" : m}</span>`;

  function upcomingCards(evs) {
    const top = evs.filter(e => e.importance >= 3).slice(0, 3);
    if (!top.length) return "";
    return `<div class="cal-next">${top.map(e => { const n = daysTo(e.date); return `
      <div class="card cal-card k-${e.kind}"><span class="cal-kind">${esc(KIND[e.kind]?.l || e.kind)} ${mk(e.market)}</span>
        <b class="cal-title">${esc(e.title)}</b>
        <span class="cal-when">${esc(new Date(e.date + "T12:00:00Z").toLocaleDateString("tr-TR", { day: "numeric", month: "short", weekday: "short", timeZone: "UTC" }))} · ${timeOf(e)}</span>
        <span class="cal-count${n <= 1 ? " soon" : ""}">${n === 0 ? "Bugün" : n === 1 ? "Yarın" : `${n} gün`}</span></div>`; }).join("")}</div>`;
  }
  function render() {
    const box = $("#calBody");
    if (!S.loaded) { box.innerHTML = `<div class="card"><div class="skeleton sk-line w40"></div><div class="skeleton sk-line"></div><div class="skeleton sk-line w80"></div></div>`; return; }
    if (S.error && !S.cal) {
      box.innerHTML = `<div class="card">${sh.stateHTML({ kind: "error", title: "Takvim yüklenemedi", msg: esc(S.error.message) + ". Takvim ilk taramadan sonra oluşur.", action: "Tekrar dene", actionId: "calRetry" })}</div>`;
      $("#calRetry").onclick = () => { S.loaded = false; render(); load(); };
      return;
    }
    // filtre çipleri
    const all = (S.cal.events || []).filter(e => inMarket(e) && e.date >= todayISO());
    $("#calKinds").innerHTML = Object.entries(KIND).filter(([k]) => all.some(e => e.kind === k)).map(([k, v]) =>
      `<button type="button" class="chip" data-k="${k}" aria-pressed="${S.kinds.has(k)}">${esc(v.l)} <span class="n">${all.filter(e => e.kind === k).length}</span></button>`).join("");
    $$("#calRange button").forEach(b => b.setAttribute("aria-checked", String(+b.dataset.d === S.days)));
    $("#calImp").setAttribute("aria-pressed", String(S.important));
    const evs = visible();
    let html = upcomingCards(evs);
    if (!evs.length) {
      html += `<div class="card">${sh.stateHTML({ kind: "empty", title: "Bu aralıkta olay yok", msg: S.kinds.size || S.important ? "Filtreleri gevşet ya da aralığı uzat." : "Seçili piyasa için yaklaşan olay bulunamadı." })}</div>`;
    } else {
      const byDay = new Map();
      evs.forEach(e => (byDay.get(e.date) || byDay.set(e.date, []).get(e.date)).push(e));
      html += `<div class="card card-flush"><ol class="cal-list">${[...byDay].map(([d, list]) => `
        <li class="cal-day${daysTo(d) <= 1 ? " soon" : ""}"><h3 class="cal-day-h">${dayHead(d)}</h3>
          <ul>${list.map(e => `<li class="cal-ev k-${e.kind}">
            <span class="cal-t">${timeOf(e)}</span>
            <span class="cal-k"><span class="cal-dot" aria-hidden="true"></span>${esc(KIND[e.kind]?.s || e.kind)}</span>
            <span class="cal-main"><span class="cal-name">${e.ticker ? `<button type="button" class="tk-link" data-sym="${esc(e.ticker)}">${esc(e.ticker)}</button> ${esc(e.title.replace(e.ticker + " ", ""))}` : esc(e.title)} ${mk(e.market)}</span>
              ${e.detail ? `<span class="cal-detail">${esc(e.detail)}</span>` : ""}</span>
            <span class="cal-imp">${imp(e.importance)}</span>
            <span class="cal-src">${e.url ? `<a href="${esc(e.url)}" target="_blank" rel="noopener" aria-label="${esc(e.title)} kaynağı">Kaynak ↗</a>` : ""}</span>
          </li>`).join("")}</ul></li>`).join("")}</ol></div>`;
    }
    const until = S.cal.macro_until;
    html += `<p class="k-note">Saatler İstanbul saatiyle. Makro tarihler resmi takvimlerden (TCMB, TÜİK, Fed, BLS)${until ? `; tanımlı son tarih ${fmt.date(until, { day: "numeric", month: "long", year: "numeric" })}` : ""} · bilanço ve temettü tarihleri Yahoo Finance'ten (şirketler değiştirebilir), genel kurullar Borsa İstanbul listesinden · VİOP vade sonu çift ayların son iş günü, ABD opsiyon vadesi ayın 3. cuması olarak hesaplanır.</p>`;
    box.innerHTML = html;
  }
  function badge() {
    const n = (S.cal?.events || []).filter(e => inMarket(e) && e.importance >= 3 && [0, 1].includes(daysTo(e.date))).length;
    sh.setBadge("takvim", n, n ? `Bugün ve yarın ${n} önemli olay` : "");
  }
  function bind() {
    $("#calKinds").addEventListener("click", e => {
      const b = e.target.closest(".chip"); if (!b) return;
      S.kinds.has(b.dataset.k) ? S.kinds.delete(b.dataset.k) : S.kinds.add(b.dataset.k);
      store.set("radar.calKinds", [...S.kinds]); render(); $(`#calKinds .chip[data-k="${b.dataset.k}"]`)?.focus();
    });
    $$("#calRange button").forEach(b => b.onclick = () => { S.days = +b.dataset.d; store.set("radar.calDays", S.days); render(); });
    sh.radioKeys?.($("#calRange"));
    $("#calImp").onclick = () => { S.important = !S.important; store.set("radar.calImp", S.important); render(); };
    $("#calBody").addEventListener("click", e => {
      const t = e.target.closest(".tk-link"); if (!t) return;
      sh.go("sinyal"); setTimeout(() => window.radar?.openTicker?.(t.dataset.sym, t), 60);
    });
    addEventListener("marketchange", () => { badge(); if (sh.route === "takvim") render(); });
  }
  function exportCSV() {
    const ex = window.radarExport; if (!ex) return;
    const rows = visible().map(e => ({ tarih: e.date, saat_istanbul: e.timed ? timeOf(e) : "", tur: KIND[e.kind]?.l || e.kind, piyasa: e.market,
      hisse: e.ticker || "", olay: e.title, ayrinti: e.detail || "", onem: e.importance, kaynak: e.url || "" }));
    ex.download(`takvim_${ex.stamp()}.csv`, ex.toCSV(rows), "text/csv;charset=utf-8");
  }
  bind();
  sh.register("takvim", {
    onShow() { S.loaded ? render() : (render(), load()); },
    async refresh() { S.loaded = false; render(); await load(); },
    exports: () => [{ label: "Takvim (CSV)", hint: `${RANGE[S.days] || S.days + " gün"}, filtreli`, run: exportCSV, disabled: !S.cal }],
    exportInfo: () => S.cal ? `${RANGE[S.days]}${S.kinds.size ? ` · ${[...S.kinds].map(k => KIND[k].l).join(", ")}` : ""}${S.important ? " · yalnız önemli" : ""}` : "",
    exportNote: "Takvim henüz yüklenmedi",
  });
  setTimeout(() => { if (!S.loaded) load(); }, 1200);           // rozet için arka planda
})();
