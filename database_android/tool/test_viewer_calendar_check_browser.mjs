// Build viewer_main.dart and stage_viewer.py before this browser test.
// 段階B1（VIEWER_DAY_STORE.md、2026-11-18）：メルヘン版の閲覧ページが、Googleドライブの更新で本体を保存し直したあと、
// カレンダーの日ごとの差枚を日別キャッシュ（Googleの部品）から1日ずつ計算し、今の計算（全記録から）と照合して、
// 結果を診断に控えることを確かめる。
// ・実ビルド（Flutterまで）：更新のあとにカレンダーの照合が1回動き「一致」になる。通信は増やさない。
// ・橋渡し（databaseViewer.checkCalendar）：日別キャッシュを1日ずつ渡す（全日を同時に渡さない）・表示前と同じ整えを掛ける・
//   読むだけ（本体・日別キャッシュを変えない）・結果（一致しない・エラー）を控える・キャッシュが無ければ何も呼ばない・
//   止めている間（途中で終わった後の24時間）とP’s CUBEの端末では動かない。B0の照合とは別に止まる。
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
const id = 'AKfycbCAL' + 'x'.repeat(40), url = `https://script.google.com/macros/s/${id}/exec`;
const hash = text => createHash('sha256').update(text).digest('hex');
const OLD_EXPORT = '2026-11-10T00:00:00+09:00', NEW_EXPORT = '2026-11-11T00:00:00+09:00';
// 差枚が計算できる記録（線を外して差枚を添えた形）。店は2つ、1日3台。
const rows = (day, generation) => Array.from({length: 3}, (_, i) => {
  const games = 1000 * generation + i;
  return {store: i % 2 ? 'saiwaichou' : 'nagamachiminami', day, machine: i % 2 ? 'ハナハナ' : 'ジャグラー', rack: 100 + i,
    games, bb: 3 + i, rb: 1,
    graph_measurement: {baseline_y: 200.5, peak_y: 100.5, end_y: 150.5, curve_remote: true, curve_index: i, preview_image: 'IMG' + day + i,
      net_estimate: {value: 100 * (i + 1), needs_check: i === 1, max_hold: null, games}}};
});
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

// 1. 実ビルド：更新のあとにカレンダーの照合が動き、一致になる。
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
  for (let i = 0; i < 160 && !(log?.calendar && !log.running); i++) {
    await page.waitForTimeout(250);
    log = await page.evaluate(() => { try { return JSON.parse(localStorage.getItem('database-viewer-diag')); } catch { return null; } });
  }
  assert.ok(log?.calendar, '更新のあとにカレンダーの照合の結果が控えられる');
  assert.equal(log.calendar.status, 'match', JSON.stringify(log.calendar));
  // 日別キャッシュは3日（11/08は端末だけの日で、Driveの更新で日別キャッシュへ移る）・9件。マスは3日×2店。
  assert.equal(log.calendar.days, 3); assert.equal(log.calendar.records, 9);
  assert.equal(log.calendar.cells, 6); assert.equal(log.calendar.mismatched, 0);
  assert.equal(log.phases.calendar.count, 1); assert.equal(log.phases.calendar.unfinished, 0);
  assert.equal(log.phases.drive.count, 1);
  assert.equal(log.check?.status, 'match', 'B0の本体と日別キャッシュの照合も、これまでどおり動く');
  // 段階B2：日・機種一覧の台の点数も、日別キャッシュの「その日と前30日」だけから計算して一致する
  // （1回1店。初回は長町南の、最新の日11/10と順に回す1日＝11/09の4台。窓のために11/08も読むので days は3）。
  assert.equal(log.scores?.status, 'match', JSON.stringify(log.scores));
  assert.equal(log.scores.store, 'nagamachiminami');
  assert.equal(log.scores.days, 3); assert.equal(log.scores.racks, 4); assert.equal(log.scores.mismatched, 0);
  assert.equal(log.phases.scores.count, 1); assert.equal(log.phases.scores.unfinished, 0);
  assert.equal(log.running, null);
  assert.deepEqual(errors, []);
  // 照合のための通信はしない（一覧と部品だけ）。
  assert.ok(requests.every(q => /check=1|parts=|file=/.test(q)), requests.join(' '));
  const lines = await page.evaluate(async () => JSON.parse(await window.databaseViewer.storageReport()));
  assert.ok(lines.some(l => /^カレンダーの日別計算：一致（3日・6マス）/.test(l)), lines.join('\n'));
  assert.ok(lines.some(l => /^カレンダーの日別計算と照合：最後まで終わった1回/.test(l)), lines.join('\n'));
  assert.deepEqual(log.scores.targets, ['2026-11-09', '2026-11-10']);
  assert.ok(lines.some(l => l.startsWith('日・機種一覧の日別採点：一致（長町南・11/09・11/10の2日・4台）')), lines.join('\n'));
  // 次の更新では幸町。順に回す日は店ごとに「最後に比べた日」で覚える（2026-11-22。長町南は11/09まで済み、幸町はまだ）。
  assert.equal(await page.evaluate(() => localStorage.getItem('database-viewer-b2-store')), '1');
  assert.equal(await page.evaluate(() => localStorage.getItem('database-viewer-b2-day:nagamachiminami')), '2026-11-09');
  assert.equal(await page.evaluate(() => localStorage.getItem('database-viewer-b2-day:saiwaichou')), null);
  assert.equal(await page.evaluate(() => localStorage.getItem('database-viewer-b2-cursor')), null, '古い位置の覚え方は使わない');
  assert.ok(lines.some(l => /^日・機種一覧の日別採点と照合：最後まで終わった1回/.test(l)), lines.join('\n'));
  await context.close();
}

