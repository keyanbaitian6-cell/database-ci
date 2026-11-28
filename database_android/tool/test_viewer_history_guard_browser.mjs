// Build viewer_main.dart and stage_viewer.py before this browser test.
// 2026-11-26 点検①②④（DATABASE_REVIEW_20261126.md）：個人用閲覧ページ（メルヘン版）の実ビルドで、端末の履歴を失わないこと。
// 架空の記録・模擬の IndexedDB 操作・模擬のGoogle応答（script.google.com を差し替え）だけを使う。
// ① 「バックアップを読み込む」でPCの分けた書き出しの1つ（見出し split_stores・1店のファイル stores）を選んだら、
//    保存の前に止めて案内を出す。端末の本体は変わらず、開き直しても2店の履歴が残る。旧形式の完全なファイルは読める。
// ② Driveの更新で端末の本体を読めない（読み出しの失敗）・壊れている（不正なJSON）ときは保存せずに見送り、
//    次の正常な更新で端末だけにあった古い日（7/1）を残して合わせる。本当に初回（本体が無い）なら新着を保存する。
// ④ 段階B1の差枚表は、端末の本体の目印と対応させる。書き出しの時刻・件数が同じ別のファイルを読み込んだ直後、
//    照合の途中で本体が替わったあとの再起動では、前の本体の表を使わない。
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
const url = `https://script.google.com/macros/s/AKfycbGUARD${'x'.repeat(40)}/exec`;
const hash = text => createHash('sha256').update(text).digest('hex');
const OLD_EXPORT = '2026-11-25T08:00:00+09:00', NEW_EXPORT = '2026-11-26T08:00:00+09:00';

// 差枚の分かる架空の記録（線は外し、差枚を添えた形）。
const rec = (store, day, rack, net) => ({store, day, machine: store === 'saiwaichou' ? 'ハナハナ' : 'ジャグラー', rack,
  games: 4000, bb: 10, rb: 5, graph_measurement: {baseline_y: 200.5, peak_y: 100.5, end_y: 150.5, curve_remote: true, curve_index: rack,
    net_estimate: {value: net, needs_check: false, max_hold: null, games: 4000}}});
const pcHeader = (exported, extra = {}) => ({format: 'database-backup', version: 1, exported_at: exported, source: 'pc-viewer', days: 60, ...extra});
// PCの書き出し（database/core.py の export_viewer）と同じ1台1行の形。
const pcFile = (header, records) => JSON.stringify(header).slice(0, -1) + ', "records": [' +
  records.map((r, i) => (i ? ',\n' : '\n') + JSON.stringify(r)).join('') + '\n]}';
// 端末に保存してある本体の形（web/index.html の finish）。
const stored = (exported, records) => JSON.stringify({header: pcHeader(exported, {date_events: []}), records, candidates: [],
  date_events: [], file: 'x', loaded_at: exported});

const TWO = [rec('nagamachiminami', '2026-07-01', 100, 100), rec('saiwaichou', '2026-11-25', 101, 200)];

const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
const helpers = () => {
  window.__idb = (op, key, value) => new Promise((resolve, reject) => {
    const q = indexedDB.open('database-viewer', 1);
    q.onupgradeneeded = () => q.result.createObjectStore('kv');
    q.onerror = () => reject(q.error);
    q.onsuccess = () => {
      const db = q.result, tx = db.transaction('kv', op === 'get' ? 'readonly' : 'readwrite'), s = tx.objectStore('kv');
      const r = op === 'get' ? s.get(key) : op === 'delete' ? s.delete(key) : s.put(value, key);
      tx.oncomplete = () => { db.close(); resolve(r.result ?? null); };
      tx.onerror = tx.onabort = () => { db.close(); reject(tx.error); };
    };
  });
  // 模擬の読み出し失敗：__failGet の間だけ、本体（'data'）の読み出しが失敗する（iPhoneの一時的な IndexedDB の失敗の代わり）。
  const get = IDBObjectStore.prototype.get;
  IDBObjectStore.prototype.get = function (key) {
    if (window.__failGet && key === 'data' && this.name === 'kv') throw new DOMException('合成の読み込み失敗', 'UnknownError');
    return get.apply(this, arguments);
  };
};

