// Mercari US crawl in a www.mercari.com tab, for mercari_photos.py. Set before loading: window.MC_PASS (the pass name),
// window.MC_QUEUE (the queries). It types each query into the search box and presses Enter (the page stays, so the
// script survives) and reads the listings shown. Batches downloaded as mercari-<pass>-batch-<n>.json.
(function () {
const pass = window.MC_PASS, key = 'MC.results.' + pass;
const MC = window.MC = {results: {}, queue: [], running: false, pass};
try { MC.results = JSON.parse(localStorage.getItem(key) || '{}'); } catch (e) {}
// left out: not a cartridge photo; lots kept, boxed/complete/manual/sealed kept but ordered last (the user, 2026-11-17)
MC.BAD = /\b(manual only|box only|empty box|empty|case only|repro|reproduction|custom|sticker|replacement|label only|poster|guide|strategy|insert only|cover art|shell only|artwork|fan ?made|fan-made|homebrew|bootleg)\b/i;
MC.CIB = /\b(cib|complete|boxed|box|in box|manual|manuals|sealed)\b/i;
MC.STOP = new Set(['the','a','an','of','and','in','to','gba','game','boy','color','advance','cartridge','vs','&','japan','pal']);
MC.words = s => s.toLowerCase().normalize('NFKD').replace(/[^a-z0-9 ]/g,' ').split(/\s+/).filter(w => w && !MC.STOP.has(w));
MC.sleep = ms => new Promise(r => setTimeout(r, ms));
MC.search = async function (q) {
  const box = document.querySelector('input[data-testid="SearchInput"]');
  if (!box) throw new Error('no search box');
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  box.focus(); setter.call(box, q.query); box.dispatchEvent(new Event('input', {bubbles: true}));
  box.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true}));
  const want_kw = q.query.trim();
  let count = null;
  for (let i = 0; i < 40; i++) {
    await MC.sleep(500);
    const kw = new URLSearchParams(location.search).get('keyword');
    if (kw !== want_kw || !document.title.includes(want_kw)) continue;
    const el = [...document.querySelectorAll('h1, h2, h3, p, span, div')].find(e => e.children.length === 0 && /^\(\d[\d,]*\+? results?\)$/.test(e.textContent.trim()));
    if (el) { count = parseInt(el.textContent.replace(/[^\d]/g, ''), 10); break; }
  }
  if (count === null) throw new Error('no result count (blocked or changed?)');
  await MC.sleep(1500);
  const sr = document.querySelector('[data-testid="SearchResults"]');
  const links = sr ? [...sr.querySelectorAll('a[data-testid="ProductThumbWrapper"]')].slice(0, count) : [];
  const want = MC.words(q.title), other = new RegExp(q.exclude, 'i');
  const req = q.require_region ? new RegExp(q.require_region, 'i') : null, notreg = q.exclude_region ? new RegExp(q.exclude_region, 'i') : null;
  const out = [], boxed = [];
  for (const a of links) {
    const id = ((a.getAttribute('href') || '').match(/\/item\/(m\d+)/) || [])[1]; if (!id) continue;
    const title = ((a.querySelector('[data-testid="ItemName"]') || {}).textContent || '').trim();
    if (MC.BAD.test(title) || other.test(title)) continue;
    if (req && !req.test(title)) continue;
    if (notreg && notreg.test(title)) continue;
    const have = new Set(MC.words(title));
    if (want.filter(w => have.has(w)).length / Math.max(1, want.length) < 0.75) continue;
    if (out.concat(boxed).some(o => o.id === id)) continue;
    (MC.CIB.test(title) ? boxed : out).push({id, title});
  }
  return out.concat(boxed).slice(0, 10);
};
MC.flushed = new Set(); MC.batch = 0;
MC.flush = function () {
  const part = {};
  for (const [r, v] of Object.entries(MC.results)) if (!MC.flushed.has(r)) { part[r] = v; MC.flushed.add(r); }
  if (!Object.keys(part).length) return 0;
  MC.batch++;
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(part)], {type: 'application/json'}));
  a.download = 'mercari-' + pass + '-batch-' + String(MC.batch).padStart(3, '0') + '.json'; document.body.appendChild(a); a.click(); a.remove();
  return Object.keys(part).length;
};
MC.run = async function () {
  if (MC.running) return; MC.running = true; MC.error = null; MC.stop = false; MC.retries = MC.retries || 0;
  try {
    for (const q of MC.queue) {
      if (MC.stop) break;
      if (q.release in MC.results) continue;
      MC.current = q.release;
      let tries = 0, ok = false;
      while (!ok && !MC.stop) {
        try { MC.results[q.release] = await MC.search(q); ok = true; }
        catch (e) {
          if (tries < 3) { tries++; MC.retries++; await MC.sleep(60000); continue; }
          MC.error = q.release + ': ' + e.message; MC.errorAt = new Date().toISOString(); break;
        }
      }
      if (!ok) break;
      try { localStorage.setItem(key, JSON.stringify(MC.results)); } catch (e) {}
      await MC.sleep(20000 + Math.random() * 10000);
    }
  } finally { MC.running = false; MC.flush(); }
};
MC.flushTimer = setInterval(MC.flush, 120000);
if (window.MC_QUEUE) { MC.queue = window.MC_QUEUE; MC.loaded = MC.queue.length; MC.run(); }
})();
