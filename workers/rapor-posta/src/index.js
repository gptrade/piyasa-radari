// rapor@<alan adı> → gizli rapor reposunun gelen/ klasörü.
// - Yalnız izinli göndericiler (GONDERENLER: "ad@x.com, @kurum.com.tr") kabul edilir; diğerleri reddedilir.
// - PDF ve görsel ekler olduğu gibi kaydedilir; eki olmayan uzun bültenler metin (.md) olarak kaydedilir.
// - Dosya adı içerik özetiyle (sha1) başlar: aynı rapor iki kez gelirse ikinci kez yazılmaz.
// - Posta içeriği hiçbir yerde yayımlanmaz; radar iş akışı repoyu çekip özetler (siteye yalnız yapılandırılmış alanlar).
import PostalMime from "postal-mime";

const EXT = { "application/pdf": "pdf", "image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png" };
const MIN_IMG = 40_000;          // imza/logo görsellerini atla
const MAX_FILE = 20_000_000;
const MIN_TEXT = 800;            // eksiz postada bu kadar metin yoksa bülten sayılmaz

// Gmail otomatik iletmede zarf göndericisi "ad+caf_=rapor=lyracube.com@gmail.com" olur: "+..." kısmı atılır.
export function bare(addr) {
  const f = String(addr || "").trim().toLowerCase();
  const at = f.lastIndexOf("@");
  return at < 0 ? f : f.slice(0, at).split("+")[0] + f.slice(at);
}

export function allowed(from, list) {
  const f = bare(from);
  return String(list || "").toLowerCase().split(/[\s,;]+/).filter(Boolean)
    .some(a => a.startsWith("@") ? f.endsWith(a) : f === bare(a));
}

// Gmail "iletme onayı" postası: kod ve bağlantı Telegram'a gönderilir, rapor olarak kaydedilmez.
export function gmailConfirm(mail) {
  const from = String(mail.from?.address || "").toLowerCase();
  if (!from.endsWith("@google.com") || !/forwarding|iletme|yönlendirme/i.test(mail.subject || "")) return null;
  const text = mail.text || String(mail.html || "").replace(/<[^>]+>/g, " ");
  const code = (text.match(/\b\d{9}\b/) || [])[0] || null;
  const link = (text.match(/https:\/\/mail[-.]settings\.google\.com\/\S+/) || text.match(/https:\/\/mail\.google\.com\/mail\/vf-\S+/) || [])[0] || null;
  return { code, link };
}

async function tg(env, text) {
  if (!env.TG_TOKEN || !env.TG_CHAT) return;
  try {
    await fetch(`https://api.telegram.org/bot${env.TG_TOKEN}/sendMessage`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: env.TG_CHAT, text, disable_web_page_preview: true }),
    });
  } catch (e) { /* bildirim isteğe bağlı */ }
}

export function slug(s, n = 40) {
  const map = { ç: "c", ğ: "g", ı: "i", ö: "o", ş: "s", ü: "u", Ç: "c", Ğ: "g", İ: "i", Ö: "o", Ş: "s", Ü: "u" };
  return String(s || "").replace(/[çğıöşüÇĞİÖŞÜ]/g, c => map[c]).toLowerCase()
    .replace(/^(fw|fwd|ileti|ynt|re)\s*:\s*/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, n) || "rapor";
}

function extOf(att) {
  const m = (att.mimeType || "").toLowerCase();
  if (EXT[m]) return EXT[m];
  const e = (att.filename || "").toLowerCase().match(/\.(pdf|jpe?g|png)$/);
  return e ? (e[1] === "jpeg" ? "jpg" : e[1]) : null;
}

export function pick(mail) {
  const files = [];
  for (const att of mail.attachments || []) {
    const ext = extOf(att);
    const size = att.content?.byteLength || 0;
    if (!ext || size > MAX_FILE) continue;
    if (ext !== "pdf" && size < MIN_IMG) continue;
    files.push({ ext, data: new Uint8Array(att.content) });
  }
  if (!files.length) {
    const text = (mail.text || String(mail.html || "").replace(/<style[\s\S]*?<\/style>|<script[\s\S]*?<\/script>/gi, "")
      .replace(/<[^>]+>/g, " ").replace(/&nbsp;/g, " ")).replace(/[ \t]+/g, " ").replace(/\n{3,}/g, "\n\n").trim();
    const links = (text.match(/https?:\/\/\S+/g) || []).length + (String(mail.html || "").match(/<a\s[^>]*href=/gi) || []).length;
    const prose = text.replace(/https?:\/\/\S+/g, "").replace(/\s+/g, " ").trim();
    // Uzun gövde = bültenin kendisi; kısa gövde + bağlantı = rapor indirme bağlantısıyla gönderilmiş (okunamaz)
    if (prose.length >= MIN_TEXT * 2 || (prose.length >= MIN_TEXT && !links)) {
      files.push({ ext: "md", data: new TextEncoder().encode(`# ${mail.subject || ""}\n\n${text}`) });
    } else if (links) {
      files.linkOnly = true;
    }
  }
  return files;
}

