/* config/watchlist.yml için küçük metin düzenleyici (functions/api/watchlist.js kullanır). */
// ───────────── YAML (yalnız bu dosyanın basit yapısı: bist:/us: altında "  - symbol: X" blokları)
export function parse(text) {
  const out = { bist: [], us: [] }; let sec = null, cur = null;
  for (const line of text.split("\n")) {
    const top = line.match(/^([a-z_]+):\s*$/);
    if (top) { sec = top[1] === "bist" ? "bist" : top[1] === "us" ? "us" : null; cur = null; continue; }
    const s = line.match(/^\s*-\s*symbol:\s*"?([A-Za-z0-9._-]+)"?\s*$/);
    if (s && sec) { cur = { symbol: s[1].toUpperCase() }; out[sec].push(cur); continue; }
    const f = line.match(/^\s{4}(name|tv|kap):\s*"?(.*?)"?\s*$/);
    if (f && cur) cur[f[1]] = f[2];
  }
  return out;
}
export function removeEntry(text, sym) {
  const L = text.split("\n");
  const i = L.findIndex(l => new RegExp(`^\\s*-\\s*symbol:\\s*"?${sym}"?\\s*$`, "i").test(l));
  if (i < 0) return null;
  let j = i + 1;
  while (j < L.length && /^\s{4,}\S/.test(L[j])) j++;
  L.splice(i, j - i);
  return L.join("\n");
}
export function addEntry(text, sec, e) {
  const L = text.split("\n");
  const h = L.findIndex(l => l.trim() === `${sec}:`);
  const q = v => JSON.stringify(v);
  const block = [`  - symbol: ${e.symbol}`, ...(e.tv ? [`    tv: ${e.tv}`] : []), `    name: ${q(e.name)}`, ...(e.kap ? [`    kap: ${e.kap}`] : []), `    aliases: ${q(e.aliases)}`];
  if (h < 0) return text.replace(/\s*$/, "\n") + `\n${sec}:\n${block.join("\n")}\n`;
  let end = h + 1;
  while (end < L.length && !/^[a-z_]+:\s*$/.test(L[end])) end++;
  let ins = end;
  while (ins > h + 1 && L[ins - 1].trim() === "") ins--;
  L.splice(ins, 0, ...block);
  return L.join("\n");
}

