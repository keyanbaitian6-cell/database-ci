// Build viewer_main.dart and stage_viewer.py before this browser test.
// 2026-11-19：Googleのスクリプトは、PCの書き出しが新しくなってから日別の部品を作り直すまでの間、?check=1 に部品を付けずに
// 目印だけを返す。そのとき閲覧ページがファイル全体（グラフの線入り）を読むと、更新が重く、本体だけが線入りの形になり、
// 日別キャッシュと食い違った（利用者のiPhone、11/19 1:31「日別キャッシュと本体：一致しない日 60日」）。
// ・日別キャッシュを持つ端末：部品の無い返事ではファイル全体を読まず、更新を見送る（本体・キャッシュは変えない。理由を出す）。
//   部品がそろったら、次の更新で今までどおり読み、照合も一致する。
// ・日別キャッシュの無い端末（古いスクリプトで使ってきた端末）：今までどおりファイル全体を読む。
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
const id = 'AKfycbPENDING' + 'x'.repeat(40), url = `https://script.google.com/macros/s/${id}/exec`;
const hash = text => createHash('sha256').update(text).digest('hex');
const rows = (day, generation) => Array.from({length: 3}, (_, i) => ({
  store: i % 2 ? 'saiwaichou' : 'nagamachiminami', day, machine: i % 2 ? 'ハナハナ' : 'ジャグラー', rack: 100 + i,
  games: 1000 * generation + i, bb: 3 + i, rb: 1, graph_measurement: {baseline_y: 100, peak_y: 10 + i, curve_index: i}}));
const header = exported => ({format: 'database-backup', version: 1, source: 'pc-viewer', exported_at: exported, date_events: [], machines: []});
function manifest(days, exported) {
  const parts = days.map(day => { const text = JSON.stringify(rows(day, 2)); return {hash: hash(text), day, count: 3, bytes: Buffer.byteLength(text), text}; });
  const listing = parts.map(({hash, day, count, bytes}) => ({hash, day, count, bytes}));
  return {manifest: {format: 'database-viewer-parts', version: 2, site: 'meruhen', revision: hash(JSON.stringify(listing)),
    header: header(exported), parts: listing, days, count: listing.length * 3},
  texts: Object.fromEntries(parts.map(p => [p.hash, p.text]))};
}
const first = manifest(['2026-11-09', '2026-11-10'], '2026-11-10T23:00:00+09:00');
const second = manifest(['2026-11-09', '2026-11-10', '2026-11-11'], '2026-11-11T23:00:00+09:00');
// 部品を作り直す前のファイル全体（線入り。読まれてはいけない）。
const fullFile = {...header('2026-11-11T23:00:00+09:00'), records: ['2026-11-09', '2026-11-10', '2026-11-11'].flatMap(d => rows(d, 3)
  .map(r => ({...r, graph_measurement: {...r.graph_measurement, curve: [[0, 100], [10, 50]]}})))};

const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
async function device(state) {
  const context = await browser.newContext({viewport: {width: 393, height: 852}});
  const requests = [];
  await context.route('https://script.google.com/**', route => {
    const u = new URL(route.request().url()), headers = {'access-control-allow-origin': '*'};
    const json = value => route.fulfill({status: 200, contentType: 'application/json', headers, body: JSON.stringify(value)});
    requests.push(u.search || '(全体)');
    const remote = state.remote;
    if (u.searchParams.has('check')) {
      return remote ? json({format: 'drive-check', version: 'parts:' + remote.manifest.revision, parts: remote.manifest})
        : json({format: 'drive-check', version: state.plainVersion, name: 'database-viewer.json'});
    }
    if (u.searchParams.has('parts')) return json({format: 'database-viewer-parts', revision: remote.manifest.revision,
      parts: u.searchParams.get('parts').split(',').map(h => ({hash: h, text: remote.texts[h]}))});
    if (u.searchParams.has('file')) return json({error: '共有ファイルはありません'});
    if (!u.search) return json(fullFile);
    throw new Error('想定外の通信：' + u);
  });
  const page = await context.newPage(), errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto(origin + '/setup');
  await page.evaluate(url => localStorage.setItem('database-viewer-remote', url), url);
  const open = async () => {
    await page.goto(origin + '/database-viewer/');
    await page.waitForSelector('flt-glass-pane', {state: 'attached', timeout: 60000});
    let log = null;
    const before = state.driveCount ?? 0;
    for (let i = 0; i < 160 && !(log?.phases?.drive?.count > before && !log.running); i++) {
      await page.waitForTimeout(250);
      log = await page.evaluate(() => { try { return JSON.parse(localStorage.getItem('database-viewer-diag')); } catch { return null; } });
    }
    // 更新のあとに照合（B0〜B2）が続くので、何も動いていない状態が1秒続くまで待つ。
    for (let i = 0, quiet = 0; i < 120 && quiet < 4; i++) {
      await page.waitForTimeout(250);
      log = await page.evaluate(() => { try { return JSON.parse(localStorage.getItem('database-viewer-diag')); } catch { return null; } });
      quiet = log?.running ? 0 : quiet + 1;
    }
    state.driveCount = log?.phases?.drive?.count ?? before;
    return log;
  };
  const stored = () => page.evaluate(async () => {
    const db = await new Promise((res, rej) => { const q = indexedDB.open('database-viewer'); q.onsuccess = () => res(q.result); q.onerror = () => rej(q.error); });
    const text = await new Promise((res, rej) => { const r = db.transaction('kv').objectStore('kv').get('data'); r.onsuccess = () => res(r.result ?? null); r.onerror = () => rej(r.error); });
    db.close(); return text;
  });
  const cacheDays = () => page.evaluate(async url => {
    const db = await new Promise((res, rej) => { const q = indexedDB.open('database-viewer-parts-v1'); q.onsuccess = () => res(q.result); q.onerror = () => rej(q.error); });
    if (!db.objectStoreNames.contains('history-heads')) { db.close(); return null; }
    const head = await new Promise((res, rej) => { const r = db.transaction('history-heads').objectStore('history-heads').get(url + '|meruhen'); r.onsuccess = () => res(r.result ?? null); r.onerror = () => rej(r.error); });
    db.close(); return head ? head.days : null;
  }, url);
  return {context, page, requests, errors, open, stored, cacheDays};
}

