// Build viewer_main.dart and stage_viewer.py before this browser test.
// メルヘン版の閲覧ページの「Googleドライブの更新」で、画面（Dart）へ渡す内容と、端末の日別キャッシュに残る内容が、
// メモリの山を下げる変更（2026-11-18：部品から組み立てた内容を文字列に直さない・旧本文を丸ごと解析しない・同じ部品を
// 何度も計算・解析しない）の前と同じであることを確かめる。期待値は、試験の中で、固定の入力から独立に作る
// （変更前のビルドでも合格する）。実ブラウザ・実IndexedDB・偽Google。
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = process.env.VIEWER_WEB_ROOT || fileURLToPath(new URL('../build/web/', import.meta.url));
const types = {'.js': 'text/javascript', '.mjs': 'text/javascript', '.html': 'text/html; charset=utf-8', '.json': 'application/json'};
const server = http.createServer(async (req, res) => {
  const name = decodeURIComponent(new URL(req.url, 'http://x').pathname).replace(/^\/database-viewer\//, '');
  const file = path.resolve(root, name || 'index.html');
  if (!file.startsWith(path.resolve(root))) { res.writeHead(403).end(); return; }
  try { res.setHeader('content-type', types[path.extname(file)] || 'application/octet-stream'); res.end(await fs.readFile(file)); }
  catch { res.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const id = 'AKfycbEQUIV' + 'x'.repeat(40), url = `https://script.google.com/macros/s/${id}/exec`;
const hash = text => createHash('sha256').update(text).digest('hex');
const OLD_EXPORT = '2026-11-10T00:00:00+09:00', NEW_EXPORT = '2026-11-11T00:00:00+09:00';

// 1日分の行。graph_measurement の画像の項目は、画面へ渡す前に取り除かれる（lighten）。
const rows = (day, generation, count = 3) => Array.from({length: count}, (_, i) => ({
  store: i % 2 ? 'saiwaichou' : 'nagamachiminami', day, machine: i % 2 ? 'ハナハナ' : 'ジャグラー', rack: 100 + i,
  games: 1000 * generation + i, bb: 3 + i, rb: 1, my: -100 * generation,
  graph_measurement: {baseline_y: 100, peak_y: 10 + i, curve_index: i, preview_image: 'IMG' + day + i, preview_stored: true, curve_stored: true},
}));
const light = list => list.map(r => { const g = {...r.graph_measurement}; delete g.preview_image; delete g.preview_stored; delete g.curve_stored; return {...r, graph_measurement: g}; });
const header = exported => ({format: 'database-backup', version: 1, source: 'pc-viewer', exported_at: exported, date_events: [], machines: []});
const part = list => { const text = JSON.stringify(list); return {text, hash: hash(text), bytes: Buffer.byteLength(text)}; };
// 日別の部品（1日1部品）と、更新の一覧（version 2）。
function manifest(days, exported) {
  const parts = days.map(({day, list}) => { const p = part(list); return {hash: p.hash, day, count: list.length, bytes: p.bytes, text: p.text}; });
  const listing = parts.map(({hash, day, count, bytes}) => ({hash, day, count, bytes}));
  return {manifest: {format: 'database-viewer-parts', version: 2, site: 'meruhen', revision: hash(JSON.stringify(listing)),
    header: header(exported), parts: listing, days: days.map(d => d.day), count: listing.reduce((a, p) => a + p.count, 0)}, texts: Object.fromEntries(parts.map(p => [p.hash, p.text]))};
}

async function scenario(name, {cachedDays, bodyRows, remoteDays}, check) {
  const context = await browser.newContext({viewport: {width: 393, height: 850}});
  const remote = manifest(remoteDays.map(day => ({day, list: rows(day, 2)})), NEW_EXPORT);
  const requests = [];
  await context.route('https://script.google.com/**', route => {
    const u = new URL(route.request().url()), headers = {'access-control-allow-origin': '*'};
    const json = body => route.fulfill({status: 200, contentType: 'application/json', headers, body: JSON.stringify(body)});
    requests.push(u.search);
    if (u.searchParams.has('check')) return json({format: 'drive-check', version: 'parts:' + remote.manifest.revision, parts: remote.manifest});
    if (u.searchParams.has('parts')) return json({format: 'database-viewer-parts', revision: remote.manifest.revision,
      parts: u.searchParams.get('parts').split(',').map(h => ({hash: h, text: remote.texts[h]}))});
    throw new Error('想定外の通信：' + u);
  });
  const page = await context.newPage(), errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.route('**/flutter_bootstrap.js', route => route.fulfill({contentType: 'text/javascript', body: ''}));
  await page.goto(`${origin}/database-viewer/index.html`);
  await page.waitForFunction(() => window.databaseViewer && typeof window.databaseViewer.fromRemote === 'function');
  // 端末の前回の状態：旧本文（保存した全文）と、日別キャッシュ。
  const cached = cachedDays.map(({day, list}) => ({day, ...part(list)}));
  await page.evaluate(async ({url, body, cached}) => {
    const open = (n, v, stores) => new Promise((resolve, reject) => {
      const q = indexedDB.open(n, v); q.onupgradeneeded = () => { for (const s of stores) if (!q.result.objectStoreNames.contains(s)) q.result.createObjectStore(s); };
      q.onsuccess = () => resolve(q.result); q.onerror = () => reject(q.error);
    });
    const done = tx => new Promise((resolve, reject) => { tx.oncomplete = resolve; tx.onerror = tx.onabort = () => reject(tx.error); });
    const kv = await open('database-viewer', 1, ['kv']); let tx = kv.transaction('kv', 'readwrite');
    if (body) tx.objectStore('kv').put(body, 'data'); await done(tx); kv.close();
    if (cached.length) {
      const key = url + '|meruhen', db = await open('database-viewer-parts-v1', 2, ['snapshots', 'history-heads', 'history-days']);
      tx = db.transaction(['history-heads', 'history-days'], 'readwrite');
      for (const p of cached) tx.objectStore('history-days').put({parts: {[p.hash]: p.text}}, key + '|' + p.day);
      tx.objectStore('history-heads').put({header: {format: 'database-backup', version: 1, source: 'pc-viewer', exported_at: '2026-11-09T00:00:00+09:00', date_events: [], machines: [], parts_at: '2026-11-09T00:00:00+09:00'}, days: cached.map(p => p.day).sort(), revision: 1}, key);
      await done(tx); db.close();
    }
  }, {url, body: bodyRows ? JSON.stringify({header: header(OLD_EXPORT), records: bodyRows, candidates: [], date_events: [], history_days: [...new Set(bodyRows.map(r => r.day))].sort(), file: 'x', loaded_at: OLD_EXPORT}) : null, cached: cached.map(p => ({day: p.day, text: p.text, hash: p.hash}))});
  const result = JSON.parse(await page.evaluate(u => window.databaseViewer.fromRemote(u, null), url));
  const state = await page.evaluate(async u => {
    const db = await new Promise((resolve, reject) => { const q = indexedDB.open('database-viewer-parts-v1', 2); q.onsuccess = () => resolve(q.result); q.onerror = () => reject(q.error); });
    const read = (store, range) => new Promise((resolve, reject) => { const r = db.transaction(store).objectStore(store).getAllKeys(); r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error); });
    const days = (await read('history-days')).map(String).sort(), head = await new Promise((resolve, reject) => { const r = db.transaction('history-heads').objectStore('history-heads').get(u + '|meruhen'); r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error); });
    db.close(); return {days, headDays: head?.days ?? null};
  }, url);
  await check({result, state, requests, remote});
  assert.deepEqual(errors, [], `[${name}] pageerror`);
  await context.close();
  console.log('  OK ' + name);
}

const browser = await chromium.launch({executablePath: process.env.CHROMIUM_PATH || undefined, headless: true, args: ['--no-sandbox']});
try {
  // 期待する画面向けの内容（変更前と同じ形・同じ項目順・同じ中身）。days は昇順。
  const expected = (days, byDay) => {
    const records = days.flatMap(day => light(byDay[day]));
    const head = {...header(NEW_EXPORT), history: true, history_days: days};
    return {header: head, records, candidates: [], date_events: [], history_days: days};
  };
  const strip = result => { const copy = {...result}; delete copy.file; delete copy.loaded_at; return copy; };
  const D = ['2026-11-05', '2026-11-06', '2026-11-07', '2026-11-08'];

  // 1) 旧本文にだけある日（D[0]）は、更新のときに日別キャッシュへ引き継がれ、画面向けの内容にも残る。
  await scenario('旧本文にだけある日を引き継ぐ', {
    cachedDays: [{day: D[1], list: rows(D[1], 1)}], remoteDays: [D[2], D[3]],
    bodyRows: [...rows(D[0], 1), ...rows(D[1], 1)],
  }, ({result, state}) => {
    assert.equal(JSON.stringify(strip(result)), JSON.stringify(expected(D, {[D[0]]: rows(D[0], 1), [D[1]]: rows(D[1], 1), [D[2]]: rows(D[2], 2), [D[3]]: rows(D[3], 2)})));
    assert.deepEqual(state.days, D.map(d => `${url}|meruhen|${d}`).sort(), '旧本文の日が日別キャッシュに入る');
    assert.deepEqual(state.headDays, D);
  });

  // 2) 旧本文の日がすべて日別キャッシュにある：キャッシュの中身が使われ、キャッシュは増えない。旧本文の違う中身で上書きしない。
  await scenario('旧本文の日がすべてキャッシュにある', {
    cachedDays: [{day: D[0], list: rows(D[0], 1)}, {day: D[1], list: rows(D[1], 1)}], remoteDays: [D[2], D[3]],
    bodyRows: [...rows(D[0], 9), ...rows(D[1], 9)], // キャッシュと違う中身（旧本文の方が違っても、キャッシュが先）
  }, ({result, state}) => {
    assert.equal(JSON.stringify(strip(result)), JSON.stringify(expected(D, {[D[0]]: rows(D[0], 1), [D[1]]: rows(D[1], 1), [D[2]]: rows(D[2], 2), [D[3]]: rows(D[3], 2)})));
    assert.deepEqual(state.days, D.map(d => `${url}|meruhen|${d}`).sort());
  });

  // 3) 旧本文もキャッシュも無い（初めて開く端末）：Googleの内容だけ。
  await scenario('初めて開く端末', {cachedDays: [], remoteDays: [D[2], D[3]], bodyRows: null}, ({result, state, requests}) => {
    assert.equal(JSON.stringify(strip(result)), JSON.stringify(expected([D[2], D[3]], {[D[2]]: rows(D[2], 2), [D[3]]: rows(D[3], 2)})));
    assert.deepEqual(state.headDays, [D[2], D[3]]);
    assert.ok(requests.some(q => q.includes('parts=')));
  });

  // 4) 旧本文があり、日別キャッシュが無い（初めて部品分けの読み込みをする端末）：旧本文の全日が引き継がれる。
  await scenario('旧本文だけある（キャッシュなし）', {
    cachedDays: [], remoteDays: [D[3]], bodyRows: [...rows(D[0], 1), ...rows(D[1], 1), ...rows(D[2], 1)],
  }, ({result, state}) => {
    assert.equal(JSON.stringify(strip(result)), JSON.stringify(expected(D, {[D[0]]: rows(D[0], 1), [D[1]]: rows(D[1], 1), [D[2]]: rows(D[2], 1), [D[3]]: rows(D[3], 2)})));
    assert.deepEqual(state.headDays, D);
  });
  console.log('PASS: 更新で画面へ渡す内容と日別キャッシュが、期待どおり（旧本文の引き継ぎ・キャッシュ優先・初回・画像項目の除去）');
} finally {
  await browser.close();
  await new Promise(resolve => server.close(resolve));
}