// onPage：ページを作った直後に受け取る（模擬のGoogle応答が、閲覧ページの起動時の自動更新より前にページを使えるように。
// 2026-11-28、開くのが遅いと current がまだ空のまま応答が呼ばれ、②a が TypeError で落ちていた）。
async function open(context, seed = {}, onPage = null) {
  const page = await context.newPage(), errors = [];
  if (onPage) onPage(page);
  page.on('pageerror', e => errors.push(e.message));
  await page.addInitScript(helpers);
  await page.goto(origin + '/setup');
  await page.evaluate(async ({seed}) => {
    if (seed.remote) localStorage.setItem('database-viewer-remote', seed.remote);
    if (seed.table) localStorage.setItem('database-viewer-day-net', seed.table);
    if (seed.data != null) await window.__idb('put', 'data', seed.data);
    if (seed.id) await window.__idb('put', 'data_id', seed.id);
    // 表示中の店（web/index.html と同じく鍵 active_source に meruhen。2026-11-28 まで鍵と値が逆だった）
    if (seed.data != null) await window.__idb('put', 'active_source', 'meruhen');
  }, {seed});
  await reopen(page);
  return {page, errors};
}
// Flutterの読み上げ用の木（文字を探すのに使う）を有効にする。`?semantics` で起動の最初から有効にする
// （2026-11-28、viewer_main.dart の main。途中で入口を押して有効にすると、押した時刻と描き直しの重なり方で結果が変わり、
// 一度消えて出し直した知らせが木に入らない不具合〔Notice に key を付けて直した〕を見逃したり、CIで時々落ちたりした）。
// 入口を押す処理は、有効にならなかったときの予備として残す。
async function reopen(page) {
  await page.goto(origin + '/database-viewer/?semantics');
  await page.waitForSelector('flt-glass-pane', {state: 'attached', timeout: 60000});
  for (let i = 0; i < 200; i++) {
    if (await page.locator('flt-semantics').count()) return;
    const placeholder = page.locator('flt-semantics-placeholder');
    if (await placeholder.count()) await placeholder.evaluate(e => e.click()).catch(() => {});
    await page.waitForTimeout(100);
  }
  throw new Error('読み上げ用の木が有効になりませんでした');
}
const idb = (page, key) => page.evaluate(async key => {
  const failing = window.__failGet; window.__failGet = false;
  try { return await window.__idb('get', key); } finally { window.__failGet = failing; }
}, key);
async function pickFile(page, name, text) {
  const button = page.getByRole('button', {name: 'バックアップを読み込む', exact: true}).first();
  await button.waitFor({timeout: 60000});
  const deadline = Date.now() + 15000;
  while (!await button.isEnabled()) { assert.ok(Date.now() < deadline, 'ファイルのボタンが有効になる'); await page.waitForTimeout(50); }
  const chooser = page.waitForEvent('filechooser', {timeout: 10000});
  await button.evaluate(e => e.click());
  await (await chooser).setFiles({name, mimeType: 'application/json', buffer: Buffer.from(text)});
}
const daysOf = text => [...new Set(JSON.parse(text).records.map(r => r.store + '|' + r.day))].sort();

