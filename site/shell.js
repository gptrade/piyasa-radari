/* Piyasa Radarı — uygulama kabuğu.
   Yönlendirme (#makro · #sinyal · #geri-alim), tema, kenar çubuğu (masaüstünde daraltma, dar ekranda çekmece),
   üst eylem çubuğu (son güncelleme · yenile · dışa aktar · tema), piyasa filtresi, sekme rozetleri,
   kaynak sağlığı hapı, ortak ipucu ve Türkçe sayı biçimleri. Sekmeler kendilerini shell.register ile bağlar. */
(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const root = document.documentElement;
  const TZ = "Europe/Istanbul";

  // ─────────────────────────────── yardımcılar
  const store = {
    get(k, d) { try { const v = JSON.parse(localStorage.getItem(k)); return v ?? d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* özel pencere / engelli depolama */ } },
  };
  const esc = t => String(t ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // Sayılar: Türkçe biçim (1.234,56 · %3,5 · +%1,2 · −%0,8). Eksi işareti gerçek eksi (U+2212).
  const NF = new Map();
  const nf = d => NF.get(d) || NF.set(d, new Intl.NumberFormat("tr-TR", { minimumFractionDigits: d, maximumFractionDigits: d })).get(d);
  const MINUS = "−";
  const fmt = {
    num(v, d = 2) { return v == null || !isFinite(v) ? "—" : (v < 0 ? MINUS : "") + nf(d).format(Math.abs(v)); },
    int(v) { return fmt.num(v, 0); },
    pct(v, d = 1, signed = true) {
      if (v == null || !isFinite(v)) return "—";
      const r = +v.toFixed(d);
      if (r === 0) return "%" + nf(d).format(0);
      return (r > 0 ? (signed ? "+" : "") : MINUS) + "%" + nf(d).format(Math.abs(r));
    },
    money(v, cur, d = 2) { return v == null ? "—" : fmt.num(v, d) + (cur === "USD" ? " $" : cur === "TRY" || !cur ? " ₺" : " " + cur); },
    clock(t) { return new Date(t).toLocaleTimeString("tr-TR", { timeZone: TZ, hour: "2-digit", minute: "2-digit" }); },
    dt(t) { return new Date(t).toLocaleString("tr-TR", { timeZone: TZ, day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }); },
    date(t, o = { day: "numeric", month: "short" }) { return new Date(t).toLocaleDateString("tr-TR", { timeZone: TZ, ...o }); },
    full(t) { return new Date(t).toLocaleString("tr-TR", { timeZone: TZ, dateStyle: "long", timeStyle: "short" }); },
    ago(t, long = false) {
      const m = Math.round((Date.now() - new Date(t)) / 60000);
      const s = m < 1 ? "şimdi" : m < 60 ? `${m} dk` : m < 1440 ? `${Math.round(m / 60)} sa` : `${Math.round(m / 1440)} g`;
      return long && m >= 1 ? s + " önce" : s;
    },
    dayKey(t) { return new Date(t).toLocaleDateString("en-CA", { timeZone: TZ }); },   // YYYY-MM-DD (İstanbul)
  };
  // Yön glifi: renk asla tek başına anlam taşımaz
  const glyph = v => v == null ? "" : v > 0 ? "▲" : v < 0 ? "▼" : "●";
  const dirCls = (v, eps = 0) => v == null ? "" : v > eps ? "up" : v < -eps ? "down" : "flat";

  // ─────────────────────────────── durum
  const ROUTES = {
    makro: { title: "Makro Veri", sub: "Haftalık makroekonomik göstergeler · ALCO paneli", view: "#view-makro", market: false },
    takvim: { title: "Takvim", sub: "Faiz kararları, enflasyon verileri, bilançolar, temettü ve vade sonları · İstanbul saati", view: "#view-takvim", market: true },
    sinyal: { title: "Sinyal Takip", sub: "BIST ve ABD haber, bildirim ve sosyal medya sinyalleri", view: "#view-sinyal", market: true },
    portfoy: { title: "Portföy", sub: "Pozisyonlar, kâr/zarar, risk ve pozisyonlarındaki gelişmeler · yalnız bu tarayıcıda", view: "#view-portfoy", market: false },
    "geri-alim": { title: "Şirket Geri Alım", sub: "KAP pay geri alım bildirimleri · Borsa İstanbul", view: "#view-geri-alim", market: true },
  };
  const ALIAS = { alco: "makro", sinyaller: "sinyal", "geri-alimlar": "geri-alim", katalizor: "takvim", ajanda: "takvim", portfolio: "portfoy", "portföy": "portfoy" };
  const H = {};                                   // route → işleyiciler {refresh, exports, onShow, onHide, onMarket}
  const updatedAt = {};                           // route → {t, label, staleMin}
  const S = { route: null, market: store.get("radar.market", "ALL") };
  if (!["ALL", "BIST", "US"].includes(S.market)) S.market = "ALL";

  const shell = {
    $, $$, esc, fmt, store, glyph, dirCls, TZ,
    get route() { return S.route; },
    get market() { return S.market; },
    register(route, h) { H[route] = h; if (S.route === route) { h.onShow?.(); syncActions(); } },
    setUpdated(route, t, opt = {}) { updatedAt[route] = t ? { t: new Date(t), ...opt } : null; if (route === S.route) syncActions(); },
    syncActions: () => syncActions(),
    setBadge(route, n, label) {
      const b = $(`.nav-item[data-route="${route}"] .badge`);
      if (!b) return;
      b.hidden = !n; b.textContent = n > 99 ? "99+" : n || "";
      b.dataset.tip = label || ""; b.setAttribute("aria-label", label || "");
    },
    setMarket(m) { if (m !== S.market) { S.market = m; store.set("radar.market", m); syncMarket(); dispatchEvent(new CustomEvent("marketchange", { detail: m })); } },
    isDark: () => root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches,
    cssVar: name => getComputedStyle(root).getPropertyValue(name).trim(),
    go,
    setHealth,
    skeletonRows,
    stateHTML,
  };
  window.shell = shell;

  // ─────────────────────────────── ortak durum parçaları (iskelet / boş / hata)
  const ICONS = {
    empty: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="m20 20-3.5-3.5M8 11h6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>`,
    error: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 2.5 20h19L12 3z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M12 10v4.5M12 17.2v.3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>`,
    info: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M12 11v6M12 7.5v.3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>`,
  };
  function stateHTML({ kind = "empty", title, msg = "", action, actionId, compact = false }) {
    return `<div class="state ${kind === "error" ? "error" : ""} ${compact ? "compact" : ""}" role="${kind === "error" ? "alert" : "status"}">
      ${ICONS[kind] || ICONS.info}<p class="state-title">${esc(title)}</p>${msg ? `<p class="state-msg">${msg}</p>` : ""}
      ${action ? `<button type="button" class="btn ${kind === "error" ? "btn-primary" : ""}" id="${actionId || ""}">${esc(action)}</button>` : ""}</div>`;
  }
  function skeletonRows(cols, n = 8) {
    const w = ["w40", "w80", "w60", "w80", "w40"];
    return Array.from({ length: n }, (_, i) => `<tr aria-hidden="true">${Array.from({ length: cols }, (_, c) =>
      `<td><div class="skeleton sk-line ${c === 2 ? w[i % 5] : ""}"></div>${c === 2 ? `<div class="skeleton sk-line w40"></div>` : ""}</td>`).join("")}</tr>`).join("");
  }

  // ─────────────────────────────── yönlendirme
  function parseHash() {
    const h = decodeURIComponent(location.hash.replace(/^#/, ""));
    const r = ALIAS[h] || h;
    return ROUTES[r] ? r : null;
  }
  function go(route, { push = true, focus = false } = {}) {
    if (!ROUTES[route]) route = "sinyal";
    const prev = S.route;
    if (prev === route) return;
    if (prev) H[prev]?.onHide?.();
    S.route = route;
    store.set("radar.route", route);
    Object.entries(ROUTES).forEach(([k, r]) => { $(r.view).hidden = k !== route; });
    $$(".nav-item").forEach(a => a.dataset.route === route ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
    $("#pageTitle").textContent = ROUTES[route].title;
    $("#pageSub").textContent = ROUTES[route].sub;
    $("#pageSub").hidden = !ROUTES[route].sub;
    document.title = `${ROUTES[route].title} · Piyasa Radarı`;
    $("#marketSec").hidden = !ROUTES[route].market;
    const h = "#" + route;
    if (location.hash !== h) (push ? history.pushState : history.replaceState).call(history, null, "", h);
    closeMenu();
    if (isNarrow()) setDrawer(false);
    syncActions();
    H[route]?.onShow?.();
    if (focus) $("#main").focus({ preventScroll: true });
  }
  addEventListener("hashchange", () => go(parseHash() || "sinyal", { push: false }));
  $$(".nav-item").forEach(a => a.addEventListener("click", e => { e.preventDefault(); go(a.dataset.route, { focus: true }); }));

  // ─────────────────────────────── eylem çubuğu
  function syncUpdated() {
    const u = updatedAt[S.route], el = $("#updatedTime");
    if (!u) { el.textContent = "—"; el.removeAttribute("datetime"); $("#updated").title = ""; $("#updated").classList.remove("stale"); return; }
    el.textContent = fmt.clock(u.t);
    el.setAttribute("datetime", u.t.toISOString());
    const stale = u.staleMin && (Date.now() - u.t) / 60000 > u.staleMin;
    $("#updated").classList.toggle("stale", !!stale);
    $("#updated").title = `${u.label || "Son güncelleme"}: ${fmt.full(u.t)} (${fmt.ago(u.t, true)})${stale ? " — veri beklenenden eski" : ""}`;
  }
  function syncActions() {
    const h = H[S.route] || {};
    const ex = h.exports?.() || [];
    const exBtn = $("#exportBtn");
    exBtn.disabled = !ex.some(x => !x.disabled);
    exBtn.title = exBtn.disabled ? (h.exportNote || "Bu sekmede dışa aktarılacak veri yok") : "Görünümü dışa aktar";
    $("#refreshBtn").disabled = !h.refresh;
    syncUpdated();
  }
  setInterval(syncUpdated, 60 * 1000);

  $("#refreshBtn").addEventListener("click", async () => {
    const h = H[S.route], b = $("#refreshBtn");
    if (!h?.refresh || b.classList.contains("spin")) return;
    b.classList.add("spin"); b.setAttribute("aria-busy", "true");
    try { await h.refresh(); } finally { b.classList.remove("spin"); b.removeAttribute("aria-busy"); syncActions(); }
  });

  // Dışa aktar menüsü (klavye: ok tuşları, Esc)
  const menu = $("#exportMenu"), exBtn = $("#exportBtn");
  function openMenu() {
    const h = H[S.route] || {};
    const ex = h.exports?.() || [];
    menu.innerHTML = (h.exportInfo ? `<p class="menu-info">${esc(h.exportInfo())}</p>` : "") +
      ex.map((x, i) => `<button type="button" role="menuitem" data-i="${i}" ${x.disabled ? "disabled" : ""}>${esc(x.label)} <small>${esc(x.hint || "")}</small></button>`).join("");
    $$("[role=menuitem]", menu).forEach(b => b.addEventListener("click", () => { ex[+b.dataset.i].run(); closeMenu(true); }));
    menu.hidden = false; exBtn.setAttribute("aria-expanded", "true");
    $("[role=menuitem]:not(:disabled)", menu)?.focus();
  }
  function closeMenu(refocus = false) {
    if (menu.hidden) return;
    menu.hidden = true; exBtn.setAttribute("aria-expanded", "false");
    if (refocus) exBtn.focus();
  }
  exBtn.addEventListener("click", e => { e.stopPropagation(); menu.hidden ? openMenu() : closeMenu(); });
  menu.addEventListener("keydown", e => {
    const items = $$("[role=menuitem]:not(:disabled)", menu);
    const i = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown") { e.preventDefault(); items[(i + 1) % items.length]?.focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); items[(i - 1 + items.length) % items.length]?.focus(); }
    else if (e.key === "Escape" || e.key === "Tab") { closeMenu(e.key === "Escape"); }
  });
  document.addEventListener("click", e => { if (!e.target.closest(".menu-wrap")) closeMenu(); });

  // ─────────────────────────────── tema
  const themeBtn = $("#themeBtn");
  function syncTheme() {
    const d = shell.isDark();
    themeBtn.setAttribute("aria-pressed", String(d));
    themeBtn.setAttribute("aria-label", d ? "Açık temaya geç" : "Koyu temaya geç");
    themeBtn.dataset.tip = d ? "Açık temaya geç" : "Koyu temaya geç";
  }
  themeBtn.addEventListener("click", () => {
    root.dataset.theme = shell.isDark() ? "light" : "dark";
    store.set("radar.theme", root.dataset.theme);
    syncTheme();
    dispatchEvent(new Event("themechange"));
  });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { if (!root.dataset.theme) { syncTheme(); dispatchEvent(new Event("themechange")); } });
  syncTheme();

  // ─────────────────────────────── kenar çubuğu: masaüstünde daralt, dar ekranda çekmece
  const isNarrow = () => matchMedia("(max-width: 1023px)").matches;
  const menuBtn = $("#menuBtn"), scrim = $("#scrim"), sidebar = $("#sidebar");
  function setDrawer(open) {
    root.classList.toggle("drawer-open", open);
    scrim.hidden = !open;
    syncMenuBtn();
    if (open) setTimeout(() => $(".nav-item[aria-current]", sidebar)?.focus(), 60);   // görünürlük geçişi bitsin
  }
  function syncMenuBtn() {
    const open = isNarrow() ? root.classList.contains("drawer-open") : !root.classList.contains("side-off");
    menuBtn.setAttribute("aria-expanded", String(open));
    menuBtn.setAttribute("aria-label", open ? "Kenar çubuğunu kapat" : "Kenar çubuğunu aç");
    menuBtn.dataset.tip = open ? "Kenar çubuğunu kapat" : "Kenar çubuğunu aç";
    sidebar.inert = !open;
  }
  menuBtn.addEventListener("click", () => {
    if (isNarrow()) { setDrawer(!root.classList.contains("drawer-open")); return; }
    root.classList.toggle("side-off");
    store.set("radar.side", !root.classList.contains("side-off"));
    syncMenuBtn();
    dispatchEvent(new Event("resize"));
  });
  scrim.addEventListener("click", () => { setDrawer(false); menuBtn.focus(); });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && root.classList.contains("drawer-open")) { setDrawer(false); menuBtn.focus(); }
  });
  matchMedia("(max-width: 1023px)").addEventListener("change", () => { root.classList.remove("drawer-open"); scrim.hidden = true; syncMenuBtn(); });
  syncMenuBtn();

  // ─────────────────────────────── piyasa filtresi (Sinyal Takip + Şirket Geri Alım)
  function syncMarket() {
    $$("#marketSeg button").forEach(b => b.setAttribute("aria-checked", String(b.dataset.market === S.market)));
  }
  $$("#marketSeg button").forEach(b => b.addEventListener("click", () => shell.setMarket(b.dataset.market)));
  radioKeys($("#marketSeg"));
  syncMarket();

  // Segment gruplarında ok tuşlarıyla gezinme (role=radiogroup)
  function radioKeys(group) {
    // gezici tabindex: grupta yalnız seçili düğme Tab sırasında
    const rove = () => $$("[role=radio]", group).forEach(b => b.tabIndex = b.getAttribute("aria-checked") === "true" ? 0 : -1);
    new MutationObserver(rove).observe(group, { subtree: true, attributes: true, attributeFilter: ["aria-checked"] });
    rove();
    group.addEventListener("keydown", e => {
      if (!["ArrowRight", "ArrowLeft", "ArrowDown", "ArrowUp"].includes(e.key)) return;
      const bs = $$("[role=radio]", group), i = bs.indexOf(document.activeElement);
      if (i < 0) return;
      e.preventDefault();
      const n = bs[(i + (e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : -1) + bs.length) % bs.length];
      n.focus(); n.click();
    });
  }
  shell.radioKeys = radioKeys;

  // ─────────────────────────────── kaynak sağlığı hapı
  // Her kaynak: veri geldi · bu dönem veri yok · kısmi hata · başarısız · kapalı (anahtar yok)
  function srcState(s) {
    if (s.disabled) return "off";
    if (!s.ok) return "fail";
    if ((s.warnings || []).length && !s.count) return "warn";
    return s.count ? "ok" : "idle";
  }
  const SRC_IC = { ok: "✓", idle: "–", warn: "!", fail: "✕", off: "⏻" };
  function setHealth(feed) {
    const btn = $("#healthBtn"), list = $("#healthList");
    const all = feed?.sources || [];
    const data = all.filter(s => s.name !== "Telegram");
    const st = data.map(s => [s, srcState(s)]);
    const active = st.filter(([, k]) => k === "ok" || k === "idle").length;
    const fails = st.filter(([, k]) => k === "fail" || k === "warn").length;
    const level = !data.length ? "" : fails === 0 ? "ok" : fails <= 2 ? "warn" : "bad";
    btn.className = "health " + level;
    $(".sym", btn).textContent = { ok: "✓", warn: "!", bad: "✕" }[level] || "";
    $("#healthTxt").textContent = data.length ? `${active}/${data.length} kaynak aktif` : "Kaynak durumu yok";
    btn.dataset.tip = data.length ? `${active} kaynak çalışıyor${fails ? ` · ${fails} hatalı` : ""}${st.some(([, k]) => k === "off") ? ` · ${st.filter(([, k]) => k === "off").length} kapalı` : ""} — ayrıntı için tıkla` : "";
    const when = t => t ? fmt.ago(t, true) : null;
    const rows = st.map(([s, k]) => {
      const last = s.last_ok ? `son başarılı ${when(s.last_ok)}` : "henüz başarılı çekim yok";
      const lastData = s.last_data ? `son veri ${when(s.last_data)}` : "";
      const line = {
        ok: `Başarılı · bu turda ${fmt.int(s.count)} yeni kayıt`,
        idle: `Başarılı · bu dönem yeni veri yok${lastData ? " · " + lastData : ""}`,
        warn: `Kısmi hata: ${(s.warnings || [])[0] || "bağlantı sorunu"} · ${last}`,
        fail: `Başarısız: ${s.error || "bilinmeyen hata"} · ${last}`,
        off: `Kapalı: ${s.disabled}`,
      }[k];
      return `<div class="src ${k}" title="${esc([s.error, ...(s.warnings || [])].filter(Boolean).join("\n"))}">
        <span class="src-ic" aria-hidden="true">${SRC_IC[k]}</span><span class="src-name">${esc(s.name)}</span>
        <span class="src-n">${k === "ok" ? "+" + fmt.int(s.count) : ""}</span>
        <span class="src-st">${esc(line)}</span></div>`;
    }).join("");
    const tg = all.find(s => s.name === "Telegram");
    const sec = feed?.secrets || {};
    const hasAI = sec.ANTHROPIC_API_KEY || sec.GEMINI_API_KEY;
    const missing = Object.entries(sec).filter(([k, v]) => !v && !["X_BEARER_TOKEN", "EVDS_API_KEY"].includes(k) && !((k === "ANTHROPIC_API_KEY" || k === "GEMINI_API_KEY") && hasAI)).map(([k]) => k);
    const ai = feed?.ai || {};
    const by = Object.entries(ai.by_provider || {}).map(([k, v]) => `${k} ${v}`).join(", ");
    list.innerHTML = rows +
      (tg ? `<p class="health-meta">Telegram bildirimi: ${tg.ok ? (tg.count ? `✓ bu turda ${tg.count} gönderildi` : "✓ çalışıyor, bu turda gönderilecek sinyal yok") : "✕ " + esc(tg.error || "hata")}${(tg.warnings || [])[0] ? " · " + esc(tg.warnings[0]) : ""}</p>` : "") +
      `<p class="health-meta">AI: ${ai.enabled ? esc((ai.providers || []).join(" → ")) + (by ? ` (${esc(by)})` : "") : "kapalı"}${feed?.generated ? ` · tur ${fmt.clock(feed.generated)}` : ""}</p>` +
      (missing.length ? `<p class="health-meta warn">Tanımlı olmayan secret: ${esc(missing.join(", "))}</p>` : "") +
      ((ai.errors || [])[0] ? `<p class="health-meta warn">AI: ${esc(ai.errors[0])}</p>` : "");
  }
  $("#healthBtn").addEventListener("click", () => {
    const b = $("#healthBtn"), open = b.getAttribute("aria-expanded") !== "true";
    b.setAttribute("aria-expanded", String(open));
    $("#healthList").hidden = !open;
  });

  // ─────────────────────────────── ipucu: fare ve klavye odağıyla
  const tip = $("#tip");
  let tipFor = null;
  function showTip(el, x, y) {
    const html = el.dataset.tip;
    if (!html) return hideTip();
    tipFor = el; tip.innerHTML = html; tip.hidden = false;
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = Math.max(8, Math.min(x + 14, innerWidth - w - 8)) + "px";
    tip.style.top = (y + 18 + h > innerHeight ? y - h - 10 : y + 18) + "px";
  }
  function hideTip() { tip.hidden = true; tipFor = null; }
  document.addEventListener("mouseover", e => { const t = e.target.closest?.("[data-tip]"); t ? showTip(t, e.clientX, e.clientY) : hideTip(); });
  document.addEventListener("mousemove", e => { if (tipFor) showTip(tipFor, e.clientX, e.clientY); });
  document.addEventListener("focusin", e => {
    const t = e.target.closest?.("[data-tip]");
    if (!t || !e.target.matches(":focus-visible")) return hideTip();
    const r = t.getBoundingClientRect(); showTip(t, r.left, r.bottom - 8);
  });
  document.addEventListener("focusout", hideTip);
  addEventListener("scroll", hideTip, { passive: true });
  document.addEventListener("keydown", e => { if (e.key === "Escape") hideTip(); });

  // ─────────────────────────────── Makro Veri (ayrı site; iframe)
  // ALCO içine stil verilemez: başlık üstten kırpılır, koyu temada renk çevrilir (style.css).
  // Uygulama ileride ?embed=1&theme= desteklerse kendi başlığını gizleyip kendi koyu temasını kullanabilir.
  const frame = $("#alcoFrame");
  const alcoUrl = () => { const u = new URL(frame.dataset.src); u.searchParams.set("embed", "1"); u.searchParams.set("theme", shell.isDark() ? "dark" : "light"); return u.href; };
  let alcoTimer;
  function loadAlco() {
    $("#alcoSkel").hidden = false;
    clearTimeout(alcoTimer);
    return new Promise(res => {
      const done = () => { $("#alcoSkel").hidden = true; shell.setUpdated("makro", new Date(), { label: "Panel yüklendi" }); res(); };
      frame.onload = done;
      alcoTimer = setTimeout(done, 15000);          // bazı durumlarda load olayı gelmez: iskeleti yine kaldır
      frame.src = alcoUrl();
    });
  }
  shell.register("makro", {
    onShow() { if (!frame.getAttribute("src")) loadAlco(); },
    refresh: loadAlco,
    exports: () => [],
    exportNote: "Makro Veri ayrı bir uygulamada; dışa aktarma o panelin içinden yapılır",
  });
  addEventListener("themechange", () => { if (frame.getAttribute("src")) loadAlco(); });

  // ─────────────────────────────── başlangıç: sekmeler kaydolduktan sonra
  addEventListener("DOMContentLoaded", () => {
    const hashRoute = parseHash();
    go(hashRoute || store.get("radar.route", "sinyal"), { push: false });
  });
})();
