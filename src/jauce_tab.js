// Jauce (Yahoo! Auctions Japan) crawl in a www.jauce.com tab, for jauce_photos.py. Set before loading: window.JC_PASS
// (the pass name, as the queries'), window.JC_QUEUE (the queries). A search is a fetch() of /search/<words joined by +>
// (the tab must have passed Jauce's "Loading..." cookie page once, by one search typed in its own search box); 404 with
// "No results found." is zero results. Results: {release: [{id, title, image (the path after auctions.c.yimg.jp/), w, h}]},
// at most 10, boxed listings (box, manual, unopened) last; batches downloaded as jauce-<pass>-batch-<n>.json.
(function () {
const pass = window.JC_PASS, key = 'JC.results.' + pass;
const JC = window.JC = {pass, results: {}, queue: [], running: false, done: 0};
try { JC.results = JSON.parse(localStorage.getItem(key) || '{}'); } catch (e) {}
// left out: not a cartridge (box or manual only, no cartridge, guides, consoles, accessories, repros); lots kept (the user, 2026-11-17)
JC.BAD = /外箱のみ|箱のみ|空箱|説明書のみ|ソフト(なし|無し)|攻略本|ガイドブック|ケースのみ|ポスター|チラシ|本体|アダプタ|ケーブル|リプロ|互換/;
JC.BOXED = /箱(?!なし|無)|説明書(?!なし|無)|未開封/;
JC.norm = s => s.normalize('NFKC').toLowerCase();
JC.sleep = ms => new Promise(r => setTimeout(r, ms));
JC.search = async function (q) {
  const r = await fetch('/search/' + q.query.split(/\s+/).map(encodeURIComponent).join('+'), {credentials: 'include'});
  const html = await r.text();
  if (r.status === 404 && /No results found/i.test(html)) return [];
  if (!r.ok) { const e = new Error('HTTP ' + r.status); e.http = r.status; throw e; }
  if (/Loading\.\.\./.test(html) && !/\/auction\//.test(html)) { const e = new Error('loading page'); e.http = 0; throw e; }
  const doc = new DOMParser().parseFromString(html, 'text/html');
  const exclude = new RegExp(q.exclude), plain = [], boxed = [];
  for (const li of doc.querySelectorAll('li')) {
    const a = li.querySelector('a[href*="/auction/"]'), img = li.querySelector('img[src*="auctions.c.yimg.jp/"]');
    if (!a || !img) continue;
    const id = (a.getAttribute('href').match(/\/auction\/([a-z]?\d+)/) || [])[1]; if (!id) continue;
    const title = (img.getAttribute('alt') || '').trim();
    const image = img.getAttribute('src').split('auctions.c.yimg.jp/')[1].split('?')[0];
    const wh = image.match(/i-img(\d+)x(\d+)-/) || [];
    const t = JC.norm(title);
    if (JC.BAD.test(t) || exclude.test(title) || !q.parts.every(p => t.includes(JC.norm(p)))) continue;
    if (plain.concat(boxed).some(o => o.id === id)) continue;
    (JC.BOXED.test(t) ? boxed : plain).push({id, title, image, w: +wh[1] || 0, h: +wh[2] || 0});
  }
  return plain.concat(boxed).slice(0, 10);
};
JC.flushed = new Set(); JC.batch = 0;
JC.flush = function () {
  const part = {};
  for (const [r, v] of Object.entries(JC.results)) if (!JC.flushed.has(r)) { part[r] = v; JC.flushed.add(r); }
  if (!Object.keys(part).length) return 0;
  JC.batch++;
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(part)], {type: 'application/json'}));
  a.download = 'jauce-' + pass + '-batch-' + String(JC.batch).padStart(3, '0') + '.json'; document.body.appendChild(a); a.click(); a.remove();
  return Object.keys(part).length;
};
JC.run = async function () {
  if (JC.running) return; JC.running = true; JC.error = null; JC.stop = false;
  try {
    for (const q of JC.queue) {
      if (JC.stop) break;
      if (q.release in JC.results) continue;
      JC.current = q.release;
      let tries = 0, ok = false;
      while (!ok && !JC.stop) {
        try { JC.results[q.release] = await JC.search(q); ok = true; }
        catch (e) {
          if (tries < 3) { tries++; await JC.sleep(60000); continue; }
          JC.error = q.release + ': ' + e.message; JC.errorAt = new Date().toISOString(); break;
        }
      }
      if (!ok) break;
      JC.done++;
      try { localStorage.setItem(key, JSON.stringify(JC.results)); } catch (e) {}
      await JC.sleep(20000 + Math.random() * 10000);
    }
  } finally { JC.running = false; JC.flush(); }
};
JC.flushTimer = setInterval(JC.flush, 120000);
if (window.JC_QUEUE) { JC.queue = window.JC_QUEUE; JC.loaded = JC.queue.length; JC.run(); }
})();