// ① 分けた書き出しの1つは読み込まない。
{
  const context = await browser.newContext({viewport: {width: 393, height: 852}});
  await context.route('https://script.google.com/**', route => route.abort());
  const body = stored(OLD_EXPORT, TWO);
  const {page, errors} = await open(context, {data: body, id: 'body-A'});
  await page.getByText(/読み込んだバックアップ：.*2台/).first().waitFor({timeout: 30000});
  const splitHeader = pcFile(pcHeader(NEW_EXPORT, {split_stores: ['nagamachiminami', 'saiwaichou'], date_events: []}), []);
  await pickFile(page, 'database-viewer.json', splitHeader);
  await page.getByText(/見出しのファイル/).first().waitFor({timeout: 30000});
  assert.equal(await idb(page, 'data'), body, '見出しのファイル：端末の本体は変えない');
  assert.equal(await idb(page, 'data_id'), 'body-A');
  const storeFile = pcFile(pcHeader(NEW_EXPORT, {stores: ['saiwaichou'], record_deletions: []}), [rec('saiwaichou', '2026-11-26', 101, 300)]);
  // ファイル名に頼らない（中身で見分ける）。
  await pickFile(page, 'backup.json', storeFile);
  await page.getByText(/1店分のファイル（幸町の台だけ）/).first().waitFor({timeout: 30000});
  assert.equal(await idb(page, 'data'), body, '1店のファイル：端末の本体は変えない');
  assert.equal(await idb(page, 'data_id'), 'body-A');
  // 開き直しても2店の履歴が残る。
  await reopen(page);
  await page.getByText(/読み込んだバックアップ：.*2台/).first().waitFor({timeout: 30000});
  assert.deepEqual(daysOf(await idb(page, 'data')), ['nagamachiminami|2026-07-01', 'saiwaichou|2026-11-25']);
  // 旧形式の完全な閲覧用（店を分けないPCの書き出し）は、今までどおり読み込む。本体の目印は新しくなる。
  const full = pcFile(pcHeader(NEW_EXPORT, {date_events: [], record_deletions: []}),
    [...TWO, rec('saiwaichou', '2026-11-26', 101, 300)]);
  await pickFile(page, 'database-viewer.json', full);
  await page.getByText(/3台を読み込みました/).first().waitFor({timeout: 30000});
  assert.equal(JSON.parse(await idb(page, 'data')).records.length, 3);
  const id = await idb(page, 'data_id');
  assert.equal(typeof id, 'string'); assert.notEqual(id, 'body-A');
  assert.deepEqual(errors, []);
  await context.close();
  console.log('PASS ①：見出し・1店のファイルは保存前に止めて案内、開き直しても2店が残る、完全なファイルは読める');
}

// ② Driveの更新：読み出しの失敗・壊れた本体は見送り、次の正常な更新で古い日を残す。初回は保存する。
function driveRoutes(context, page, fresh, {failFirst = false} = {}) {
  let failNext = failFirst;
  const requests = [];
  return context.route('https://script.google.com/**', async route => {
    const u = new URL(route.request().url()), headers = {'access-control-allow-origin': '*'};
    requests.push(u.search);
    if (u.searchParams.has('check')) return route.fulfill({status: 200, contentType: 'application/json', headers,
      body: JSON.stringify({format: 'drive-check', version: 'v1', name: 'database-viewer.json'})});
    if (u.searchParams.has('file')) return route.fulfill({status: 200, contentType: 'application/json', headers, body: JSON.stringify({error: '共有ファイルはありません'})});
    if (failNext) { failNext = false; await page().evaluate(() => { window.__failGet = true; }); }
    return route.fulfill({status: 200, contentType: 'application/json', headers, body: fresh});
  });
}
const FRESH = pcFile(pcHeader(NEW_EXPORT, {date_events: [], record_deletions: []}), [rec('saiwaichou', '2026-11-26', 101, 300)]);
{
  // ②a 読み出しの失敗。
  const context = await browser.newContext({viewport: {width: 393, height: 852}});
  let current = null;
  await driveRoutes(context, () => current, FRESH, {failFirst: true});
  const body = stored(OLD_EXPORT, TWO);
  const {page, errors} = await open(context, {data: body, id: 'body-A', remote: url}, p => { current = p; });
  await page.getByText(/保存せずに見送りました/).first().waitFor({timeout: 30000});
  await page.getByText(/端末に保存した内容を読めませんでした/).first().waitFor();
  assert.equal(await idb(page, 'data'), body, '読み出しに失敗したら、端末の本体を新着だけで置き換えない');
  assert.equal(await idb(page, 'data_id'), 'body-A');
  // 失敗が終わったあとの正常な更新（更新ボタン）で、端末だけにあった7/1を残して合わせる。
  await page.evaluate(() => { window.__failGet = false; });
  await page.getByRole('button', {name: 'Googleドライブの最新を読み込む', exact: true}).first().evaluate(e => e.click());
  await page.getByText(/より前の2台を合わせて表示しています/).first().waitFor({timeout: 30000});
  assert.deepEqual(daysOf(await idb(page, 'data')), ['nagamachiminami|2026-07-01', 'saiwaichou|2026-11-25', 'saiwaichou|2026-11-26']);
  await reopen(page);
  await page.getByText(/自動で読み込み：.*3台（うち2台は前に読み込んだ古い日の記録）/).first().waitFor({timeout: 30000});
  assert.deepEqual(daysOf(await idb(page, 'data')), ['nagamachiminami|2026-07-01', 'saiwaichou|2026-11-25', 'saiwaichou|2026-11-26']);
  assert.deepEqual(errors, []);
  await context.close();
}
{
  // ②b 壊れた本体（途中で切れたJSON）。開くときに読めず、更新でも新着だけを保存しない。
  const context = await browser.newContext({viewport: {width: 393, height: 852}});
  let current = null;
  await driveRoutes(context, () => current, FRESH);
  const broken = stored(OLD_EXPORT, TWO).slice(0, 80);
  const {page} = await open(context, {data: broken, id: 'body-A', remote: url}, p => { current = p; });
  await page.getByText(/壊れていて読めません/).first().waitFor({timeout: 30000});
  assert.equal(await idb(page, 'data'), broken, '壊れた本体を新着だけで置き換えない');
  await context.close();
}
{
  // ②c 本当に初回（端末に本体が無い）は、Driveの新着を保存する。
  const context = await browser.newContext({viewport: {width: 393, height: 852}});
  let current = null;
  await driveRoutes(context, () => current, FRESH);
  const {page, errors} = await open(context, {remote: url}, p => { current = p; });
  await page.getByText(/Googleドライブの最新（1台）を読み込みました/).first().waitFor({timeout: 30000});
  assert.deepEqual(daysOf(await idb(page, 'data')), ['saiwaichou|2026-11-26']);
  assert.equal(typeof await idb(page, 'data_id'), 'string');
  assert.deepEqual(errors, []);
  await context.close();
  console.log('PASS ②：読み出しの失敗・壊れた本体は保存せずに見送り、次の正常な更新で7/1を残す。初回は保存する');
}