// 1. 部品で更新してきた端末。
{
  const state = {remote: first};
  const d = await device(state);
  let log = await d.open();
  assert.equal(log.check?.status, 'match', '部品で更新したあとの照合は一致');
  assert.deepEqual(await d.cacheDays(), ['2026-11-09', '2026-11-10']);
  const body = await d.stored();
  // 2. PCが書き出した直後（Googleがまだ部品を作り直していない）：ファイル全体を読まずに見送る。
  state.remote = null; state.plainVersion = '1763000000000-123456';
  d.requests.length = 0;
  log = await d.open();
  assert.ok(!d.requests.includes('(全体)'), 'ファイル全体を読まない：' + d.requests.join(' '));
  assert.equal(await d.stored(), body, '本体は変えない');
  assert.deepEqual(await d.cacheDays(), ['2026-11-09', '2026-11-10'], '日別キャッシュも変えない');
  assert.equal(log.phases.drive.unfinished, 0); assert.equal(log.phases.check.count, 1, '見送った更新のあとは照合しない');
  const placeholder = d.page.locator('flt-semantics-placeholder');
  if (await placeholder.count()) await placeholder.evaluate(e => e.click());
  await d.page.getByText(/閲覧用の日別の部品を作り直しているところです/).first().waitFor({timeout: 30000});
  // 3. 部品がそろった：今までどおり部品で更新し、照合も一致する。
  state.remote = second;
  log = await d.open();
  assert.deepEqual(await d.cacheDays(), ['2026-11-09', '2026-11-10', '2026-11-11']);
  assert.ok(JSON.parse(await d.stored()).records.some(r => r.day === '2026-11-11'), '新しい日が本体に入る');
  assert.ok(!JSON.parse(await d.stored()).records.some(r => r.graph_measurement?.curve), '線入りのファイル全体は入らない');
  assert.equal(log.check?.status, 'match'); assert.equal(log.phases.check.count, 2);
  assert.deepEqual(d.errors, []);
  await d.context.close();
}

// 4. 日別キャッシュの無い端末（部品を使ったことがない）：今までどおりファイル全体を読む。
{
  const state = {remote: null, plainVersion: '1763000000000-123456'};
  const d = await device(state);
  await d.page.evaluate(async body => {
    const db = await new Promise((res, rej) => { const q = indexedDB.open('database-viewer', 1); q.onupgradeneeded = () => q.result.createObjectStore('kv'); q.onsuccess = () => res(q.result); q.onerror = () => rej(q.error); });
    await new Promise((res, rej) => { const tx = db.transaction('kv', 'readwrite'); tx.objectStore('kv').put(body, 'data'); tx.oncomplete = res; tx.onerror = () => rej(tx.error); }); db.close();
  }, JSON.stringify({header: header('2026-11-09T23:00:00+09:00'), records: rows('2026-11-09', 1)}));
  await d.open();
  assert.ok(d.requests.includes('(全体)'), '日別キャッシュが無ければファイル全体を読む：' + d.requests.join(' '));
  assert.ok(JSON.parse(await d.stored()).records.some(r => r.day === '2026-11-11'), '本体は新しくなる');
  assert.equal(await d.cacheDays(), null, '日別キャッシュは作らない（今までどおり）');
  assert.deepEqual(d.errors, []);
  await d.context.close();
}
await browser.close(); server.close();
console.log('PASS: 部品を作り直す前は見送る（全体を読まない・本体とキャッシュを変えない）・そろったら更新・キャッシュの無い端末は今までどおり');
