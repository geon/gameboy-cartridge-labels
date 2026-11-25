// Every photo of given listings, read from their pages in a jauce.com or tradera.com tab, for last_photos.py. Set
// before loading: window.LP_SITE ('jauce' or 'tradera'), window.LP_QUEUE ([{key, id}]: Yahoo auction ids or Tradera
// item ids). Results {key: [photo paths in the listing's order]} (Jauce: the path after auctions.c.yimg.jp/; Tradera:
// the path after img.tradera.net/images/), [] for a page without photos; one page every 4 to 6 s; batches downloaded as
// listing-photos-<site>-batch-<n>.json every 2 minutes.
(function () {
const site = window.LP_SITE, key = 'LP.results.' + site;
const LP = window.LP = {site, results: {}, queue: [], running: false, done: 0};
try { LP.results = JSON.parse(localStorage.getItem(key) || '{}'); } catch (e) {}
LP.sleep = ms => new Promise(r => setTimeout(r, ms));
LP.photos = {
  jauce: async function (id) {
    const r = await fetch('/auction/' + id, {credentials: 'include'});
    if (!r.ok) { const e = new Error('HTTP ' + r.status); e.http = r.status; throw e; }
    const h = await r.text();
    return [...new Set((h.match(/auctions\.c\.yimg\.jp\/images\.auctions\.yahoo\.co\.jp\/image\/[^"'?\s)\\]+/g) || []))]
      .map(u => u.split('auctions.c.yimg.jp/')[1]);
  },
  tradera: async function (id) {
    const r = await fetch('/item/0/' + id + '/x', {credentials: 'include'});
    if (!r.ok) { const e = new Error('HTTP ' + r.status); e.http = r.status; throw e; }
    const h = await r.text();
    const t = [...h.matchAll(/self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)/g)].map(m => JSON.parse(m[1])).join('');
    const m = t.indexOf('"itemMainImageTemplate"');
    if (m < 0) return [];
    const a = t.indexOf('"images":[', m);
    let d = 0, j = a + 9;
    for (; j < t.length; j++) { const c = t[j]; if (c === '[') d++; else if (c === ']') { d--; if (!d) break; } }
    return JSON.parse(t.slice(a + 9, j + 1)).map(x => (x.fullSize || x.normal || '').split('img.tradera.net/images/')[1]).filter(Boolean);
  },
};
LP.flushed = new Set(); LP.batch = 0;
LP.flush = function () {
  const part = {};
  for (const [r, v] of Object.entries(LP.results)) if (!LP.flushed.has(r)) { part[r] = v; LP.flushed.add(r); }
  if (!Object.keys(part).length) return 0;
  LP.batch++;
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(part)], {type: 'application/json'}));
  a.download = 'listing-photos-' + site + '-batch-' + String(LP.batch).padStart(3, '0') + '.json'; document.body.appendChild(a); a.click(); a.remove();
  return Object.keys(part).length;
};
LP.run = async function () {
  if (LP.running) return; LP.running = true; LP.error = null; LP.stop = false;
  try {
    for (const q of LP.queue) {
      if (LP.stop) break;
      if (q.key in LP.results) continue;
      LP.current = q.key;
      let tries = 0, ok = false;
      while (!ok && !LP.stop) {
        try { LP.results[q.key] = await LP.photos[site](q.id); ok = true; }
        catch (e) {
          if (e.http === 404) { LP.results[q.key] = []; ok = true; break; }
          if (tries < 3) { tries++; await LP.sleep(60000); continue; }
          LP.error = q.key + ': ' + e.message; break;
        }
      }
      if (!ok) break;
      LP.done++;
      try { localStorage.setItem(key, JSON.stringify(LP.results)); } catch (e) {}
      await LP.sleep(4000 + Math.random() * 2000);
    }
  } finally { LP.running = false; LP.flush(); }
};
LP.flushTimer = setInterval(LP.flush, 120000);
if (window.LP_QUEUE) { LP.queue = window.LP_QUEUE; LP.loaded = LP.queue.length; LP.run(); }
})();