async function sha1(data) {
  const h = new Uint8Array(await crypto.subtle.digest("SHA-1", data));
  return [...h].map(b => b.toString(16).padStart(2, "0")).join("");
}

function b64(data) {
  let s = "";
  for (let i = 0; i < data.length; i += 0x8000) s += String.fromCharCode(...data.subarray(i, i + 0x8000));
  return btoa(s);
}

async function put(env, path, data, msg) {
  const r = await fetch(`https://api.github.com/repos/${env.RAPOR_REPO}/contents/${path}`, {
    method: "PUT",
    headers: { Authorization: `Bearer ${env.GH_TOKEN}`, "User-Agent": "rapor-posta", Accept: "application/vnd.github+json" },
    body: JSON.stringify({ message: msg, content: b64(data) }),
  });
  if (r.status === 422) return "var";            // aynı dosya zaten kayıtlı
  if (!r.ok) throw new Error(`GitHub ${r.status}: ${(await r.text()).slice(0, 200)}`);
  return "yazildi";
}

export default {
  async email(message, env) {
    const sender = String(message.from || "").toLowerCase();
    if (sender.endsWith("@google.com")) {          // Gmail iletme onayı: kodu Telegram'a gönder
      const mail = await PostalMime.parse(message.raw);
      const c = gmailConfirm(mail);
      if (c) {
        await tg(env, `📮 Gmail iletme onayı (rapor@)\nOnay kodu: ${c.code || "bulunamadı"}${c.link ? `\nBağlantı: ${c.link}` : ""}`);
        return;
      }
    }
    if (!allowed(message.from, env.GONDERENLER)) {
      await tg(env, `⛔ rapor@ adresine izinsiz gönderici: ${bare(message.from)}\nKabul edilmesi için RAPOR_GONDERENLER secret'ına ekleyip eposta-kurulum iş akışını çalıştır.`);
      message.setReject("Bu adres yalnız kayıtlı göndericilerden posta kabul eder.");
      return;
    }
    const mail = await PostalMime.parse(message.raw);
    const files = pick(mail);
    if (!files.length) {
      const who = mail.from?.name || mail.from?.address || "";
      await tg(env, files.linkOnly
        ? `📎 rapor@: "${mail.subject || ""}" (${who}) — ek yok, rapor bağlantıda. PDF'i indirip ek olarak iletirsen işlenir.`
        : `📭 rapor@: "${mail.subject || ""}" geldi ama ek ya da bülten metni yok, atlandı.`);
      return;
    }
    const day = new Date().toISOString().slice(0, 10);
    const base = slug(mail.subject);
    let ok = 0, dup = 0;
    const errs = [];
    for (const f of files) {
      const h = await sha1(f.data);
      try {
        const r = await put(env, `gelen/${day}_${base}-${h.slice(0, 10)}.${f.ext}`, f.data, `Gelen rapor ${day}`);
        r === "var" ? dup++ : ok++;
      } catch (e) {
        errs.push(String(e.message || e).slice(0, 160));
      }
    }
    // Kayıt hatası artık sessiz kalmaz (eskiden hata fırlatılıyor, posta kayboluyordu)
    if (errs.length) {
      await tg(env, `❌ rapor@: "${mail.subject || ""}" kaydedilemedi (${errs.length}/${files.length} dosya).\n${errs[0]}\nGitHub anahtarının süresi dolmuş olabilir: RAPOR_YAZMA_TOKEN'ı yenileyip eposta-kurulum iş akışını çalıştır.`);
    }
    if (ok || dup) {
      await tg(env, ok ? `📥 rapor@: "${mail.subject || ""}" alındı (${ok} dosya${dup ? `, ${dup} tanesi zaten vardı` : ""}). Radar 15–30 dk içinde özetler.`
                       : `♻️ rapor@: "${mail.subject || ""}" daha önce alınmış (aynı dosya), yeniden işlenmedi.`);
    }
  },
};