// 2. 橋渡しだけ（画面なし）：1日ずつ渡す・読むだけ・結果の控え・キャッシュ無し・止めている間・P’s CUBE。
{
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.route('**/flutter_bootstrap.js', route => route.fulfill({contentType: 'text/javascript', body: ''}));
  await page.goto(`${origin}/database-viewer/index.html`);
  await page.waitForFunction(() => window.databaseViewer && typeof window.databaseViewer.checkCalendar === 'function');
  await page.evaluate(helpers);
  // Dart の代わりの受け取り：1日ずつ呼ばれた順と中身、finish を呼んだ時点で全日が渡し終わっているかを控える。
  await page.evaluate(() => {
    window.__run = async (finishValue) => {
      const days = [], rowsByDay = {}, state = {finishCalls: 0, daysAtFinish: null};
      const status = await window.databaseViewer.checkCalendar(
        (day, json) => { days.push(day); rowsByDay[day] = JSON.parse(json); },
        () => {
          state.finishCalls++; state.daysAtFinish = days.length;
          if (finishValue instanceof Error) throw finishValue;
          return JSON.stringify(finishValue);
        });
      return {status, days, rowsByDay, ...state};
    };
  });
  const run = (value = {status: 'match', cells: 4, mismatched: 0, examples: []}) => page.evaluate(v => window.__run(v), value);
  // キャッシュが無ければ、何も渡さず・finishも呼ばない。
  await page.evaluate(async ({url, body}) => {
    localStorage.setItem('database-viewer-remote', url);
    const kv = await window.__open('database-viewer', 1, ['kv']);
    await new Promise((res, rej) => { const tx = kv.transaction('kv', 'readwrite'); tx.objectStore('kv').put(body, 'data'); tx.oncomplete = res; tx.onerror = () => rej(tx.error); }); kv.close();
  }, {url, body});
  let r = await run();
  assert.equal(r.status, 'no-cache'); assert.deepEqual(r.days, []); assert.equal(r.finishCalls, 0);
  assert.equal((await page.evaluate(() => window.__diag())).calendar.status, 'no-cache');
  // 端末の日別キャッシュ：3日（11/07は記録の無い日）。
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
  await seed({'2026-11-07': '', '2026-11-08': JSON.stringify(rows('2026-11-08', 1)), '2026-11-09': JSON.stringify(rows('2026-11-09', 2))});
  const before = await page.evaluate(() => window.__all());
  r = await run();
  assert.equal(r.status, 'match');
  assert.deepEqual(r.days, ['2026-11-07', '2026-11-08', '2026-11-09'], '日別キャッシュを日の順に1日ずつ渡す');
  assert.equal(r.finishCalls, 1); assert.equal(r.daysAtFinish, 3, '全日を渡し終えてから finish を呼ぶ');
  assert.deepEqual(r.rowsByDay['2026-11-07'], [], '記録の無い日は空の一覧');
  assert.equal(r.rowsByDay['2026-11-08'].length, 3);
  assert.ok(r.rowsByDay['2026-11-08'].every(x => x.graph_measurement && !('preview_image' in x.graph_measurement)), '表示前と同じ整え（画像の項目を外す）を掛ける');
  assert.equal(r.rowsByDay['2026-11-09'][0].games, 2000, 'キャッシュの中身をそのまま渡す');
  assert.deepEqual(await page.evaluate(() => window.__all()), before, '照合は本体・日別キャッシュを変えない');
  let calendar = (await page.evaluate(() => window.__diag())).calendar;
  assert.deepEqual({status: calendar.status, days: calendar.days, records: calendar.records, cells: calendar.cells, mismatched: calendar.mismatched},
    {status: 'match', days: 3, records: 6, cells: 4, mismatched: 0});
  // 一致しない結果（Dart が出した例）をそのまま控え、画面の行に出す。
  const example = {store: 'saiwaichou', day: '2026-11-09', old: '差枚200・分かる1/1台・要確認1・勝ち1/1', next: 'マス無し'};
  r = await run({status: 'mismatch', cells: 4, mismatched: 1, examples: [example]});
  assert.equal(r.status, 'mismatch');
  calendar = (await page.evaluate(() => window.__diag())).calendar;
  assert.deepEqual(calendar.examples, [example]);
  const lines = await page.evaluate(async () => JSON.parse(await window.databaseViewer.storageReport()));
  assert.ok(lines.some(l => l.startsWith('カレンダーの日別計算：一致しないマス 1件（3日・4マス。例：saiwaichou 11/09 今の計算差枚200・分かる1/1台・要確認1・勝ち1/1・日別マス無し）')), lines.join('\n'));
  // 受け取り側が失敗しても、結果は「照合できませんでした」として控え、区切りは終える。
  r = await run(new Error('日別の計算に失敗'));
  assert.equal(r.status, 'error');
  let diag = await page.evaluate(() => window.__diag());
  assert.equal(diag.calendar.status, 'error'); assert.match(diag.calendar.message, /日別の計算に失敗/);
  assert.equal(diag.running, null, '失敗しても区切りは終わる');
  // 途中でページが終わっていたら（次に開いたとき calendar_halt）、24時間はこの照合だけをしない。結果も変えない。B0の照合は止めない。
  await page.evaluate(() => {
    const log = window.__diag(); log.calendar_halt = {at: new Date().toISOString()};
    localStorage.setItem('database-viewer-diag', JSON.stringify(log));
  });
  r = await run();
  assert.equal(r.status, null); assert.deepEqual(r.days, []); assert.equal(r.finishCalls, 0);
  assert.equal((await page.evaluate(() => window.__diag())).calendar.status, 'error');
  assert.notEqual(await page.evaluate(() => window.databaseViewer.checkDayCache()), null, 'B0の照合は止まらない');
  // P’s CUBEを表示している端末では動かない。
  await page.evaluate(async () => {
    const log = window.__diag(); delete log.calendar_halt; localStorage.setItem('database-viewer-diag', JSON.stringify(log));
    const kv = await window.__open('database-viewer', 1, ['kv']);
    await new Promise((res, rej) => { const tx = kv.transaction('kv', 'readwrite'); tx.objectStore('kv').put('pscube', 'active_source'); tx.oncomplete = res; tx.onerror = () => rej(tx.error); }); kv.close();
  });
  r = await run();
  assert.equal(r.status, null); assert.deepEqual(r.days, []); assert.equal(r.finishCalls, 0);
  assert.equal(await page.evaluate(() => window.databaseViewer.checkScores(() => {}, () => '{}')), null, 'B2の照合もP’s CUBEでは動かない');
  // B2の照合：同じ形で1日ずつ渡し、結果を別の項目に控える。止めている間（scores_halt）はB2だけ止まる。
  await page.evaluate(async () => {
    const kv = await window.__open('database-viewer', 1, ['kv']);
    await new Promise((res, rej) => { const tx = kv.transaction('kv', 'readwrite'); tx.objectStore('kv').put('meruhen', 'active_source'); tx.oncomplete = res; tx.onerror = () => rej(tx.error); }); kv.close();
  });
  const scores = await page.evaluate(async () => {
    const days = [];
    const status = await window.databaseViewer.checkScores((day, json) => days.push(day), () => JSON.stringify({status: 'match', racks: 6, mismatched: 0, examples: []}));
    return {status, days, diag: window.__diag().scores};
  });
  assert.equal(scores.status, 'match');
  assert.deepEqual(scores.days, ['2026-11-07', '2026-11-08', '2026-11-09']);
  assert.deepEqual({status: scores.diag.status, days: scores.diag.days, racks: scores.diag.racks}, {status: 'match', days: 3, racks: 6});
  await page.evaluate(() => { const log = window.__diag(); log.scores_halt = {at: new Date().toISOString()}; localStorage.setItem('database-viewer-diag', JSON.stringify(log)); });
  assert.equal(await page.evaluate(() => window.databaseViewer.checkScores(() => {}, () => '{}')), null, 'B2を止めている間はB2だけ動かない');
  assert.notEqual(await page.evaluate(() => window.databaseViewer.checkCalendar(() => {}, () => JSON.stringify({status: 'match', cells: 0, mismatched: 0, examples: []}))), null, 'B1は止まらない');
  await context.close();
}
await browser.close(); server.close();
console.log('PASS: 段階B1のカレンダー照合（更新のあとに一致・1日ずつ渡す・読むだけ・違いを出す・エラー・キャッシュ無し・止めている間・P’s CUBE）');
