/* Piyasa Radarı — Uluslararası Regülasyon Takip.
   Veri: data/regulasyon/regwatch.json (regulasyon.yml, günlük). BCBS/BIS, Azerbaycan, Türkiye, Körfez ve Orta Doğu bankacılık
   düzenleyicilerinin risk yönetimi ve model validasyonu yayınları; kaynak gösteren Google araması (Gemini) ile bulunur. */
(() => {
  "use strict";
  const sh = window.shell;
  const { $, $$, esc, fmt } = sh;
  const SRC = "data/regulasyon/regwatch.json";
  const PERIODS = { 30: "30G", 90: "90G", 180: "6A", 365: "1Y" };
  const S = { doc: null, loaded: false, loading: false, error: null, missing: false, days: 90, reg: "", topic: "", type: "", q: "", limit: 40 };

  async function load(force = false) {
    if (S.loading || (S.loaded && !force)) return;
    S.loading = true; S.error = null; S.missing = false;
    if (!S.loaded) renderLoading();
    try {
      const r = await fetch(`${SRC}?t=${Date.now()}`, { cache: "no-store" });
      if (r.status === 404) { S.missing = true; throw new Error("veri yok"); }
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      S.doc = await r.json();
      S.doc.regById = Object.fromEntries((S.doc.regulators || []).map(x => [x.id, x]));
      S.doc.topicById = Object.fromEntries((S.doc.topics || []).map(x => [x.key, x.label]));
      S.loaded = true;
      sh.setUpdated("regulasyon", new Date(S.doc.generated), { label: "Tarama", staleMin: 60 * 48 });
    } catch (e) { S.error = e.message || "veri okunamadı"; }
    finally { S.loading = false; }
    S.loaded ? render() : renderError();
  }

  const dayOf = it => it.date || (it.first_seen || "").slice(0, 10);
  function filtered() {
    const d = S.doc, since = new Date(Date.now() - S.days * 864e5).toISOString().slice(0, 10), q = S.q.toLocaleLowerCase("tr");
    return d.items.filter(it => dayOf(it) >= since && (!S.reg || it.reg === S.reg) && (!S.topic || (it.topics || []).includes(S.topic)) &&
      (!S.type || it.type === S.type) && (!q || `${it.title} ${it.title_tr || ""} ${it.summary || ""}`.toLocaleLowerCase("tr").includes(q)));
  }

  function summaryCard() {
    const s = S.doc.summary, d = S.doc;
    if (!s) return `<section class="card"><h2 class="card-title">Yönetici özeti</h2><p class="meta rg-meta">Özet, yeterli doküman birikince (en az 3) haftalık olarak üretilecek.</p></section>`;
    return `<section class="card rg-sum" aria-labelledby="rgSumT"><div class="card-head"><h2 class="card-title" id="rgSumT">Yönetici özeti · dönemin en kritik 3 eğilimi</h2>
      <span class="card-meta">${esc(fmt.date(s.date + "T12:00:00Z", { day: "numeric", month: "long", year: "numeric" }))} · son 90 gün, ${s.n_docs} doküman · AI özeti</span></div>
      <ol class="rg-trends">${(s.trends || []).map(t => `<li><b>${esc(t.title || "")}</b><p>${esc(t.detail || "")}</p>
        ${t.tr_impact ? `<p class="rg-tr"><span class="tag na">TR</span> ${esc(t.tr_impact)}</p>` : ""}
        ${(t.regulators || []).length ? `<p class="meta rg-meta">${(t.regulators || []).map(esc).join(" · ")}</p>` : ""}</li>`).join("")}</ol></section>`;
  }
  function table(rows) {
    const d = S.doc, shown = rows.slice(0, S.limit);
    return `<section class="card card-flush" aria-labelledby="rgTblT"><div class="card-head"><h2 class="card-title" id="rgTblT">Detaylı bulgular (${rows.length})</h2>
      <span class="card-meta">yayın tarihine göre · başlık resmi dokümana gider</span></div>
      <div class="tbl-scroll"><table class="tbl rg-tbl"><thead><tr><th scope="col">Kurum / ülke</th><th scope="col">Yayın tarihi</th><th scope="col">Doküman başlığı</th><th scope="col">Türü</th><th scope="col">Konular</th></tr></thead><tbody>
      ${shown.map(it => { const r = d.regById[it.reg] || {}; return `<tr>
        <td class="rg-reg"><b>${esc(r.name || it.reg)}</b><span class="meta">${esc(r.country || "")}</span></td>
        <td class="rg-date">${it.date ? esc(fmt.date(it.date + "T12:00:00Z", { day: "numeric", month: "short", year: "numeric" })) : `<span class="meta" data-tip="Yayın tarihi bulunamadı; ilk görüldüğü gün">${esc(fmt.date(it.first_seen, { day: "numeric", month: "short" }))}*</span>`}</td>
        <td class="rg-title"><a href="${esc(it.url)}" target="_blank" rel="noopener">${esc(it.title)} ↗</a>${it.title_tr && it.title_tr !== it.title ? `<span class="rg-tr-title">${esc(it.title_tr)}</span>` : ""}${it.summary ? `<p class="rg-s">${esc(it.summary)}</p>` : ""}</td>
        <td><span class="tag ${it.type === "taslak" ? "warn" : it.type === "nihai" ? "up" : ""}">${esc(d.types[it.type] || it.type)}</span></td>
        <td class="rg-topics">${(it.topics || []).map(k => `<span class="rg-chip">${esc(d.topicById[k] || k)}</span>`).join("")}</td></tr>`; }).join("")}
      </tbody></table>
      ${rows.length > shown.length ? `<div class="tbl-foot"><span>${shown.length} / ${rows.length}</span><button type="button" class="link-btn" id="rgMore">Daha fazla</button></div>` : ""}
      ${rows.length ? "" : sh.stateHTML({ kind: "empty", title: "Bu süzgeçte doküman yok", msg: "Dönemi uzatmayı ya da filtreleri kaldırmayı dene." })}</div></section>`;
  }
  function coverage() {
    const d = S.doc, runs = d.runs || {};
    const cnt = {}; d.items.forEach(it => { cnt[it.reg] = (cnt[it.reg] || 0) + 1; });
    return `<section class="card" aria-labelledby="rgCovT"><div class="card-head"><h2 class="card-title" id="rgCovT">Kaynak taraması</h2><span class="card-meta">her kurum yaklaşık haftada bir taranır</span></div>
      <div class="rg-cov">${(d.regulators || []).map(r => { const x = runs[r.id];
        return `<div class="rg-cov-i ${x && !x.ok ? "bad" : ""}"><b>${esc(r.name)}</b><span class="meta">${x ? `${x.ok ? "tarandı" : "hata"} ${esc(fmt.date(x.at))} · ${cnt[r.id] || 0} doküman` : "henüz taranmadı"}</span></div>`; }).join("")}</div></section>`;
  }

  function render() {
    if (sh.route !== "regulasyon") return;
    if (!S.loaded) return S.error ? renderError() : renderLoading();
    const d = S.doc;
    $("#rgReg").innerHTML = `<option value="">Tüm kurumlar</option>` + d.regulators.map(r => `<option value="${esc(r.id)}" ${S.reg === r.id ? "selected" : ""}>${esc(r.name)}</option>`).join("");
    $("#rgTopic").innerHTML = `<option value="">Tüm konular</option>` + d.topics.map(t => `<option value="${esc(t.key)}" ${S.topic === t.key ? "selected" : ""}>${esc(t.label)}</option>`).join("");
    $("#rgType").innerHTML = `<option value="">Tüm türler</option>` + Object.entries(d.types).map(([k, v]) => `<option value="${k}" ${S.type === k ? "selected" : ""}>${esc(v)}</option>`).join("");
    $("#rgSrc").innerHTML = `Kaynak: kurumların resmi siteleri, kaynak gösteren Google araması (Gemini) ile · faiz kararları, enflasyon raporları ve rutin makro duyurular hariç · ${fmt.int(d.items.length)} doküman · güncelleme ${fmt.dt(d.generated)}`;
    const rows = filtered();
    $("#rgBody").innerHTML = `<div class="view" style="gap:var(--s-4)">${summaryCard()}${table(rows)}${coverage()}
      <p class="en-note">Dokümanlar, her kurumun yalnız kendi alan adında yapılan Google aramasının gösterdiği sonuçlardan alınır; link aramanın kaynaklarında yoksa ya da kurumun sitesinde değilse kayıt atılır. Konu etiketleri ve Türkçe özetler AI ile üretilir; düzenleyici bağlayıcılık ve yürürlük tarihleri için orijinal dokümana bak. Bazı kurumlar (ör. İran, Lübnan) yayınlarını sınırlı ya da yalnız yerel dilde paylaşır; arama bunları kaçırabilir.</p></div>`;
    $("#rgMore")?.addEventListener("click", () => { S.limit += 40; render(); });
  }
  function renderLoading() {
    $("#rgSrc").innerHTML = `<span class="skeleton sk-line w40" style="display:inline-block;width:320px"></span>`;
    $("#rgBody").innerHTML = `<div class="view" style="gap:var(--s-4)" aria-busy="true"><div class="card"><div class="skeleton sk-line w40"></div><div class="skeleton" style="height:90px;margin-top:12px"></div></div>
      <div class="card card-flush"><table class="tbl"><tbody>${sh.skeletonRows(5, 8)}</tbody></table></div></div>`;
  }
  function renderError() {
    $("#rgSrc").textContent = "";
    $("#rgBody").innerHTML = S.missing ? sh.stateHTML({ kind: "info", title: "Regülasyon taraması henüz oluşmadı", msg: "İlk tarama tamamlanınca bulgular burada görünecek." }) :
      sh.stateHTML({ kind: "error", title: "Regülasyon verisi yüklenemedi", msg: esc(S.error), action: "Tekrar dene", actionId: "rgRetry" });
    $("#rgRetry")?.addEventListener("click", () => load(true));
  }

  function exportCSV() {
    const ex = window.radarExport, d = S.doc;
    const rows = filtered().map(it => ({ kurum: d.regById[it.reg]?.name || it.reg, ulke: d.regById[it.reg]?.country || "", yayin_tarihi: it.date || "", baslik: it.title,
      baslik_tr: it.title_tr || "", tur: d.types[it.type] || it.type, konular: (it.topics || []).map(k => d.topicById[k] || k).join("; "), ozet: it.summary || "", link: it.url, ilk_gorulme: it.first_seen }));
    ex.download(`regulasyon_${S.days}g_${ex.stamp()}.csv`, ex.toCSV(rows), "text/csv;charset=utf-8");
  }

  $$("#rgPeriod button").forEach(b => b.onclick = () => { S.days = +b.dataset.d; S.limit = 40; $$("#rgPeriod button").forEach(x => x.setAttribute("aria-checked", String(x === b))); render(); });
  sh.radioKeys($("#rgPeriod"));
  $("#rgReg").onchange = e => { S.reg = e.target.value; S.limit = 40; render(); };
  $("#rgTopic").onchange = e => { S.topic = e.target.value; S.limit = 40; render(); };
  $("#rgType").onchange = e => { S.type = e.target.value; S.limit = 40; render(); };
  let t; $("#rgQ").oninput = e => { clearTimeout(t); t = setTimeout(() => { S.q = e.target.value.trim(); S.limit = 40; render(); }, 150); };

  sh.register("regulasyon", {
    onShow() { S.loaded ? render() : load(); },
    async refresh() { await load(true); },
    exports: () => [{ label: "Bulgular (CSV)", hint: `${PERIODS[S.days] || S.days + "G"} · filtreye göre`, run: exportCSV, disabled: !S.loaded }],
    exportInfo: () => S.loaded ? `Dönem: son ${S.days} gün` : "",
    exportNote: "Regülasyon verisi henüz yüklenmedi",
  });
})();
