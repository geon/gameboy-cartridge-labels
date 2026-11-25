# Crawling eBay

Cartridge photos from eBay searches, for releases no label photo has. Learned on 2026-11-09 and 10, with the USA releases (676 of 715 searched, 3154 photos downloaded, 2945 kept after the user's look).

## What works and what doesn't

- **Search pages need a browser.** curl on `https://www.ebay.com/sch/i.html?...` gets HTTP 403, even with a browser User-Agent. They are fetched from inside an ebay.com tab instead, through the Claude in Chrome extension.
- **Images don't.** curl on `https://i.ebayimg.com/images/g/<image id>/s-l1600.jpg` works: the same bytes as saving the image from Chrome. No browser needed for them.
- **Never open tabs with AppleScript.** Each new tab brings Chrome to the front and takes macOS's focus from whatever the user is doing. AppleScript's `save` of an image tab does work (the file gets a `.html` name but is the JPEG), but it isn't needed.
- **AppleScript can't run JavaScript in Chrome** unless View > Developer > Allow JavaScript from Apple Events is turned on (it's off).
- **Searching inside one tab disturbs nothing.** The page stays on ebay.com; each search is a `fetch()` of the search URL (with the user's cookies), parsed with `DOMParser`. No navigation, no new tabs, no focus.

## Sizes

- `s-l1600` is the largest size eBay serves: the long side is at most 1600 px. Seen: 1600x1600, 1534x1462, 1254x1254, 1200x1600.
- Asking for `s-l1600` of a smaller original gives the original: one was a 300x300 logo. Photos under 1000 px on the long side are dropped.
- `.jpg` and `.webp` both work at the end of the URL; `.jpg` gives JPEG.

## Search results

- One search per release: `<title> <GBA | Game Boy Color | Game Boy> cartridge`, category Video Games (`_sacat=139973`), 60 per page (`_ipg=60`). The database title is turned around for the query ("Lord of the Rings, The - ..." -> "The Lord of the Rings ...", " - " -> " ").
- Results are `li.s-item` or `li.s-card`. The first ones are "Shop on eBay" placeholders with item number 123456: skip them.
- Each result has the item number (`/itm/<number>`), the title (minus "Opens in a new window or tab" and a leading "NEW LISTING") and an image id from `i.ebayimg.com/images/g/<id>/`, in `src`, `data-src` or `srcset` (lazy loading).
- **A result's image is the listing's first photo**, normally the front of the cartridge. So the listing pages need not be opened: one page load per release.
- Below the matches comes "Results matching fewer words": unrelated games. The title-word filter drops them.

## Filters on listing titles

- **Not a loose cartridge:** box, boxed, CIB, complete, manual, lot, bundle, case, sealed, repro, reproduction, custom, sticker, replacement, label only, poster, guide, strategy, insert, cover art, empty, shell only, artwork.
- **Another system:** for GBA releases GBC, Game Boy Color, DS, 3DS, PSP, GameCube, Sega; for Game Boy and Game Boy Color releases GBA, Advance, DS, 3DS, PSP, N64, Sega.
- **Another region** (applied when downloading): Japan, Japanese, JPN, JP, NTSC-J, PAL, EUR, Europe, UK, German, French, Spanish, Italian, import, Chinese, Korean, or a serial like `AGB-P-BJBJ`. Japanese cartridges do get listed on ebay.com.
- **The game itself:** at least ¾ of the title's words (minus "the", "of", "GBA", "game", "boy" and the like) in the listing title.
- At most 10 candidates per search; the first 5 that download at 1000 px or more are kept.
- What the filters miss: dirty cartridges, logos and stock pictures, some boxes. The user went through the photos and deleted 209 of 3154.

## Getting data in and out of the page

- The page can't write files, and the extension returns data only to the conversation. Passing hundreds of results through the conversation costs tokens and means retyping ids.
- **In:** the query list goes in as a file: a file input is added to the page, and the extension's `file_upload` puts the local JSON file in it (147 KB for 715 queries).
- **Out:** a browser download is the page's only way to disk. The page saves the results found since the last time every 2 minutes as `~/Downloads/ebay-batch-usa-<n>.json`; a background shell loop moves each one away and downloads its images with curl. Chrome asks once whether ebay.com may download several files.
- Saving everything only at the end meant nothing showed up for two hours: don't.
- The results are also in the page's `localStorage` (`EB.results`), and it keeps its queue: it can resume after an error as long as the tab isn't closed or reloaded.

## Pace and blocking

- One search every 9 to 13 s (about 11 s): 676 searches in about 2 hours, then HTTP 403 on every search. The loop stops at the first error.
- Not known yet: how long the block lasts, and whether a slower pace (one every 30 s) avoids it.
- `curl` on the images (one a second, about 3000) was never blocked.

## The release list

- generated/read-serials/missing.json holds the database's record ids (`agb-0003`, `AGB-A22J`), not serials: that's why it looks mixed. The cartridge serials are in each record's `cartridgeSerials` in gb-game-list's releases.json; 716 missing releases have a `-USA` one. About 2300 have no cartridge serial; their region is the last letter of the game id (`AGB-A22J` is Japan).
- Searching ebay.com for European or Japanese releases mostly finds US cartridges. Planned: ebay.co.uk and ebay.de for Europe, Japanese titles with "Japan" for Japan. Not tried.

## Files

The downloader:

src/ebay_photos.py

It makes the query list (`queries USA`) and takes in the page's batches (`ingest <batch> <queries>`). Its records, one per downloaded photo, also those deleted by hand afterwards, so they're never downloaded again:

ebay-photos/sources.json

Every release searched, with its counts, so a run can resume:

ebay-photos/searches.json

New photos go to the drop-off folder with a listing.json (page_url, image_url, title_on_page, searched_release, searched_serial, query, fetched), for make add-photos, which files them into photos/ as `<sha1>.jpg` and their origin into photo-sources.json:

save-new-images-here/ebay-search/

The first 2945 photos are still in ebay-photos/, with their listing.json there.

## The page's script

Run in an ebay.com tab with the extension's javascript_tool; then a file input appears top left, and `file_upload` of the query file starts the searches. `EB.stop = true` stops them; `EB.run()` resumes.

```js
window.EB = window.EB || {results: {}, queue: [], running: false};
EB.BAD = /\b(box|boxed|cib|complete|manual|manuals|lot|bundle|case|sealed|repro|reproduction|custom|sticker|replacement|label only|poster|guide|strategy|insert|cover art|empty|shell only|artwork)\b/i;
EB.STOP = new Set(['the','a','an','of','and','in','to','gba','game','boy','color','advance','cartridge','vs','&']);
EB.words = s => s.toLowerCase().normalize('NFKD').replace(/[^a-z0-9 ]/g,' ').split(/\s+/).filter(w => w && !EB.STOP.has(w));
EB.search = async function (q) {
  const url = 'https://www.ebay.com/sch/i.html?_nkw=' + encodeURIComponent(q.query) + '&_sacat=139973&_ipg=60';
  const r = await fetch(url, {credentials: 'include'});
  if (!r.ok) throw new Error('HTTP ' + r.status);
  const html = await r.text();
  const doc = new DOMParser().parseFromString(html, 'text/html');
  const items = doc.querySelectorAll('li.s-item, li.s-card');
  if (!items.length && !/No exact matches|0 results/i.test(html)) throw new Error('no result list (blocked?)');
  const want = EB.words(q.title), other = new RegExp(q.exclude, 'i');
  const out = [];
  for (const li of items) {
    const a = li.querySelector('a[href*="/itm/"]'); if (!a) continue;
    const item = (a.getAttribute('href').match(/\/itm\/(\d+)/) || [])[1]; if (!item || item === '123456') continue;
    const title = ((li.querySelector('.s-item__title, .s-card__title') || {}).textContent || '').replace(/Opens in a new window or tab/, '').replace(/^NEW LISTING/, '').trim();
    const img = [...li.querySelectorAll('img')].map(i => i.getAttribute('src') + ' ' + (i.getAttribute('data-src') || '') + ' ' + (i.getAttribute('srcset') || '')).join(' ');
    const image = (img.match(/i\.ebayimg\.com\/images\/g\/([A-Za-z0-9~_-]+)\//) || [])[1];
    if (!image || EB.BAD.test(title) || other.test(title)) continue;
    const have = new Set(EB.words(title));
    if (want.filter(w => have.has(w)).length / Math.max(1, want.length) < 0.75) continue;
    if (out.some(o => o.image === image)) continue;
    out.push({item, title, image});
    if (out.length >= 10) break;
  }
  return out;
};
EB.flushed = EB.flushed || new Set(); EB.batch = EB.batch || 0;
EB.flush = function () {
  const part = {};
  for (const [r, v] of Object.entries(EB.results)) if (!EB.flushed.has(r)) { part[r] = v; EB.flushed.add(r); }
  if (!Object.keys(part).length) return 0;
  EB.batch++;
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(part)], {type: 'application/json'}));
  a.download = 'ebay-batch-usa-' + String(EB.batch).padStart(3, '0') + '.json'; document.body.appendChild(a); a.click(); a.remove();
  return Object.keys(part).length;
};
EB.run = async function () {
  if (EB.running) return; EB.running = true; EB.error = null; EB.stop = false;
  try {
    for (const q of EB.queue) {
      if (EB.stop) break;
      if (q.release in EB.results) continue;
      EB.current = q.release;
      try { EB.results[q.release] = await EB.search(q); }
      catch (e) { EB.error = q.release + ': ' + e.message; break; }
      try { localStorage.setItem('EB.results', JSON.stringify(EB.results)); } catch (e) {}
      await new Promise(r => setTimeout(r, 9000 + Math.random() * 4000));
    }
  } finally { EB.running = false; EB.flush(); }
};
if (EB.flushTimer) clearInterval(EB.flushTimer);
EB.flushTimer = setInterval(EB.flush, 120000);
const inp = document.createElement('input'); inp.type = 'file'; inp.setAttribute('aria-label', 'EB queries file');
inp.style.cssText = 'position:fixed;top:0;left:0;z-index:99999';
inp.onchange = async () => { EB.queue = JSON.parse(await inp.files[0].text()); EB.run(); };
document.body.prepend(inp);
```

The shell loop that takes in the batches (S: a folder for the query file and the batches taken in):

```bash
cd /Users/vicwid/code/geon/gameboy-labels-detection
while true; do
  for f in $(find ~/Downloads -maxdepth 1 -name 'ebay-batch-usa-*.json' | sort); do
    mv "$f" "$S/batches/" && python3 src/ebay_photos.py ingest "$S/batches/$(basename "$f")" "$S/queries.json"
  done
  sleep 30
done
```

## Second pass (2026-11-10)

- The database entries with at least one but fewer than 3 high-resolution label photos (20 px/mm or more at the label, straighten's full resolution; poor fits not counted): 1555 (1351 with one, 204 with two), searched in that order, those with one first. eBay photos reach 20 px/mm about as often as the others (28 % against 23 %).
- All regions on ebay.com (imports are listed there): the region from the cartridge serial's suffix, else the game id's last letter; "Japan" or "PAL" added to the query for Japanese and European releases. No listing left out for its region or for naming another Game Boy system: all cartridge photos are welcome (the user), and read-serials reads each photo's own serial. Only other systems are left out (DS, 3DS, PSP, GameCube, N64, Sega), with the title filters above. (The first 7 searches ran with region filters, dropped then: a PAL filter had found nothing in a trial.)
- Titles in Japanese script (104): searched by a romanized title, ebay-romanized-titles.json (written by Claude), last in the queue; full-width letters made plain (NFKC) for the rest.
- A named pass (`queries <region> <releases.json> pass2`, `ingest ... pass2`): a release searched before is searched again (the first pass kept 5 of up to 10 candidates), recorded under its "passes".
- The records are in save-new-images-here/ now (searches.json, sources.json): run with `EBAY_OUT=save-new-images-here`.
- One search every 18 to 26 s. Batches: `~/Downloads/ebay-batch-pass2-<n>.json`. A network failure ("Failed to fetch", once after 14 searches) is retried after a minute, up to 3 times; an HTTP error or a page without results still stops the run.
- Blocked (HTTP 403) on 2026-11-11 after 344 of the pass's searches at one every 18 to 26 s (207 since the tab was restarted); lifted by the time it was noticed (a few hours at most). Resumed at one every 35 to 50 s; blocked again at 08:19 UTC after 69 more searches (2.5 hours), lifted 3 hours later: eBay seems to limit searches over a longer period, not their pace. Now on a block the page waits half an hour and tries again, for up to 4 hours, and records each block (`EB.blocks`: when, after how many searches).
- Blocks since (2026-11-11, UTC, searches done at each): 12:28 (490), 13:28 (531), 14:13 (551), 14:45 (554), 15:19 (559), 15:52 (563), 16:32 (576), 17:04 (580), 17:35 (581), 18:06 (582), 18:38 (585): after the first, the half-hour waits let through 1 to 41 searches each, fewer and fewer. A block isn't a fixed pause: once blocked, eBay lets a trickle through for hours.
- What the user deleted (57 of the first 344 photos): 14 were other systems' games of the same title (PlayStation 2, Xbox: Defender, MLB Slugfest, All-Star Baseball), so PlayStation, PS1-5, Sony, Xbox, Wii, Dreamcast, disc and the like are left out now. 7 were one seller's, titles ending "Nintendo <4 digits> gba" (games photographed in their box, likely), 1 of theirs kept: not filtered (the user: nothing to go on). Booklet, graded, set and "new" caught too few to filter. The other 36 had ordinary titles: only the photo shows a box.
- Trial: a PAL search ("Castlevania Aria of Sorrow GBA PAL cartridge") found no listing naming PAL among 60 results; Japanese ones found 10 each.

## Yahoo! Auctions Japan through Jauce (2026-11-10)

- www.jauce.com, a proxy shop for Yahoo! Auctions: a search is a form post to `/directory_list.php` (`find` = the words); the results are in the HTML (like eBay's), each an `li` with the auction id (`/auction/v1250734539`), the title (Japanese, in the image's alt) and the first photo (`auctions.c.yimg.jp/images.auctions.yahoo.co.jp/image/.../i-img1200x900-....jpg`: its size in its name).
- Yahoo refuses curl (HTTP 403), on its image server and its thumbnail server (auc-pctr.c.yimg.jp) alike; through Jauce's image proxy (`https://www.jauce.com/read_yafile/https://auc-pctr.c.yimg.jp/i/<path>`) curl gets the full size.
- Searched by the database's Japanese-script title (gb-game-list's titles: 1753 of 1888 Japanese releases have one; readings in brackets left out, NFKC) and the system's Japanese name (ゲームボーイ, ゲームボーイカラー, ゲームボーイアドバンス). A listing's title must hold ¾ of the title's parts.
- Left out: lots and sets (まとめ, セット, N本), boxes and manuals (外箱, 空箱, 箱 and 説明書 but not 箱なし or 説明書なし), guides, cases, consoles (本体), accessories, repros; other systems (DS, PSP, PS, SFC, スーパーファミコン, ファミコン but not ファミコンミニ, the GBA's Famicom Mini series, and the like). Photos under 1000 px skipped by their name, before downloading.
- A search with no results comes back as HTTP 404 with "No results found." (first seen on エアフォースデルタII): zero results, not an error.
- One search every 20 to 30 s; batches `~/Downloads/jauce-batch-<n>.json`, taken in by `python3 src/jauce_photos.py ingest`. Records: save-new-images-here/jauce-sources.json, jauce-searches.json; photos: save-new-images-here/jauce-search/ (page_url: the Yahoo listing).
- First run: the 567 Japanese releases of the second pass's list with a Japanese title, all searched (2026-11-11): 1608 photos, never blocked.
- Second run (2026-11-11), done the same day (1174 searches, 2266 photos, never blocked): the worst Japanese prints first (the user: raising the worst existing prints' quality is the top priority): the 21 Japanese releases with only poor fits (no restored image), then the 958 with good label photos but none at 20 px/mm, the lowest resolution first, then the 289 with no label photo; 1174 of them with a Japanese title. Still 5 photos per release (the user: if not enough, the next pass shows it). Batches `jauce2-batch-<n>.json`.

- After two runs (2026-11-11): of 1741 searches, 449 kept 5 photos, 817 kept 0 or 1 (373 had no candidates): the long query (the whole title, subtitles and taglines too, and ゲームボーイアドバンス) needs every word in a listing's title, and sellers write the main title and GBA. Third run, pass "short1": the 462 Japanese releases with a single label photo (no median possible, so damage stays), those Jauce found 0-1 photos for first (396), then those never searched (66, by their romanized title); the short query: the title's first word (split at spaces and "/"; Latin words until 6 letters, romanized titles at least two words) and the numbers in the rest, with GBA, GBC or GB (`queries releases.json short1 short`). Its title check needs those words only: more listings, and more of a series' other games, which read-serials files under their own release. "ソフト無し" (no cartridge) listings left out too.

## Mercari (www.mercari.com, tried 2026-11-10)

- Photos: `u-mercari-images.mercdn.net/photos/<item>_1.jpg`, curl works, 1600 x 1200.
- Searches: the search page's HTML has no results; the page gets them from Mercari's own GraphQL API (`/v1/api`, undocumented). Not used: either a navigation per search driven from the conversation, or calling that API. Waiting on the user.

## Open

- 39 USA releases not searched (the block). Resume slower, after a pause.
- Other regions: not started.
- Listing pages (all photos of a listing, not only the first) weren't needed; the listing's own gallery is its `s-l140` thumbnails, and the page also holds other listings' images.

## 2026-11-11: Jauce run 4 (short2) and eBay pass 3, after deleting the photos under 10 px/mm

The queues were made from the pipeline's outputs as they were before that day's add-photos. Releases with photos waiting from add-photos are left out. A label photo counts as usable when its fit isn't poor.

- Jauce, pass "short2", 504 short queries: Japanese releases with fewer than 3 usable label photos at 10 px/mm (Yahoo's photos are at most 1200 px, so 20 px/mm is out of reach there). Not those already searched in short1. Order: never searched on Jauce (31, by romanized title), then 0 usable (133), then 1–2 usable (340); within each, releases with no photo at all first. A query now carries its own pass name ("pass"), so one queue can mix passes.
- eBay, pass 3, 2959 queries: other releases with fewer than 3 usable label photos at 20 px/mm, not searched in pass 2. Order: some photo but none usable at 20 px/mm, then 1–2 usable, then no photo at all.
- Both now keep only photos of at least 1200 px on the longest side (was 1000). At 1000 px most labels came out under 10 px/mm.

## 2026-11-12: Mercari

- Mercari Japan (jp.mercari.com): searches work in a tab (the site's own search box; Japanese titles), but its photos are at most 1080 px (`static.mercdn.net/item/detail/orig/…`, as its own listing pages show them), and `u-mercari-images` refuses them (HTTP 403). Under the 1200 px minimum: not used. ZenMarket's Mercari pages refuse script fetches (HTTP 403) and show machine-translated titles.
- Vinted: at most 800 px. Not used.
- Mercari US (www.mercari.com): src/mercari_photos.py. The tab script types each query into the search box and presses Enter (the page stays, so the script survives), then reads the listings. Photos from `u-mercari-images.mercdn.net/photos/<item>_1.jpg` without parameters: 1600 px, or 1080 px for some uploads (a larger width parameter only scales up). Sample, Pokemon Pinball: 9 of 10 at 1200 px or more.
- Run 1 (pass "us1"), 3400 queries: eBay pass 3's releases (2959), then the Japanese releases of Jauce run 4 by romanized title (441). eBay's queries without "cartridge"; eBay's filters in the tab.

## 2026-11-12: eBay pass 4 and Mercari US run 2 (us2), for the entries with 1–3 decent photos

- The goal (the user): at least one print with 5 decent label photos per database entry. Decent: a fit restore uses (precise, or an approximate cut in a print with 2 precise) at 10 px/mm or more. Counted per serial-id entry by its best print; the numbered entries (agb-1468 and the like) left out, their gameId unreliable (releases.json, see the database notes).
- From the run before the 1177 new photos (Konsolenkost, Jauce run 4, eBay pass 3's first batches): 3061 entries with 1–3 decent, 1151 of them Japanese. After those photos: 1753 with 1, 839 with 2, 474 with 3, 344 with 4, 470 with 5 or more, 1692 with no label photo.
- eBay, pass "pass4", 2152 queries: the 1–3 entries never searched on eBay (Japanese by romanized title with "Japan", as in pass 2), fewest decent first, never searched anywhere before the rest. It takes over pass 3's remaining queue for those entries; pass 3's tab was closed (two eBay crawls at once double the rate that got the first pass blocked). One search every 35–50 s, half-hour waits on a block (last night's script, pass 4's names). Batches `~/Downloads/ebay-batch-pass4-<n>.json`.
- Mercari US, pass "us2", 1894 queries: the non-Japanese 1–3 entries, the same order. Run 1 (us1) had stalled after 3 searches recorded (its tab kept searching, its batches no longer reached Downloads); closed. One search every 20–30 s. Batches `~/Downloads/mercari-us2-batch-<n>.json`.
- Both tabs now also leave out fan-made, homebrew and bootleg listings (Mercari's first test search found a fan-made Pokemon Pinball).
- Taken in by a shell loop (`ingest <batch> <queries> pass4`, `mercari_photos.py ingest <batch> <queries>`), as before.

### Mercari's tab script

Run in a www.mercari.com tab with javascript_tool; a file input appears top left, and `file_upload` of the query file starts it. `MC.stop = true` stops it, `MC.run()` resumes. It types each query into the search box and presses Enter: the page stays (only the URL changes), so the script survives. A search counts as loaded when the URL's keyword and the page title are the new query's and the "(N results)" count is shown; only the first N listings of the SearchResults block are results (a search with 0 results still shows 30 suggestions there).

```js
window.MC = {results: {}, queue: [], running: false, pass: 'us2'};
try { MC.results = JSON.parse(localStorage.getItem('MC.results.us2') || '{}'); } catch (e) {}
MC.BAD = /\b(box|boxed|cib|complete|manual|manuals|lot|bundle|case|sealed|repro|reproduction|custom|sticker|replacement|label only|poster|guide|strategy|insert|cover art|empty|shell only|artwork|fan ?made|fan-made|homebrew|bootleg)\b/i;
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
  const out = [];
  for (const a of links) {
    const id = ((a.getAttribute('href') || '').match(/\/item\/(m\d+)/) || [])[1]; if (!id) continue;
    const title = ((a.querySelector('[data-testid="ItemName"]') || {}).textContent || '').trim();
    if (MC.BAD.test(title) || other.test(title)) continue;
    if (req && !req.test(title)) continue;
    if (notreg && notreg.test(title)) continue;
    const have = new Set(MC.words(title));
    if (want.filter(w => have.has(w)).length / Math.max(1, want.length) < 0.75) continue;
    if (out.some(o => o.id === id)) continue;
    out.push({id, title});
    if (out.length >= 10) break;
  }
  return out;
};
MC.flushed = new Set(); MC.batch = 0;
MC.flush = function () {
  const part = {};
  for (const [r, v] of Object.entries(MC.results)) if (!MC.flushed.has(r)) { part[r] = v; MC.flushed.add(r); }
  if (!Object.keys(part).length) return 0;
  MC.batch++;
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(part)], {type: 'application/json'}));
  a.download = 'mercari-us2-batch-' + String(MC.batch).padStart(3, '0') + '.json'; document.body.appendChild(a); a.click(); a.remove();
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
      try { localStorage.setItem('MC.results.us2', JSON.stringify(MC.results)); } catch (e) {}
      await MC.sleep(20000 + Math.random() * 10000);
    }
  } finally { MC.running = false; MC.flush(); }
};
MC.flushTimer = setInterval(MC.flush, 120000);
const inp = document.createElement('input'); inp.type = 'file'; inp.setAttribute('aria-label', 'MC queries file');
inp.style.cssText = 'position:fixed;top:0;left:0;z-index:99999';
inp.onchange = async () => { MC.queue = JSON.parse(await inp.files[0].text()); MC.loaded = MC.queue.length; MC.run(); };
document.body.prepend(inp);
```

## 2026-11-12: the Konsolenkost photos

- 549 photos (labels cut out and pasted on two template cartridge photos): 551 label photos found, 508 solved: 410 precise, 93 approximate cuts, 5 poor fits. 182 joined families with photos of other sources, 316 alone, 10 in families of Konsolenkost photos only (the shared template linked no different games).
- Their pixel alignment: the family correction 0.34 mm at the median, 0.70 at 90 % (others 0.22, 0.48); the fine correction 0.08 and 0.22 (others 0.06, 0.14): the pasted labels' scale a little off, well within the 2 mm limit.
- Resolution: 11.1 px/mm at the median (the template's), 14.2 at 90 %. Their fine detail at 10–15 px/mm matches other sources' at the same px/mm (0.100 against 0.103, Laplacian over contrast): the measured px/mm isn't overstated by upscaled labels.

## 2026-11-12: downloads wait in downloaded-photos/

- The downloaders (ebay_photos, mercari_photos, jauce_photos) save photos to downloaded-photos/<site>-search/ (with listing.json), no longer to save-new-images-here/: a download running meanwhile landed in an add-photos run (the user: move them when ready to add them). `make move-downloads` moves the photos whose listing entry is written, with their entries, to save-new-images-here/<site>-search/; the downloaders and the move take turns on each folder's listing.json (a lock file).
- Their records moved there too, the default for all three: downloaded-photos/sources.json, searches.json (eBay), mercari-sources.json, mercari-searches.json, jauce-sources.json, jauce-searches.json. No `EBAY_OUT` needed any more.
- downloaded-photos/ is not in git, as save-new-images-here/.

## 2026-11-13: pass "bad1", for the prints marked Bad

- The goal (the user): photos for the prints marked Bad with few high-quality source photos, where a new photo has the best chance of improving the print; DMG first, then CGB, then AGB, with some fuzz.
- The prints: each print's latest mark in print-marks.json (marks of 2026-11-12, by an old print key, taken to the current print holding most of their label photos), Bad, not frozen: 340 (130 DMG, 64 CGB, 146 AGB), from the outputs before the 2026-11-13 make all. High quality: a precise fit (not poor, not an approximate cut) at 20 px/mm or more (restore's px/mm). 140 have none, 129 one, 55 two.
- Order, per release (a release's best-placed print): the print's label photos at 20 px/mm, plus 0 for DMG, 0.7 for CGB, 1.4 for AGB, plus a random 0 to 1 (seeded), plus its best px/mm / 100. 331 releases (8 prints had no release, 1 a release outside the database); the first 50 are 46 DMG and 4 CGB, the first 200 are 108 DMG, 42 CGB, 50 AGB.
- eBay, 327 queries (4 releases have no Latin word to search by): downloaded-photos/queries-ebay-bad1.json, all regions as pass 2 ("Japan" for the 161 Japanese, "PAL" for the 50 European). Batches `~/Downloads/ebay-batch-bad1-<n>.json`, taken in by `ingest <batch> <queries> bad1`.
- Mercari US, 166 queries, the non-Japanese ones, the same order: downloaded-photos/queries-mercari-bad1.json. Batches `~/Downloads/mercari-bad1-batch-<n>.json`.
- Jauce, 13 queries (the user): only the Japanese releases never searched there (152 of the 165 were, in short1 and short2, days before: a repeat finds mostly the same listings). Yahoo's photos are at most 1200 px, about 10 px/mm at the label, so they add photos but not the fine detail. 11 of them are DMG releases whose id ends in A (DMG-P9A), which `jauce_photos.py queries` skips (it takes ids ending in J): their queries were made by hand, short, by the katakana title written by Claude (Yahoo sellers write those, not the English title). downloaded-photos/queries-jauce-bad1.json; batches `~/Downloads/jauce-bad1-batch-<n>.json`.
- Outcome, 2026-11-14: Mercari finished all 166 queries, 529 photos kept. Jauce finished all 13, about 47 kept (none for Populous Gaiden, Trip World, Bubble Bobble Junior). eBay was stopped at 182 of 327 queries, 662 photos kept: from about 19:00 local (after query 157, roughly 90 minutes and 157 searches at about one a minute) eBay blocked the tab again and again; each 30-minute wait let one search through before the next block. The other 145 queries are still to do (`queries` skips the 182 recorded as searched in pass bad1), resumed on another day with a pause between searches.

## 2026-11-17: one seller's store (sumomo-syoukai, ebay.co.uk)

- A store's search (`_ssn=<seller>&_nkw=gameboy`) on ebay.co.uk: curl gets HTTP 403 there too; from inside the tab, `fetch()` of the same URL with `_ipg=240&_pgn=<n>` works: 467 listings in 2 pages (a third page repeats the second), each with an image id. Not blocked.
- This seller: Japanese cartridges, the serial in most titles (DMG-PMA, AGB-ARZJ-JPN). 64 listings left out by title: manuals (most), Famicom games, cartridge cases, DS Lite connector covers, guide books. None complete in box. 28 had been downloaded by an earlier search.
- `python3 src/ebay_photos.py store <listings.json> <store name>`: the first photo of each listing, to downloaded-photos/ebay-store/ (listing.json there, `store` in each entry); records in downloaded-photos/sources.json with `store` instead of `release`, too-small photos recorded with `too_small`. The listings: downloaded-photos/ebay-store-sumomo-syoukai.json.

## 2026-11-18: two German stores (ebay.de)

- The user picked them from search results: retrospielewelt 80er 90er 2000er (https://www.ebay.de/str/retrospielewelt80er90er2000er, seller `retrospielewelt`) and chronogamesretro (seller `chrono-games`). The seller id for `_ssn` is in the store page's HTML (`_ssn=` links, `"username"`), not the store's URL name.
- Searched from an ebay.de tab with `_ssn=<seller>&_nkw=gameboy` and `_nkw=game boy` (same results both ways), `_ipg=240`: 35 and 23 listings, one page each. Not blocked.
- The extension returns at most about 1000 characters per call: listings come out as a browser download (Chrome asks once to allow several downloads).
- Left out by hand (NOT_CARTRIDGE doesn't catch them): other systems' games (N64, SNES, NES, Mega Drive), a games guide, two consoles without games. A console bundle with 2 games kept (a lot).
- Kept: retrospielewelt 23 of 28 (5 too small), chronogamesretro 19 of 20 (1 too small). Listings: downloaded-photos/ebay-store-retrospielewelt.json, downloaded-photos/ebay-store-chrono-games.json.

## 2026-11-22: pass "wanted1", the wanted list (eBay and Jauce)

- The releases of generated/publish/wanted.json (the prints a photo or two short of an image), in its rank order: 1564 releases of 1734 prints, 757 Japanese.
- eBay: 1553 queries (`queries ALL <releases> wanted1`; 834 Japanese with "Japan", 423 European with "PAL"); one search every 35–50 s, half-hour waits on a block for up to 4 hours. Batches `~/Downloads/ebay-batch-wanted1-<n>.json`.
- Jauce: 757 short queries (`queries <releases> wanted1 short`), Japanese releases searched before included (Yahoo's auctions last about a week; auctions downloaded before are skipped by ingest). One search every 20–30 s. Batches `~/Downloads/jauce-wanted1-batch-<n>.json`.
- Lots and other-region listings no longer left out (the user, 2026-11-17); boxed, complete, manual and sealed listings (箱, 説明書, 未開封) put last instead of left out. Still left out: box or manual only, empty, repros, custom, stickers, guides, fan-made, consoles and accessories, other systems.
- Jauce changed: the form post to /directory_list.php now gets a "Loading..." page (a script sets a cookie and reloads). A search typed in the tab's own search box passes it and lands on `/search/<words joined by +>`; after that, a `fetch()` of `/search/<words>` from the tab gets the results page (404 with "No results found." when there are none, as before).
- Special shells left out (the user: not cartridges like Pokemon Pinball with the rumble): the releases whose code is in the main checkout's special-shells.tsv (rumble, tilt, infrared, solar and the like): 16 of eBay's queries, 8 of Jauce's, none searched yet. Left: eBay 1537, Jauce 749.
- Mercari US, pass "wanted1": the wanted list's releases without a Japanese id (as us2 and bad1), special shells left out: 789 queries. One search every 20–30 s; batches `~/Downloads/mercari-wanted1-batch-<n>.json`. The same filter change (lots kept, boxed last).
- ebay.de, pass "wanted1-de" (the user): the same 1537 releases and order as ebay.com's, queries without "cartridge" (German sellers write "Modul"), in an ebay.de tab at the same pace, alongside the ebay.com tab (whether eBay counts both domains together for its blocks is not known). German box/manual words (OVP, Anleitung, komplett) put last, guides (Berater, Lösungsbuch) and box/manual only left out. Batches `~/Downloads/ebay-de-batch-wanted1-<n>.json`, `ingest <batch> <queries> wanted1-de`.

## 2026-11-22: Blocket (www.blocket.se)

- The user's search: "gameboy" in Spel (https://www.blocket.se/recommerce/forsale/search?product_category=2.93.3905.64&q=gameboy), 64 listings in 2 pages (the page's "106 annonser" is not the listing count).
- Plain curl gets the search pages; their schema.org data (CollectionPage) holds each listing's title, link and first photo. Photos at `images.blocketcdn.se/dynamic/1600w/item/<id>/<uuid>` (1600x2133 seen; 2000w is a 404; whether 1600w scales smaller originals up is not known).
- src/blocket_photos.py (`list <search URL>`, `download <listings.json>`), as tradera_photos.py; listings in downloaded-photos/blocket-listings.json, photos in downloaded-photos/blocket-search/, records in downloaded-photos/blocket-sources.json.
- Mercari, European releases (2026-11-23): searched with "PAL", 29 of the first 65 found nothing. A trial without it, on 5 of those 29: 2 found listings (Bomberman NES Classics, Disney Sports Motocross), 3 still none. US sellers seldom write PAL, and many of these are PAL-only releases, rare in the US. Now European releases are searched without "PAL" (and without ":" and "!"); the 29 searched again in pass "wanted1b". eBay unchanged: there European releases found photos 45 of 58 times (ebay.com) and 39 of 41 (ebay.de) with "PAL".
- All other eBay country sites (the user, 2026-11-23), pass "wanted1-<site>": co.uk, fr, es, nl, befr.ebay.be, at, ch, ie, pl, ca, com.au, com.hk, com.sg, com.my, the same 1537 queries as ebay.de, one search every 60–90 s per tab. ebay.ph redirects to ebay.com (left out). ebay.it: the browser extension isn't allowed to read its pages (not started). com.hk, com.sg and com.my show an error page at their front page, but their search pages work. The tab script: src/ebay_country_tab.js (set `window.EB_SITE` first; the query list appended to it and the whole file loaded through a file input). Many listings show up on several sites; ingest skips items already downloaded. Batches `~/Downloads/ebay-<site>-batch-wanted1-<n>.json`.
- Ingest must run one at a time: ebay_photos.py ingest rewrites downloaded-photos/sources.json and searches.json whole, so two ingests at once lose each other's records. The ebay.com and ebay.de loops did, in their first hours: 12 searches and 27 photo records lost (photos on disk; records rebuilt from listing.json, searches taken in again from their batches). Now one loop takes in every eBay site and Jauce in turn (Mercari has its own record files).
- eBay's rate limit is shared across its country sites (2026-11-23): with 16 sites searching at once (about 13 searches a minute in all), ten country sites were blocked between 08:27 and 08:45 after about 30 searches each, then ebay.com and ebay.de 21 s apart at 09:09 (each had gone 200+ searches between blocks alone). Blocks show as HTTP 403 on some sites and as a page without a result list on others. Since then the tabs take turns (the user: "limit them to the global rate, or alternate between countries"): each tab's search waits for its slot in a clock-based rotation, `EB_SLOT(i, n, ms)`: tab i of n searches at the start of slot i of each n × ms cycle; set to 16 sites and 75 s, one eBay search every 75 s in all, each site every 20 min.
- Chrome asks once per site to allow a page to download several files; until allowed, a tab's later batches wait (the first one gets through). They were released when the user allowed them.
- Country sites skip releases that already have 5 photos from this crawl (the user, 2026-11-23): photo records fetched since 2026-11-22 in downloaded-photos/sources.json, jauce-sources.json and mercari-sources.json, counted per release (older records left out: they include photos deleted by hand). 323 releases; `EB.prune(list)` removes them from the unsearched part of each country tab's queue (ebay.com and ebay.de keep theirs). About 1200 searches left per country site.

## 2026-11-25: pass "wanted2", the latest wanted list (all eBay sites, Jauce, Mercari)

- The wanted1 tabs had stopped on 2026-11-23 around 16:30 (ebay.com 349 of 1537 searched, ebay.de 304, the other country sites 4 to 119; Jauce had finished; Mercari 490 of 789). Restarted as a new pass on the wanted list of 2026-11-25 (generated/publish/wanted.json): 1142 releases, 1132 without the special shells (main-old checkout's special-shells.tsv).
- Per site, the releases never searched there in wanted1 come first, in the list's rank order; those searched there in wanted1 (2–3 days before: mostly the same listings) last.
- eBay: each release searched once, on one site (the user: not once per eBay domain; the first setup, all 16 sites with the same 1121 queries, was stopped after 4 searches): European releases on ebay.de (311, without "cartridge"), the rest on ebay.com (808, with "cartridge"), passes "wanted2-de" and "wanted2-com". One search every 75 s in all (`EB_SLOT` [i, 2, 75000]): about 23 hours. Releases searched on any eBay site in wanted1 come last. Batches `~/Downloads/ebay-<site>-batch-wanted2-<site>-<n>.json`.
- Jauce: 537 short queries, pass "wanted2". Mercari US: 585 queries (releases without a Japanese id; European ones without "PAL", ":" and "!"), pass "wanted2". Batches `~/Downloads/jauce-wanted2-batch-<n>.json`, `~/Downloads/mercari-wanted2-batch-<n>.json`.
- The tab scripts are files now (they used to be typed into the tabs, and the slot rotation was lost with them): src/ebay_country_tab.js (EB_SITE, EB_PASS, EB_SLOT, EB_QUEUE), src/jauce_tab.js (JC_PASS, JC_QUEUE), src/mercari_tab.js (MC_PASS, MC_QUEUE). Per tab, a run file (the settings, the script and the queue in one .js) is loaded through a file input added with javascript_tool (`(0,eval)` of the file's text), with the extension's file_upload.
- One shell loop takes in every batch, one ingest at a time.
- Tradera and Blocket (the user: search for specific titles, not whole categories): one search per release, by the title eBay's queries use without punctuation, no system or region words (`tradera_photos.py queries`, 1121 queries). A listing is kept when its title holds ¾ of the title's words, names no other system, and isn't a manual, box, ad, poster, guide, repro, figure or the like (`tradera_photos.wanted_listing`); complete in box or with a manual last; at most 5 photos per release.
- Tradera: plain curl now gets a "Client Challenge" page; the search pages (`/search?q=`, for sale and with `&itemStatus=Sold`) are fetched from a tradera.com tab (src/tradera_tab.js), one release every 8–12 s. Results are the flight data's `"items":[{"itemId"…` array; a search without results has `"items":[],"relatedItems"…` (unrelated listings, not used). Batches `~/Downloads/tradera-wanted2-batch-<n>.json`, `tradera_photos.py ingest`; searches in downloaded-photos/tradera-searches.json.
- Blocket: plain curl still works; `blocket_photos.py search <queries>`, the search's first page (`/recommerce/forsale/search?q=`, no category: its search is loose, the title check does the filtering), one every 3 s; searches in downloaded-photos/blocket-searches.json.
- Divided, 2026-11-25 (the user: each release searched once, on one site, not once per site; exactness doesn't matter, the photos are added periodically and the wanted list updated): the wanted list in rank order, each release given to the next site in turn among those that can search it (eBay: ebay.de for European releases, ebay.com for the rest; Mercari: no Japanese id; Jauce: Japanese ids with a title to search by; Tradera and Blocket: any). Releases already searched in wanted2 anywhere left out (135). Shares: eBay 233 (ebay.com 158, ebay.de 75), Tradera 234, Blocket 234, Jauce 159, Mercari 127. One search every 75 s on eBay: about 5 hours.
- What has been searched where: each site's searches file in downloaded-photos/ (searches.json for eBay, jauce-searches.json, mercari-searches.json, tradera-searches.json, blocket-searches.json), per release and pass; every listing downloaded (or found too small) is in the site's sources file and never downloaded again. The next pass's queues should leave out releases searched recently on any site.

- Passes "wanted3" and "wanted4", 2026-11-25 evening: the wanted list divided again the same way, releases searched in wanted2 (or wanted3) on any site left out, those searched in wanted1 last. wanted3 (the list of 18:16, built before that day's photos were added): 86 releases, 73 of them ebay.com's unreached wanted2 queue (stopped); ebay.com 19, Tradera 19, Blocket 19, Jauce 11, Mercari 7. wanted4 (the list rebuilt by make all at 22:21, 1037 releases, 1000 of them searched that day): 27 left, 16 searchable: ebay.com 3, ebay.de 1, Mercari 4, Tradera 4, Blocket 4. Of the 1046 wanted releases searched in wanted2: 392 got photos, 473 had no matching listing, 181 had matching listings but none kept (89 only too small photos).

## 2026-11-25: smaller webshops checked again, and last photos of deleted Jauce and Tradera downloads

- Webshops: each crawled shop's listing pages read again (no product pages) and compared with its stored listing of 2026-11-18. New products: Game Play Stores 530 (the first crawl had found 331 of 861: older product ids, missed then), Retro Game Collector 43, Gamewalhalla 15, Nostalgibutiken 10 (3 repros), Games & Co 8, Retro MTL 8, VPD 5, Retrospillkongen 4, Dutch Game Boys 4, El Rincon Del Retro 3, Retro Game World 2, Spel & Sånt 1, Gameland Groningen 1; none in the other 25 (Console Passion's and Game Paradise's "new" links were menu links). Those 13 shops crawled again (`shop_photos.py run <names>`: known products skipped). The 5 browser-only shops not checked.
- remove-photos keeps no log of what it deletes (only the terminal line and photo-sources.json's record removed). Deleted by hand is worked out as: downloaded, not in photo-sources.json, not in remove-low-resolution's deleted.json, not waiting in downloaded-photos/ or save-new-images-here/. Of the downloads: Jauce 2085 of 5657 deleted, Tradera 3288 of 7500.
- Last photos (the user: a deleted first photo often wasn't the cartridge): for the releases on the wanted list, 600 Jauce listings (262 releases) and 342 Tradera ones (82 releases; Tradera's category photos matched to a release by title, src/last_photos.py best_release). Their pages still show every photo after the auction ended (Jauce `/auction/<id>`, Tradera `/item/0/<id>/x` with the flight data's "images" after "itemMainImageTemplate"); read in tabs (src/listing_photos_tab.js), the last photo downloaded by `last_photos.py ingest` as yahoo-<id>-last.jpg / tradera-<id>-last.jpg. Each listing looked at: downloaded-photos/last-photos.json.