// ④ 差枚表と本体の対応。
const days2 = ['2026-11-08', '2026-11-09'];
const pair = (day, n, s) => [rec('nagamachiminami', day, 100, n), rec('saiwaichou', day, 101, s)];
{
  // ④a 表示直後：時刻・件数が同じ別のファイルを読み込んだら、前の本体の表（+777）を使わない。
  const body = stored(OLD_EXPORT, days2.flatMap(d => pair(d, 400, 200)));
  const stamp = 'body-A|' + OLD_EXPORT + '|4';
  const table = JSON.stringify({version: 1, stamp, cells: Object.fromEntries(days2.flatMap(d => [
    ['nagamachiminami|' + d, [777, 1, 1, 0, 0, 0]], ['saiwaichou|' + d, [200, 1, 1, 0, 0, 0]]]))});
  const other = pcFile(pcHeader(OLD_EXPORT, {date_events: [], record_deletions: []}), days2.flatMap(d => pair(d, 420, 210)));
  for (const pick of [false, true]) {
    const context = await browser.newContext({viewport: {width: 393, height: 852}});
    await context.route('https://script.google.com/**', route => route.abort());
    const {page, errors} = await open(context, {data: body, id: 'body-A', table});
    if (pick) {
      await pickFile(page, 'other.json', other);
      await page.getByText(/4台を読み込みました/).first().waitFor({timeout: 30000});
    }
    await page.getByRole('button', {name: '日別の差枚（推定）', exact: true}).click({timeout: 60000});
    await page.getByText(/2026年11月のデータ/).first().waitFor();
    const [shown, hidden] = pick ? ['+420', '+777'] : ['+777', '+420'];
    await page.getByText(shown, {exact: true}).first().waitFor({timeout: 30000});
    assert.equal(await page.getByText(hidden, {exact: true}).count(), 0, pick ? '読み込んだ直後' : '同じ本体なら表を使う');
    assert.deepEqual(errors, []);
    await context.close();
  }
}
{
  // ④b 照合中に本体が替わる（別のタブが時刻・件数の同じ別の本体を保存した）：照合が終わって表を控えても、その表は
  // 照合を始めたときの本体の目印で控えるので、再起動後の別の本体には使わない。
  // 長町南は100番・102番（+100・+300）、幸町は101番（+200）。
  const rows = day => [100, 101, 102].map((rack, i) => rec(i % 2 ? 'saiwaichou' : 'nagamachiminami', day, rack,
    i % 2 ? 200 : 100 * (i + 1)));
  const parts = ['2026-11-09', '2026-11-10'].map(day => { const text = JSON.stringify(rows(day)); return {hash: hash(text), day, count: 3, bytes: Buffer.byteLength(text), text}; });
  const listing = parts.map(({hash, day, count, bytes}) => ({hash, day, count, bytes}));
  const manifest = {format: 'database-viewer-parts', version: 2, site: 'meruhen', revision: hash(JSON.stringify(listing)),
    header: pcHeader(NEW_EXPORT, {date_events: [], machines: []}), parts: listing, days: parts.map(p => p.day), count: 6};
  const texts = Object.fromEntries(parts.map(p => [p.hash, p.text]));
  const context = await browser.newContext({viewport: {width: 393, height: 852}});
  let online = true;
  await context.route('https://script.google.com/**', route => {
    if (!online) return route.abort();
    const u = new URL(route.request().url()), headers = {'access-control-allow-origin': '*'};
    const json = value => route.fulfill({status: 200, contentType: 'application/json', headers, body: JSON.stringify(value)});
    if (u.searchParams.has('check')) return json({format: 'drive-check', version: 'parts:' + manifest.revision, parts: manifest});
    if (u.searchParams.has('parts')) return json({format: 'database-viewer-parts', revision: manifest.revision,
      parts: u.searchParams.get('parts').split(',').map(h => ({hash: h, text: texts[h]}))});
    return json({error: '共有ファイルはありません'});
  });
  const page = await context.newPage(), errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.addInitScript(helpers);
  await page.addInitScript(() => {
    let bridge;
    Object.defineProperty(window, 'databaseViewer', {configurable: true, get: () => bridge, set(value) {
      bridge = value;
      const check = value.checkCalendar.bind(value);
      value.checkCalendar = async (...args) => {
        // 照合の途中：別のタブが、書き出しの時刻・件数が同じで差枚の違う本体を保存する。
        window.__idBefore = await window.__idb('get', 'data_id');
        const doc = JSON.parse(await window.__idb('get', 'data'));
        for (const r of doc.records) r.graph_measurement.net_estimate.value += 20;
        await value.save(JSON.stringify(doc), true);
        window.__idAfter = await window.__idb('get', 'data_id');
        return check(...args);
      };
    }});
  });
  await page.goto(origin + '/setup');
  await page.evaluate(async ({url, body}) => {
    localStorage.setItem('database-viewer-remote', url);
    await window.__idb('put', 'data', body);
  }, {url, body: stored(OLD_EXPORT, rows('2026-11-08'))});
  await reopen(page);
  let log = null;
  for (let i = 0; i < 160 && !(log?.calendar && log?.trend && !log.running); i++) {
    await page.waitForTimeout(250);
    log = await page.evaluate(() => { try { return JSON.parse(localStorage.getItem('database-viewer-diag')); } catch { return null; } });
  }
  assert.equal(log?.calendar?.status, 'match', JSON.stringify(log?.calendar));
  const [before, after, table] = await page.evaluate(() => [window.__idBefore, window.__idAfter, JSON.parse(localStorage.getItem('database-viewer-day-net'))]);
  assert.ok(before && after && before !== after, '照合の途中で本体（と目印）が替わった');
  assert.equal(table.stamp, before + '|' + NEW_EXPORT + '|9', '表は照合を始めたときの本体の目印で控える');
  assert.equal(await idb(page, 'data_id'), after);
  // 再起動後（通信なし）：端末の本体は替わった方。表（長町南 11/10 は +400）ではなく、今の計算（+440）で出す。
  online = false;
  await reopen(page);
  await page.getByRole('button', {name: '日別の差枚（推定）', exact: true}).click({timeout: 60000});
  await page.getByText(/2026年11月のデータ/).first().waitFor();
  await page.getByText('+440', {exact: true}).first().waitFor({timeout: 30000});
  assert.equal(await page.getByText('+400', {exact: true}).count(), 0, '再起動後に前の本体の表を使わない');
  assert.deepEqual(errors, []);
  await context.close();
  console.log('PASS ④：時刻・件数が同じ別のファイルの読み込み直後・照合中に替わった本体の再起動後は、前の本体の差枚表を使わない');
}

await browser.close();
await new Promise(resolve => server.close(resolve));
