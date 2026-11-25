// Tradera title searches in a www.tradera.com tab, for tradera_photos.py ingest. Set before loading: window.TR_PASS,
// window.TR_QUEUE (tradera_photos.py queries). Per release, the search page for sale and sold (/search?q=...,
// &itemStatus=Sold) is fetched, its Next.js flight data (the strings of self.__next_f.push([1, "..."]), each decoded
// as JSON) joined, and its "items":[...] array read: at most 60 items each, the fields ingest uses. Filtering is
// done in ingest. One release every 8 to 12 s; batches downloaded as tradera-<pass>-batch-<n>.json every 2 minutes.
(function () {
const pass = window.TR_PASS, key = 'TR.results.' + pass;
const TR = window.TR = {pass, results: {}, queue: [], running: false, done: 0};
try { TR.results = JSON.parse(localStorage.getItem(key) || '{}'); } catch (e) {}
TR.sleep = ms => new Promise(r => setTimeout(r, ms));
TR.items = function (html) {
  const text = [...html.matchAll(/self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)/g)].map(m => JSON.parse(m[1])).join('');
  const i = text.indexOf('"items":[{"itemId"');  // the results (other "items" arrays on the page are menus, ads)
  if (i < 0) return text.includes('"items":[],"relatedItems"') ? [] : null;  // no results: only "related" listings
  let d = 0, j = i + 8;
  for (; j < text.length; j++) { const c = text[j]; if (c === '[') d++; else if (c === ']') { d--; if (!d) break; } }
  return JSON.parse(text.slice(i + 8, j + 1));
};
TR.page = async function (url) {
  const r = await fetch(url, {credentials: 'include'});
  if (!r.ok) { const e = new Error('HTTP ' + r.status); e.http = r.status; throw e; }
  const html = await r.text();
  if (/Client Challenge/.test(html)) { const e = new Error('challenge page'); e.http = 0; throw e; }
  const items = TR.items(html);
  if (items === null) { const e = new Error('no items in page'); e.http = 0; throw e; }
  return (items || []).slice(0, 60).map(v => ({itemId: v.itemId, categoryId: v.categoryId, shortDescription: v.shortDescription,
    itemUrl: v.itemUrl, imageUrlTemplate: v.imageUrlTemplate, imageWidth: v.imageWidth, imageHeight: v.imageHeight, isActive: v.isActive}));
};
TR.search = async function (q) {
  const base = '/search?q=' + encodeURIComponent(q.query);
  const active = await TR.page(base);
  await TR.sleep(3000);
  const sold = await TR.page(base + '&itemStatus=Sold');
  const seen = new Set(active.map(v => v.itemId));
  return active.concat(sold.filter(v => !seen.has(v.itemId)));
};
TR.flushed = new Set(); TR.batch = 0;
TR.flush = function () {
  const part = {};
  for (const [r, v] of Object.entries(TR.results)) if (!TR.flushed.has(r)) { part[r] = v; TR.flushed.add(r); }
  if (!Object.keys(part).length) return 0;
  TR.batch++;
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(part)], {type: 'application/json'}));
  a.download = 'tradera-' + pass + '-batch-' + String(TR.batch).padStart(3, '0') + '.json'; document.body.appendChild(a); a.click(); a.remove();
  return Object.keys(part).length;
};
TR.run = async function () {
  if (TR.running) return; TR.running = true; TR.error = null; TR.stop = false;
  try {
    for (const q of TR.queue) {
      if (TR.stop) break;
      if (q.release in TR.results) continue;
      TR.current = q.release;
      let tries = 0, ok = false;
      while (!ok && !TR.stop) {
        try { TR.results[q.release] = await TR.search(q); ok = true; }
        catch (e) {
          if (tries < 3) { tries++; await TR.sleep(e.http === undefined ? 60000 : 600000); continue; }
          TR.error = q.release + ': ' + e.message; TR.errorAt = new Date().toISOString(); break;
        }
      }
      if (!ok) break;
      TR.done++;
      try { localStorage.setItem(key, JSON.stringify(TR.results)); } catch (e) {}
      await TR.sleep(5000 + Math.random() * 4000);
    }
  } finally { TR.running = false; TR.flush(); }
};
TR.flushTimer = setInterval(TR.flush, 120000);
if (window.TR_QUEUE) { TR.queue = window.TR_QUEUE; TR.loaded = TR.queue.length; TR.run(); }
})();
