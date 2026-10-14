/* Piyasa Radarı — Takvim sekmesi (katalizörler).
   Veri: data/calendar.json (pipeline: TÜİK Ulusal Veri Yayımlama Takvimi + config/calendar.yml makro takvim
   + hesaplanan vade sonları + KAP/Yahoo bilanço/temettü).
   Görünümler: Hafta (iş günü sütunları), Ay (ızgara), Liste (gün gün). Olaya tıklayınca ayrıntı penceresi. */
(() => {
  "use strict";
  const sh = window.shell;
  const { $, $$, esc, fmt, store } = sh;
  const DAY = 86400000;
  const KIND = {
    cb: { l: "Merkez bankası", s: "MB" }, macro: { l: "Makro veri", s: "Veri" }, data: { l: "Diğer resmi veri", s: "Veri" },
    report: { l: "Rapor", s: "Rapor" }, earnings: { l: "Bilanço", s: "Bilanço" }, agm: { l: "Genel kurul", s: "GK" },
    dividend: { l: "Temettü", s: "Temettü" }, expiry: { l: "Vade sonu", s: "Vade" },
  };
  const RANGE = { 14: "2 hafta", 30: "1 ay", 60: "2 ay" };
  const VIEWS = { week: "Hafta", month: "Ay", list: "Liste" };
  const WD = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"];
  const S = { cal: null, loaded: false, error: null, kinds: new Set(store.get("radar.calKinds", [])),
    days: store.get("radar.calDays", 30), important: store.get("radar.calImp", false),
    view: store.get("radar.calView", "week"), anchor: null, idx: [] };
  if (!VIEWS[S.view]) S.view = "week";

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

  // ── tarih yardımcıları (ISO YYYY-MM-DD, UTC öğlen üzerinden: saat dilimi kayması olmasın)
  const istDate = d => new Date(d).toLocaleDateString("en-CA", { timeZone: "Europe/Istanbul" });
  const todayISO = () => istDate(Date.now());
  const D = iso => new Date(iso + "T12:00:00Z");
  const addDays = (iso, n) => new Date(D(iso).getTime() + n * DAY).toISOString().slice(0, 10);
  const monday = iso => addDays(iso, -((D(iso).getUTCDay() + 6) % 7));
  const daysTo = iso => Math.round((D(iso) - D(todayISO())) / DAY);
  const dLabel = (iso, o) => D(iso).toLocaleDateString("tr-TR", { timeZone: "UTC", ...o });

  const inMarket = e => sh.market === "ALL" || e.market === "ALL" || e.market === sh.market;
  const passes = e => inMarket(e) && (!S.kinds.size || S.kinds.has(e.kind)) && (!S.important || e.importance >= 3);
  function visible() {
    const lim = todayISO(), hi = addDays(lim, S.days);
    return (S.cal?.events || []).filter(e => passes(e) && e.date >= lim && e.date <= hi);
  }
  function between(lo, hi) { return (S.cal?.events || []).filter(e => passes(e) && e.date >= lo && e.date <= hi); }
  const covered = (lo, hi) => { const r = S.cal?.range || []; return r.length === 2 && hi >= r[0] && lo <= r[1]; };

  function rel(n) { return n === 0 ? "bugün" : n === 1 ? "yarın" : n === -1 ? "dün" : n < 0 ? `${-n} gün önce` : `${n} gün sonra`; }
  function dayHead(iso) {
    const n = daysTo(iso);
    return `<span class="cal-day-name">${esc(dLabel(iso, { weekday: "long", day: "numeric", month: "long" }))}</span><span class="cal-rel${n >= 0 && n <= 1 ? " soon" : ""}">${rel(n)}</span>`;
  }
  const hm = e => new Date(e.when).toLocaleTimeString("tr-TR", { timeZone: "Europe/Istanbul", hour: "2-digit", minute: "2-digit" });
  const timeOf = e => e.timed ? hm(e) : ["earnings", "dividend", "agm"].includes(e.kind) ? "—" : "gün boyu";
  const imp = n => `<span class="meter" data-l="${n}" role="img" aria-label="Önem ${n === 3 ? "yüksek" : n === 2 ? "orta" : "düşük"}"><i></i><i></i><i></i></span>`;
  const mk = m => m === "ALL" ? "" : `<span class="tag mk">${m === "US" ? "ABD" : m}</span>`;
  const shortTitle = e => e.title.split(" · ")[0];
  const reg = e => { S.idx.push(e); return S.idx.length - 1; };

  function chip(e, { time = true } = {}) {
    const lbl = `${shortTitle(e)}${e.ticker ? "" : ""}`;
    return `<li><button type="button" class="cal-chip k-${e.kind} i${e.importance}" data-i="${reg(e)}"
      aria-label="${esc(`${e.timed ? hm(e) + " " : ""}${e.title}, ${KIND[e.kind]?.l || e.kind}, önem ${e.importance}`)}">
      ${time && e.timed ? `<span class="cal-chip-t">${hm(e)}</span>` : ""}<span class="cal-chip-n">${esc(lbl)}</span>${e.market === "US" ? `<span class="cal-chip-m">ABD</span>` : ""}</button></li>`;
  }

  // ── Hafta görünümü
  function navBar(label, sub) {
    return `<div class="cal-nav">
      <div class="cal-nav-btns">
        <button type="button" class="btn btn-sm" data-nav="-1" aria-label="Önceki ${S.view === "month" ? "ay" : "hafta"}">‹ Önceki</button>
        <button type="button" class="btn btn-sm" data-nav="0">Bugün</button>
        <button type="button" class="btn btn-sm" data-nav="1" aria-label="Sonraki ${S.view === "month" ? "ay" : "hafta"}">Sonraki ›</button>
      </div>
      <h3 class="cal-nav-h">${esc(label)}${sub ? ` <span class="cal-nav-sub">${esc(sub)}</span>` : ""}</h3>
      <label class="cal-pick"><span class="sr-only">Tarih seç</span><input type="date" id="calPick" value="${S.anchor}"></label>
    </div>`;
  }
  function renderWeek() {
    const mon = monday(S.anchor), sun = addDays(mon, 6), t = todayISO();
    const evs = between(mon, sun);
    const days = [...Array(7)].map((_, i) => addDays(mon, i)).filter((d, i) => i < 5 || evs.some(e => e.date === d));
    const label = `${dLabel(mon, { day: "numeric", month: D(mon).getUTCMonth() === D(addDays(mon, 4)).getUTCMonth() ? undefined : "long" })}–${dLabel(addDays(mon, 4), { day: "numeric", month: "long", year: "numeric" })}`;
    const cols = days.map(d => {
      const list = evs.filter(e => e.date === d).sort((a, b) => (a.when > b.when) - (a.when < b.when) || b.importance - a.importance);
      const wd = WD[(D(d).getUTCDay() + 6) % 7];
      return `<section class="cal-col${d === t ? " today" : ""}${d < t ? " past" : ""}" aria-label="${esc(dLabel(d, { weekday: "long", day: "numeric", month: "long" }))}">
        <header class="cal-col-h"><span class="cal-wd">${wd}</span><b class="cal-dn">${D(d).getUTCDate()}</b>${list.length ? `<span class="cal-cnt">${list.length}</span>` : ""}</header>
        ${list.length ? `<ul class="cal-chips">${list.map(e => chip(e)).join("")}</ul>` : `<p class="cal-none">—</p>`}
      </section>`;
    }).join("");
    const out = !covered(mon, sun) ? `<div class="card cal-out">${sh.stateHTML({ kind: "empty", title: "Bu hafta takvim kapsamı dışında", msg: `Takvim ${fmt.date(S.cal.range[0], { day: "numeric", month: "long" })} – ${fmt.date(S.cal.range[1], { day: "numeric", month: "long" })} aralığını kapsar.` })}</div>` : "";
    return `${navBar(label, evs.length ? `${evs.length} olay` : "")}${out}
      <div class="cal-wk"><div class="cal-grid" style="--cols:${days.length}">${cols}</div>${side()}</div>`;
  }

  // ── Ay görünümü
  function renderMonth() {
    const a = D(S.anchor), first = `${a.getUTCFullYear()}-${String(a.getUTCMonth() + 1).padStart(2, "0")}-01`;
    const nextFirst = new Date(Date.UTC(a.getUTCFullYear(), a.getUTCMonth() + 1, 1, 12)).toISOString().slice(0, 10);
    const last = addDays(nextFirst, -1), start = monday(first), t = todayISO();
    const end = addDays(monday(last), 6);
    const evs = between(start, end);
    const cells = [];
    for (let d = start; d <= end; d = addDays(d, 1)) {
      const list = evs.filter(e => e.date === d).sort((x, y) => y.importance - x.importance || (x.when > y.when) - (x.when < y.when));
      const show = list.slice(0, 4), more = list.length - show.length;
      const wkend = (D(d).getUTCDay() + 6) % 7 >= 5;
      const nodata = !covered(d, d);
      cells.push(`<div class="cal-cell${d.slice(0, 7) !== first.slice(0, 7) ? " other" : ""}${nodata ? " nodata" : ""}${d === t ? " today" : ""}${wkend ? " wkend" : ""}" role="gridcell" aria-label="${esc(dLabel(d, { day: "numeric", month: "long" }))}, ${list.length} olay">
        <button type="button" class="cal-cell-d" data-week="${d}" aria-label="${esc(dLabel(d, { day: "numeric", month: "long" }))} haftasını aç">${D(d).getUTCDate()}</button>
        ${show.length ? `<ul class="cal-chips">${show.map(e => chip(e, { time: false })).join("")}</ul>` : ""}
        ${more > 0 ? `<button type="button" class="cal-more" data-week="${d}">+${more} daha</button>` : ""}</div>`);
    }
    const label = dLabel(first, { month: "long", year: "numeric" });
    return `${navBar(label, evs.length ? `${evs.filter(e => e.date >= first && e.date <= last).length} olay` : "")}
      <div class="card card-flush cal-month" role="grid" aria-label="${esc(label)}">
        <div class="cal-month-h" role="row">${WD.map(w => `<span role="columnheader">${w}</span>`).join("")}</div>
        <div class="cal-month-g">${cells.join("")}</div></div>
      <p class="k-note">Hücrede en önemli 4 olay; tümü için "+ daha" ya da gün numarası (Hafta görünümü). Taralı günler takvim kapsamı dışında.</p>`;
  }

  // ── yan panel: her iş günü yayımlananlar + gösterim
  function side() {
    const daily = S.cal?.daily || [];
    return `<aside class="cal-side">
      <div class="card"><h3 class="card-h">Her iş günü</h3>
        ${daily.length ? `<ul class="cal-daily">${daily.map(d => `<li><span class="cal-daily-t">${esc(d.time)}</span><span>${d.url ? `<a href="${esc(d.url)}" target="_blank" rel="noopener">${esc(d.name)}</a>` : esc(d.name)}</span><span class="cal-inst">${esc(d.inst)}</span></li>`).join("")}</ul>`
          : `<p class="k-note">Liste resmi takvimle birlikte gelir.</p>`}</div>
      <div class="card"><h3 class="card-h">Gösterim</h3>
        <ul class="cal-legend">
          <li><span class="cal-chip i3 k-macro demo">Kalın</span> yüksek önem</li>
          <li><span class="cal-chip i2 k-macro demo">Normal</span> orta</li>
          <li><span class="cal-chip i1 k-data demo">Soluk</span> düşük</li>
        </ul>
        <ul class="cal-legend kinds">${Object.entries(KIND).map(([k, v]) => `<li><span class="cal-dot k-${k}"></span>${esc(v.l)}</li>`).join("")}</ul>
      </div></aside>`;
  }

  // ── Liste görünümü (önceki sürüm)
  function upcomingCards(evs) {
    const top = evs.filter(e => e.importance >= 3).slice(0, 3);
    if (!top.length) return "";
    return `<div class="cal-next">${top.map(e => { const n = daysTo(e.date); return `
      <div class="card cal-card k-${e.kind}"><span class="cal-kind">${esc(KIND[e.kind]?.l || e.kind)} ${mk(e.market)}</span>
        <b class="cal-title"><button type="button" class="cal-open" data-i="${reg(e)}">${esc(e.title)}</button></b>
        <span class="cal-when">${esc(dLabel(e.date, { day: "numeric", month: "short", weekday: "short" }))} · ${timeOf(e)}</span>
        <span class="cal-count${n <= 1 ? " soon" : ""}">${n === 0 ? "Bugün" : n === 1 ? "Yarın" : `${n} gün`}</span></div>`; }).join("")}</div>`;
  }
  function renderList() {
    const evs = visible();
    let html = upcomingCards(evs);
    if (!evs.length) {
      html += `<div class="card">${sh.stateHTML({ kind: "empty", title: "Bu aralıkta olay yok", msg: S.kinds.size || S.important ? "Filtreleri gevşet ya da aralığı uzat." : "Seçili piyasa için yaklaşan olay bulunamadı." })}</div>`;
      return html;
    }
    const byDay = new Map();
    evs.forEach(e => (byDay.get(e.date) || byDay.set(e.date, []).get(e.date)).push(e));
    return html + `<div class="card card-flush"><ol class="cal-list">${[...byDay].map(([d, list]) => `
      <li class="cal-day${daysTo(d) <= 1 ? " soon" : ""}"><h3 class="cal-day-h">${dayHead(d)}</h3>
        <ul>${list.map(e => `<li class="cal-ev k-${e.kind}">
          <span class="cal-t">${timeOf(e)}</span>
          <span class="cal-k"><span class="cal-dot" aria-hidden="true"></span>${esc(KIND[e.kind]?.s || e.kind)}</span>
          <span class="cal-main"><span class="cal-name">${e.ticker ? `<button type="button" class="tk-link" data-sym="${esc(e.ticker)}">${esc(e.ticker)}</button> ` : ""}<button type="button" class="cal-open" data-i="${reg(e)}">${esc(e.ticker ? e.title.replace(e.ticker + " ", "") : e.title)}</button> ${mk(e.market)}</span>
            ${e.detail ? `<span class="cal-detail">${esc(e.detail)}</span>` : ""}${e.last ? `<span class="cal-detail cal-last">Son: ${esc(e.last)}</span>` : ""}</span>
          <span class="cal-imp">${imp(e.importance)}</span>
          <span class="cal-src">${e.url ? `<a href="${esc(e.url)}" target="_blank" rel="noopener" aria-label="${esc(e.title)} kaynağı">Kaynak ↗</a>` : ""}</span>
        </li>`).join("")}</ul></li>`).join("")}</ol></div>`;
  }

  // ── ayrıntı penceresi
  function openDetail(e, opener) {
    const dlg = $("#calDlg");
    const when = `${dLabel(e.date, { weekday: "long", day: "numeric", month: "long", year: "numeric" })}${e.timed ? ` · ${hm(e)}` : ""}`;
    const meta = [KIND[e.kind]?.l || e.kind, e.inst, e.group, e.freq ? e.freq + " yayın" : ""].filter(Boolean);
    $("#calDlgBody").innerHTML = `
      <p class="cal-dlg-meta"><span class="cal-dot k-${e.kind}" aria-hidden="true"></span>${meta.map(esc).join(" · ")} ${mk(e.market)}</p>
      <h2 class="cal-dlg-t" id="calDlgTitle">${esc(shortTitle(e))}</h2>
      <p class="cal-dlg-when">${esc(when)}${e.period ? ` · dönem: ${esc(e.period)}` : ""} <span class="cal-rel">${rel(daysTo(e.date))}</span></p>
      ${e.detail ? `<p>${esc(e.detail)}</p>` : ""}
      ${e.last ? `<div class="cal-dlg-box"><span class="k-lbl">Son açıklanan</span><b>${esc(e.last)}</b><span class="k-note">Kaynak: TCMB EVDS</span></div>` : ""}
      ${e.assets?.length ? `<div class="cal-dlg-sec"><span class="k-lbl">Etkilediği varlıklar</span><div class="cal-assets">${e.assets.map(a => `<span class="tag">${esc(a)}</span>`).join("")}</div></div>` : ""}
      ${e.items?.length > 1 ? `<div class="cal-dlg-sec"><span class="k-lbl">Bu yayındaki tablolar</span><ul class="cal-items">${e.items.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>` : ""}
      <div class="cal-dlg-sec cal-dlg-imp"><span class="k-lbl">Önem</span>${imp(e.importance)} ${e.importance === 3 ? "yüksek" : e.importance === 2 ? "orta" : "düşük"}</div>
      <div class="cal-dlg-act">
        ${e.ticker ? `<button type="button" class="btn btn-sm" data-sym="${esc(e.ticker)}" id="calDlgTk">${esc(e.ticker)} sinyalleri</button>` : ""}
        ${e.url ? `<a class="btn btn-sm" href="${esc(e.url)}" target="_blank" rel="noopener">Kaynağa git ↗</a>` : ""}
      </div>`;
    S.opener = opener;
    dlg.showModal();
    $("#calDlgTk")?.addEventListener("click", () => { dlg.close(); sh.go("sinyal"); setTimeout(() => window.radar?.openTicker?.(e.ticker), 60); });
  }

  function render() {
    const box = $("#calBody");
    $$("#calView button").forEach(b => b.setAttribute("aria-checked", String(b.dataset.v === S.view)));
    $("#calRange").hidden = S.view !== "list";
    if (!S.loaded) { box.innerHTML = `<div class="card"><div class="skeleton sk-line w40"></div><div class="skeleton sk-line"></div><div class="skeleton sk-line w80"></div></div>`; return; }
    if (S.error && !S.cal) {
      box.innerHTML = `<div class="card">${sh.stateHTML({ kind: "error", title: "Takvim yüklenemedi", msg: esc(S.error.message) + ". Takvim ilk taramadan sonra oluşur.", action: "Tekrar dene", actionId: "calRetry" })}</div>`;
      $("#calRetry").onclick = () => { S.loaded = false; render(); load(); };
      return;
    }
    if (!S.anchor) S.anchor = todayISO();
    const all = (S.cal.events || []).filter(e => inMarket(e) && e.date >= todayISO());
    $("#calKinds").innerHTML = Object.entries(KIND).filter(([k]) => all.some(e => e.kind === k)).map(([k, v]) =>
      `<button type="button" class="chip" data-k="${k}" aria-pressed="${S.kinds.has(k)}">${esc(v.l)} <span class="n">${all.filter(e => e.kind === k).length}</span></button>`).join("");
    $$("#calRange button").forEach(b => b.setAttribute("aria-checked", String(+b.dataset.d === S.days)));
    $("#calImp").setAttribute("aria-pressed", String(S.important));
    S.idx = [];
    const body = S.view === "week" ? renderWeek() : S.view === "month" ? renderMonth() : renderList();
    const until = S.cal.tr_until, mu = S.cal.macro_until;
    box.innerHTML = body + `<p class="k-note">Saatler İstanbul saatiyle. Türkiye verileri TÜİK Ulusal Veri Yayımlama Takvimi'nden (TÜİK, TCMB, BDDK, Hazine ve Maliye Bakanlığı, SPK ve diğer kurumlar; otomatik${until ? `, ${fmt.date(until, { day: "numeric", month: "long" })} tarihine kadar` : ""}); son açıklanan değerler TCMB EVDS'ten · TCMB PPK, Fed ve ABD TÜFE resmi takvimlerden${mu ? ` (tanımlı son tarih ${fmt.date(mu, { day: "numeric", month: "long", year: "numeric" })})` : ""} · temettüler KAP'tan, bilançolar Yahoo Finance'ten (şirketler değiştirebilir), genel kurullar Borsa İstanbul listesinden · VİOP vade sonu çift ayların son iş günü, ABD opsiyon vadesi ayın 3. cuması olarak hesaplanır.</p>`;
  }
  function badge() {
    const n = (S.cal?.events || []).filter(e => inMarket(e) && e.importance >= 3 && [0, 1].includes(daysTo(e.date))).length;
    sh.setBadge("takvim", n, n ? `Bugün ve yarın ${n} önemli olay` : "");
  }
  function shift(dir) {
    if (dir === 0) S.anchor = todayISO();
    else if (S.view === "month") { const a = D(S.anchor); S.anchor = new Date(Date.UTC(a.getUTCFullYear(), a.getUTCMonth() + dir, 1, 12)).toISOString().slice(0, 10); }
    else S.anchor = addDays(S.anchor, 7 * dir);
    render();
  }
  function bind() {
    $("#calKinds").addEventListener("click", e => {
      const b = e.target.closest(".chip"); if (!b) return;
      S.kinds.has(b.dataset.k) ? S.kinds.delete(b.dataset.k) : S.kinds.add(b.dataset.k);
      store.set("radar.calKinds", [...S.kinds]); render(); $(`#calKinds .chip[data-k="${b.dataset.k}"]`)?.focus();
    });
    $$("#calRange button").forEach(b => b.onclick = () => { S.days = +b.dataset.d; store.set("radar.calDays", S.days); render(); });
    $$("#calView button").forEach(b => b.onclick = () => { S.view = b.dataset.v; store.set("radar.calView", S.view); render(); });
    sh.radioKeys?.($("#calRange")); sh.radioKeys?.($("#calView"));
    $("#calImp").onclick = () => { S.important = !S.important; store.set("radar.calImp", S.important); render(); };
    $("#calBody").addEventListener("click", e => {
      const nav = e.target.closest("[data-nav]");
      if (nav) { shift(+nav.dataset.nav); $(`#calBody [data-nav="${nav.dataset.nav}"]`)?.focus(); return; }
      const more = e.target.closest("[data-week]");
      if (more) { S.anchor = more.dataset.week; S.view = "week"; store.set("radar.calView", "week"); render(); return; }
      const t = e.target.closest(".tk-link");
      if (t) { sh.go("sinyal"); setTimeout(() => window.radar?.openTicker?.(t.dataset.sym, t), 60); return; }
      const o = e.target.closest("[data-i]");
      if (o && S.idx[+o.dataset.i]) openDetail(S.idx[+o.dataset.i], o);
    });
    $("#calBody").addEventListener("change", e => {
      if (e.target.id === "calPick" && e.target.value) { S.anchor = e.target.value; render(); $("#calPick")?.focus(); }
    });
    const dlg = $("#calDlg");
    $("#calDlgClose").onclick = () => dlg.close();
    dlg.addEventListener("click", e => { if (e.target === dlg) dlg.close(); });
    dlg.addEventListener("close", () => S.opener?.isConnected && S.opener.focus());
    addEventListener("marketchange", () => { badge(); if (sh.route === "takvim") render(); });
  }
  function rangeRows() {
    if (S.view === "list") return visible();
    if (S.view === "week") { const m = monday(S.anchor); return between(m, addDays(m, 6)); }
    const a = D(S.anchor), f = `${S.anchor.slice(0, 7)}-01`;
    return between(f, addDays(new Date(Date.UTC(a.getUTCFullYear(), a.getUTCMonth() + 1, 1, 12)).toISOString().slice(0, 10), -1));
  }
  function exportCSV() {
    const ex = window.radarExport; if (!ex) return;
    const rows = rangeRows().map(e => ({ tarih: e.date, saat_istanbul: e.timed ? timeOf(e) : "", tur: KIND[e.kind]?.l || e.kind, piyasa: e.market,
      kurum: e.inst || "", hisse: e.ticker || "", olay: e.title, donem: e.period || "", ayrinti: e.detail || "",
      son_aciklanan: e.last || "", etkiledigi: (e.assets || []).join("; "), onem: e.importance, kaynak: e.url || "" }));
    ex.download(`takvim_${ex.stamp()}.csv`, ex.toCSV(rows), "text/csv;charset=utf-8");
  }
  bind();
  sh.register("takvim", {
    onShow() { S.loaded ? render() : (render(), load()); },
    async refresh() { S.loaded = false; render(); await load(); },
    exports: () => [{ label: "Takvim (CSV)", hint: S.view === "list" ? `${RANGE[S.days] || S.days + " gün"}, filtreli` : `görünen ${S.view === "week" ? "hafta" : "ay"}, filtreli`, run: exportCSV, disabled: !S.cal }],
    exportInfo: () => S.cal ? `${S.view === "list" ? RANGE[S.days] : VIEWS[S.view]}${S.kinds.size ? ` · ${[...S.kinds].map(k => KIND[k].l).join(", ")}` : ""}${S.important ? " · yalnız önemli" : ""}` : "",
    exportNote: "Takvim henüz yüklenmedi",
  });
  setTimeout(() => { if (!S.loaded) load(); }, 1200);           // rozet için arka planda
})();
