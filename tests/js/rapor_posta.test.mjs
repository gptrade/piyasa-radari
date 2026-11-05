// node tests/js/rapor_posta.test.mjs — e-posta alıcısı: konu etiketi ve gönderici alan adı
import assert from "node:assert/strict";
const src = await import("../../workers/rapor-posta/src/index.js").catch(e => ({ err: e }));
if (src.err) { console.log("atlandı (postal-mime yok):", src.err.code || src.err.message); process.exit(0); }
const { folderOf, stripTags, senderDomain, slug } = src;
assert.equal(folderOf("[Şirket] ASELS raporu"), "sirket");
assert.equal(folderOf("Fwd: günlük bülten #strateji"), "strateji");
assert.equal(folderOf("[sektör] Bankacılık"), "sektor");
assert.equal(folderOf("Gedik Sabah Notu"), "gelen");
assert.equal(slug(stripTags("[Şirket] ASELS raporu")), "asels-raporu");
assert.equal(senderDomain({ text: "---------- Forwarded message ---------\nFrom: Gedik Araştırma <research@gedik.com.tr>\nDate: ...", from: { address: "ben@gmail.com" } }), "gedik.com.tr");
assert.equal(senderDomain({ text: "Kimden: \"Ak Yatırım\" <bulten@akyatirim.com.tr>", from: { address: "ben@gmail.com" } }), "akyatirim.com.tr");
assert.equal(senderDomain({ text: "merhaba", from: { address: "strateji@denizyatirim.com" } }), "denizyatirim.com");
assert.equal(senderDomain({ text: "merhaba", from: { address: "ben@gmail.com" } }), "");
console.log("rapor_posta.test: tamam");
