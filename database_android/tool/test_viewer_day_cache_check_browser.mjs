// Build viewer_main.dart and stage_viewer.py before this browser test.
// 段階B0（VIEWER_DAY_STORE.md、2026-11-18 利用者「既存で進めて」）：メルヘン版の閲覧ページが、Googleドライブの更新で本体を
// 保存し直したあと、端末の本体と日別キャッシュ（Googleの部品）を日ごとに照合し、結果を診断に控えることを確かめる。
// ・実ビルド（Flutterまで）：更新のあとに照合が1回動き「一致」になる。表示は変えない。
// ・照合は読むだけ：本体・日別キャッシュの中身を変えない。
// ・キャッシュの1日が違えば「一致しない日」としてその日を出す。キャッシュの日が本体に無い・本体の日がキャッシュに無い場合も。
// ・日別キャッシュが無ければ本体を読まずに終える。照合を止めている間（途中で終わった後の24時間）は照合しない。
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = process.env.VIEWER_WEB_ROOT || fileURLToPath(new URL('../build/web/', import.meta.url));
const types = {'.js': 'text/javascript', '.mjs': 'text/javascript', '.html': 'text/html; charset=utf-8', '.json': 'application/json', '.wasm': 'application/wasm', '.css': 'text/css', '.png': 'image/png'};
const server = http.createServer(async (req, res) => {
  const pathname = new URL(req.url, 'http://x').pathname;
  if (pathname === '/setup') { res.setHeader('content-type', 'text/html'); res.end('<!doctype html><body>s</body>'); return; }
  const name = decodeURIComponent(pathname).replace(/^\/database-viewer\//, '');
  const file = path.resolve(root, name || 'index.html');
  if (!file.startsWith(path.resolve(root))) { res.writeHead(403).end(); return; }
  try { res.setHeader('content-type', types[path.extname(file)] || 'application/octet-stream'); res.end(await fs.readFile(file)); }
  catch { res.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const id = 'AKfycbCHECK' + 'x'.repeat(40), url = `https://script.google.com/macros/s/${id}/exec`;
const hash = text => createHash('sha256').update(text).digest('hex');
const OLD_EXPORT = '2026-11-10T00:00:00+09:00', NEW_EXPORT = '2026-11-11T00:00:00+09:00';
const rows = (day, generation) => Array.from({length: 3}, (_, i) => ({
  store: i % 2 ? 'saiwaichou' : 'nagamachiminami', day, machine: i % 2 ? 'ハナハナ' : 'ジャグラー', rack: 100 + i,
  games: 1000 * generation + i, bb: 3 + i, rb: 1,
  graph_measurement: {baseline_y: 100, peak_y: 10 + i, curve_index: i, preview_image: 'IMG' + day + i},
}));
const header = exported => ({format: 'database-backup', version: 1, source: 'pc-viewer', exported_at: exported, date_events: [], machines: []});
function manifest(days, exported) {
  const parts = days.map(({day, list}) => { const text = JSON.stringify(list); return {hash: hash(text), day, count: list.length, bytes: Buffer.byteLength(text), text}; });
  const listing = parts.map(({hash, day, count, bytes}) => ({hash, day, count, bytes}));
  return {manifest: {format: 'database-viewer-parts', version: 2, site: 'meruhen', revision: hash(JSON.stringify(listing)),
    header: header(exported), parts: listing, days: days.map(d => d.day), count: listing.reduce((a, p) => a + p.count, 0)},
  texts: Object.fromEntries(parts.map(p => [p.hash, p.text]))};
}
const remote = manifest(['2026-11-09', '2026-11-10'].map(day => ({day, list: rows(day, 2)})), NEW_EXPORT);
const body = JSON.stringify({header: header(OLD_EXPORT), records: ['2026-11-08', '2026-11-09'].flatMap(d => rows(d, 1)),
  candidates: [], date_events: [], history_days: ['2026-11-08', '2026-11-09'], file: 'x', loaded_at: OLD_EXPORT});

const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
const helpers = () => {
  window.__open = (n, v, stores) => new Promise((resolve, reject) => {
    const q = v ? indexedDB.open(n, v) : indexedDB.open(n);
    q.onupgradeneeded = () => { for (const s of stores || []) if (!q.result.objectStoreNames.contains(s)) q.result.createObjectStore(s); };
    q.onsuccess = () => resolve(q.result); q.onerror = () => reject(q.error);
  });
  window.__all = async () => {
    const dump = {};
    for (const [n, stores] of [['database-viewer', ['kv']], ['database-viewer-parts-v1', ['history-heads', 'history-days']]]) {
      const db = await window.__open(n);
      for (const s of stores) {
        if (!db.objectStoreNames.contains(s)) continue;
        dump[n + '/' + s] = await new Promise((resolve, reject) => {
          const out = [], q = db.transaction(s).objectStore(s).openCursor();
          q.onsuccess = () => { const c = q.result; if (!c) return resolve(out); out.push([String(c.key), JSON.stringify(c.value)]); c.continue(); };
          q.onerror = () => reject(q.error);
        });
      }
      db.close();
    }
    return dump;
  };
  window.__diag = () => JSON.parse(localStorage.getItem('database-viewer-diag') || 'null');
};

// 1. 実ビルド：更新のあとに照合が動き、一致になる。
{
  const context = await browser.newContext({viewport: {width: 393, height: 852}});
  const requests = [];
  await context.route('https://script.google.com/**', route => {
    const u = new URL(route.request().url()), headers = {'access-control-allow-origin': '*'};
    const json = value => route.fulfill({status: 200, contentType: 'application/json', headers, body: JSON.stringify(value)});
    requests.push(u.search);
    if (u.searchParams.has('check')) return json({format: 'drive-check', version: 'parts:' + remote.manifest.revision, parts: remote.manifest});
    if (u.searchParams.has('parts')) return json({format: 'database-viewer-parts', revision: remote.manifest.revision,
      parts: u.searchParams.get('parts').split(',').map(h => ({hash: h, text: remote.texts[h]}))});
    if (u.searchParams.has('file')) return json({error: '共有ファイルはありません'});
    throw new Error('想定外の通信：' + u);
  });
  const page = await context.newPage(), errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto(origin + '/setup');
  await page.evaluate(async ({url, body}) => {
    localStorage.setItem('database-viewer-remote', url);
    const db = await new Promise((res, rej) => { const q = indexedDB.open('database-viewer', 1); q.onupgradeneeded = () => q.result.createObjectStore('kv'); q.onsuccess = () => res(q.result); q.onerror = () => rej(q.error); });
    await new Promise((res, rej) => { const tx = db.transaction('kv', 'readwrite'); tx.objectStore('kv').put(body, 'data'); tx.oncomplete = res; tx.onerror = () => rej(tx.error); }); db.close();
  }, {url, body});
  await page.goto(origin + '/database-viewer/');
  await page.waitForSelector('flt-glass-pane', {state: 'attached', timeout: 60000});
  let log = null;
  for (let i = 0; i < 160 && !(log?.check && !log.running); i++) {
    await page.waitForTimeout(250);
    log = await page.evaluate(() => { try { return JSON.parse(localStorage.getItem('database-viewer-diag')); } catch { return null; } });
  }
  assert.ok(log?.check, '更新のあとに照合の結果が控えられる');
  assert.equal(log.check.status, 'match', JSON.stringify(log.check));
  // 本体：11/08（端末だけの日、3件）＋Driveの11/09・11/10（各3件）。キャッシュも同じ3日。
  assert.equal(log.check.bodyDays, 3); assert.equal(log.check.bodyRecords, 9);
  assert.equal(log.check.cacheDays, 3); assert.equal(log.check.cacheRecords, 9);
  assert.equal(log.phases.check.count, 1); assert.equal(log.phases.check.unfinished, 0);
  assert.equal(log.phases.drive.count, 1);
  assert.equal(log.running, null);
  assert.deepEqual(errors, []);
  // 照合のための通信はしない（一覧と部品だけ）。
  assert.ok(requests.every(q => /check=1|parts=|file=/.test(q)), requests.join(' '));
  // 診断の画面の行。
  const lines = await page.evaluate(async () => JSON.parse(await window.databaseViewer.storageReport()));
  assert.ok(lines.some(l => /^日別キャッシュと本体：一致（3日・9件）/.test(l)), lines.join('\n'));
  assert.ok(lines.some(l => /^日別キャッシュと本体の照合：最後まで終わった1回/.test(l)), lines.join('\n'));
  await context.close();
}

// 2. 照合だけ（画面なし）：読むだけ・違いを見つける・キャッシュが無い・止めている間。
{
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.route('**/flutter_bootstrap.js', route => route.fulfill({contentType: 'text/javascript', body: ''}));
  await page.goto(`${origin}/database-viewer/index.html`);
  await page.waitForFunction(() => window.databaseViewer && typeof window.databaseViewer.checkDayCache === 'function');
  await page.evaluate(helpers);
  // キャッシュが無ければ照合しない（本体も読まない）。
  await page.evaluate(async ({url, body}) => {
    localStorage.setItem('database-viewer-remote', url);
    const kv = await window.__open('database-viewer', 1, ['kv']);
    await new Promise((res, rej) => { const tx = kv.transaction('kv', 'readwrite'); tx.objectStore('kv').put(body, 'data'); tx.oncomplete = res; tx.onerror = () => rej(tx.error); }); kv.close();
  }, {url, body});
  assert.equal(await page.evaluate(() => window.databaseViewer.checkDayCache()), 'no-cache');
  // 端末の日別キャッシュ：本体と同じ2日（本体の記録は画像の項目つき＝照合は表示前と同じ整えで比べる）。
  const seed = days => page.evaluate(async ({url, days}) => {
    const key = url + '|meruhen', db = await window.__open('database-viewer-parts-v1', 2, ['snapshots', 'history-heads', 'history-days']);
    await new Promise((res, rej) => {
      const tx = db.transaction(['history-heads', 'history-days'], 'readwrite');
      for (const [day, text] of Object.entries(days)) tx.objectStore('history-days').put({parts: text ? {['h' + day]: text} : {}}, key + '|' + day);
      tx.objectStore('history-heads').put({header: {format: 'database-backup', version: 1}, days: Object.keys(days).sort(), revision: 1}, key);
      tx.oncomplete = res; tx.onerror = () => rej(tx.error);
    });
    db.close();
  }, {url, days});
  const strip = list => list.map(r => { const g = {...r.graph_measurement}; delete g.preview_image; return {...r, graph_measurement: g}; });
  // 項目の順番が違っても同じ記録（正規化して比べる）。記録の無い日（空の日）は件数0として比べる。
  const reorder = list => list.map(r => Object.fromEntries(Object.entries(r).reverse()));
  await seed({'2026-11-08': JSON.stringify(reorder(strip(rows('2026-11-08', 1)))), '2026-11-09': JSON.stringify(strip(rows('2026-11-09', 1))), '2026-11-07': ''});
  const before = await page.evaluate(() => window.__all());
  assert.equal(await page.evaluate(() => window.databaseViewer.checkDayCache()), 'match');
  assert.deepEqual(await page.evaluate(() => window.__all()), before, '照合は本体・日別キャッシュを変えない');
  assert.deepEqual((await page.evaluate(() => window.__diag())).check.examples, []);
  // 1台だけ値が違う日・本体に無い日・キャッシュに無い日。
  const changed = strip(rows('2026-11-09', 1)); changed[1].games += 1;
  await seed({'2026-11-08': '', '2026-11-09': JSON.stringify(changed), '2026-11-10': JSON.stringify(strip(rows('2026-11-10', 1)))});
  assert.equal(await page.evaluate(() => window.databaseViewer.checkDayCache()), 'mismatch');
  const check = (await page.evaluate(() => window.__diag())).check;
  assert.equal(check.mismatchedDays, 3);
  assert.deepEqual(check.examples, [{day: '2026-11-08', body: 3, cache: 0}, {day: '2026-11-09', body: 3, cache: 3}, {day: '2026-11-10', body: 0, cache: 3}]);
  const lines = await page.evaluate(async () => JSON.parse(await window.databaseViewer.storageReport()));
  assert.ok(lines.some(l => l.startsWith('日別キャッシュと本体：一致しない日 3日（本体2日・6件／キャッシュ3日・6件。例：11/08 本体3件・キャッシュ0件、11/09 本体3件・キャッシュ3件、11/10 本体0件・キャッシュ3件）')), lines.join('\n'));
  // 照合の途中でページが終わっていたら（次に開いたとき check_halt）、24時間は照合しない。結果も変えない。
  await page.evaluate(() => {
    const log = window.__diag(); log.check_halt = {at: new Date().toISOString()};
    localStorage.setItem('database-viewer-diag', JSON.stringify(log));
  });
  assert.equal(await page.evaluate(() => window.databaseViewer.checkDayCache()), null);
  assert.equal((await page.evaluate(() => window.__diag())).check.status, 'mismatch');
  // P’s CUBEを表示している端末では照合しない。
  await page.evaluate(async () => {
    const log = window.__diag(); delete log.check_halt; localStorage.setItem('database-viewer-diag', JSON.stringify(log));
    const kv = await window.__open('database-viewer', 1, ['kv']);
    await new Promise((res, rej) => { const tx = kv.transaction('kv', 'readwrite'); tx.objectStore('kv').put('pscube', 'active_source'); tx.oncomplete = res; tx.onerror = () => rej(tx.error); }); kv.close();
  });
  assert.equal(await page.evaluate(() => window.databaseViewer.checkDayCache()), null);
  await context.close();
}
await browser.close(); server.close();
console.log('PASS: 段階B0の照合（更新のあとに一致・読むだけ・違う日を出す・キャッシュ無し・止めている間・P’s CUBE）');
