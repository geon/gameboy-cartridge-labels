// eBay crawl in one eBay site's tab (any country, ebay.com too). Set before loading: window.EB_SITE (com, uk, fr, ...),
// window.EB_PASS (the pass name, as ingest's: wanted2-uk), window.EB_SLOT = [i, n, ms]: this tab is tab i of n sharing
// eBay's rate limit (shared across its country sites), searching at the start of slot i of each n × ms cycle (the
// user, 2026-11-23: one eBay search every ms in all). window.EB_QUEUE: the queries, when loaded with the script.
(function () {
const site = window.EB_SITE, pass = window.EB_PASS || 'wanted1-' + site, key = 'EB.results.' + pass;
const [slotI, slotN, slotMs] = window.EB_SLOT || [0, 1, 75000];
const EB = window.EB = {site, pass, results: {}, queue: [], running: false, blocks: [], done: 0};
try { EB.results = JSON.parse(localStorage.getItem(key) || '{}'); } catch (e) {}
// left out: not a cartridge photo (box/manual only, guides, repros); lots and other regions kept (the user, 2026-11-17)
EB.BAD = /\b(manual only|box only|empty box|empty|repro|reproduction|custom|sticker|replacement|label only|poster|guide|strategy|insert only|cover art|shell only|artwork|fan ?made|fan-made|homebrew|bootleg|case only|nur anleitung|nur ovp|leerverpackung|lösungsbuch|berater|spieleberater|notice seule|boîte seule|bo[iî]te vide|solo manuale|solo scatola|scatola vuota|solo caja|caja vacía|alleen doos|alleen handleiding|lege doos|tylko pudełko|tylko instrukcja|reprodukcja)\b/i;
// boxed or with manual: kept, ordered last
EB.CIB = /\b(cib|complete|complet|complète|completo|compleet|komplett|kompletna|ovp|boxed|box|in box|w\/ ?box|manual|manuals|anleitung|sealed|versiegelt|boîte|boite|notice|scatola|manuale|caja|doos|handleiding|pudełko|instrukcja)\b/i;
EB.STOP = new Set(['the','a','an','of','and','in','to','gba','game','boy','color','advance','cartridge','vs','&','japan','pal']);
EB.words = s => s.toLowerCase().normalize('NFKD').replace(/[^a-z0-9 ]/g, ' ').split(/\s+/).filter(w => w && !EB.STOP.has(w));
EB.sleep = ms => new Promise(r => setTimeout(r, ms));
EB.search = async function (q) {
  const r = await fetch(location.origin + '/sch/i.html?_nkw=' + encodeURIComponent(q.query) + '&_sacat=139973&_ipg=60', {credentials: 'include'});
  if (!r.ok) { const e = new Error('HTTP ' + r.status); e.http = r.status; throw e; }
  const html = await r.text();
  const doc = new DOMParser().parseFromString(html, 'text/html');
  if (!/srp-results|srp-river/.test(html)) { const e = new Error('no result list (blocked?)'); e.http = 0; throw e; }
  const items = doc.querySelectorAll('li.s-item, li.s-card');
  const want = EB.words(q.title), other = new RegExp(q.exclude, 'i');
  const plain = [], boxed = [];
  for (const li of items) {
    const a = li.querySelector('a[href*="/itm/"]'); if (!a) continue;
    const item = (a.getAttribute('href').match(/\/itm\/(\d+)/) || [])[1]; if (!item || item === '123456') continue;
    const title = ((li.querySelector('.s-item__title, .s-card__title') || {}).textContent || '').trim();
    const img = [...li.querySelectorAll('img')].map(i => i.getAttribute('src') + ' ' + (i.getAttribute('data-src') || '') + ' ' + (i.getAttribute('srcset') || '')).join(' ');
    const image = (img.match(/i\.ebayimg\.com\/images\/g\/([A-Za-z0-9~_-]+)\//) || [])[1];
    if (!image || EB.BAD.test(title) || other.test(title)) continue;
    const have = new Set(EB.words(title));
    if (want.filter(w => have.has(w)).length / Math.max(1, want.length) < 0.75) continue;
    if (plain.concat(boxed).some(o => o.image === image || o.item === item)) continue;
    (EB.CIB.test(title) ? boxed : plain).push({item, title, image});
  }
  return plain.concat(boxed).slice(0, 10);
};
EB.flushed = new Set(); EB.batch = 0;
EB.flush = function () {
  const part = {};
  for (const [r, v] of Object.entries(EB.results)) if (!EB.flushed.has(r)) { part[r] = v; EB.flushed.add(r); }
  if (!Object.keys(part).length) return 0;
  EB.batch++;
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(part)], {type: 'application/json'}));
  a.download = 'ebay-' + site + '-batch-' + pass + '-' + String(EB.batch).padStart(3, '0') + '.json'; document.body.appendChild(a); a.click(); a.remove();
  return Object.keys(part).length;
};
EB.slot = function () {  // waits for this tab's next slot
  const cycle = slotN * slotMs, now = Date.now();
  let t = Math.floor(now / cycle) * cycle + slotI * slotMs;
  if (t < now) t += cycle;
  return EB.sleep(t - now);
};
// removes releases from the unsearched part of the queue (those with enough photos already)
EB.prune = list => { const s = new Set(list), before = EB.queue.length; EB.queue.splice(0, EB.queue.length, ...EB.queue.filter(q => q.release in EB.results || !s.has(q.release))); return site + ' removed ' + (before - EB.queue.length) + ', left to search ' + EB.queue.filter(q => !(q.release in EB.results)).length; };
EB.run = async function () {
  if (EB.running) return; EB.running = true; EB.error = null; EB.stop = false;
  try {
    for (const q of EB.queue) {
      if (EB.stop) break;
      if (q.release in EB.results) continue;
      EB.current = q.release;
      let ok = false, netTries = 0, blockStart = null;
      while (!ok && !EB.stop) {
        await EB.slot();
        try { EB.results[q.release] = await EB.search(q); ok = true; }
        catch (e) {
          if (e.http === undefined && netTries < 3) { netTries++; await EB.sleep(60000); continue; }
          if (e.http !== undefined) {  // blocked: wait half an hour, for up to 4 hours
            EB.blocks.push({at: new Date().toISOString(), done: EB.done, error: e.message});
            blockStart = blockStart || Date.now();
            if (Date.now() - blockStart < 4 * 3600e3) { EB.blocked = true; await EB.sleep(1800e3); continue; }
          }
          EB.error = q.release + ': ' + e.message; EB.errorAt = new Date().toISOString(); break;
        }
      }
      EB.blocked = false;
      if (!ok) break;
      EB.done++;
      try { localStorage.setItem(key, JSON.stringify(EB.results)); } catch (e) {}
    }
  } finally { EB.running = false; EB.flush(); }
};
EB.flushTimer = setInterval(EB.flush, 300000);
const inp = document.createElement('input'); inp.type = 'file'; inp.setAttribute('aria-label', 'EB queries file');
inp.style.cssText = 'position:fixed;top:30px;left:0;z-index:99999';
inp.onchange = async () => { EB.queue = JSON.parse(await inp.files[0].text()); EB.loaded = EB.queue.length; EB.run(); };
document.body.prepend(inp);
if (window.EB_QUEUE) { EB.queue = window.EB_QUEUE; EB.loaded = EB.queue.length; EB.run(); }
})();
