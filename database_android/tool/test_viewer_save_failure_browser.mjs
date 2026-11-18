// Build viewer_main.dart and stage_viewer.py before this browser test.
// 2026-11-18：iPhoneで「端末に保存できませんでした」が出たが、原因の手がかりが残らなかった。閲覧ページの本体の保存
// （databaseViewer.save）が失敗したとき、その種類を診断に控え、元の失敗をそのまま返すこと（保存の動きは変えない）を確かめる。
// ・エラーの無い中断（iPhoneと同じ文言になる場合）：write・abort・決まった文言・大きさ・画面の表裏を控える。
// ・保存先が返したエラー：その名前を控える。保存先を開けない：open として控える。
// ・失敗しても、前に保存した本体は変わらない。成功した保存は回数を増やさない。
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = process.env.VIEWER_WEB_ROOT || fileURLToPath(new URL('../build/web/', import.meta.url));
const types = {'.js': 'text/javascript', '.mjs': 'text/javascript', '.html': 'text/html; charset=utf-8', '.json': 'application/json', '.wasm': 'application/wasm', '.css': 'text/css', '.png': 'image/png'};
const server = http.createServer(async (req, res) => {
  const name = decodeURIComponent(new URL(req.url, 'http://x').pathname).replace(/^\/database-viewer\//, '');
  const file = path.resolve(root, name || 'index.html');
  if (!file.startsWith(path.resolve(root))) { res.writeHead(403).end(); return; }
  try { res.setHeader('content-type', types[path.extname(file)] || 'application/octet-stream'); res.end(await fs.readFile(file)); }
  catch { res.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
const context = await browser.newContext();
const page = await context.newPage();
await page.route('**/flutter_bootstrap.js', route => route.fulfill({contentType: 'text/javascript', body: ''}));
await page.goto(`${origin}/database-viewer/index.html`);
await page.waitForFunction(() => window.databaseViewer && typeof window.databaseViewer.save === 'function');
await page.evaluate(() => {
  window.__stored = () => new Promise((resolve, reject) => {
    const q = indexedDB.open('database-viewer');
    q.onsuccess = () => { const db = q.result; const r = db.transaction('kv').objectStore('kv').get('data'); r.onsuccess = () => { db.close(); resolve(r.result ?? null); }; r.onerror = () => reject(r.error); };
    q.onerror = () => reject(q.error);
  });
  window.__diag = () => JSON.parse(localStorage.getItem('database-viewer-diag') || 'null');
  window.__try = async text => { try { await window.databaseViewer.save(text, true); return 'ok'; } catch (e) { return `${e?.name}|${e?.message}`; } };
});
const first = JSON.stringify({header: {format: 'database-backup'}, records: [{day: '2026-11-17'}]});
assert.equal(await page.evaluate(t => window.__try(t), first), 'ok');
assert.equal(await page.evaluate(() => window.__diag()?.save_fail ?? null), null, '成功した保存は控えない');

// 1. エラーの無い中断（保存先が理由を返さずに書き込みを取り消した）。
await page.evaluate(() => {
  const original = IDBDatabase.prototype.transaction;
  window.__restore = () => { IDBDatabase.prototype.transaction = original; };
  IDBDatabase.prototype.transaction = function (...args) {
    const tx = original.apply(this, args);
    if (args[1] === 'readwrite') Promise.resolve().then(() => tx.abort());
    return tx;
  };
});
const second = JSON.stringify({header: {format: 'database-backup'}, records: [{day: '2026-11-18'}]});
assert.equal(await page.evaluate(t => window.__try(t), second), 'Error|端末に保存できませんでした。', '元の失敗をそのまま返す');
let fail = await page.evaluate(() => window.__diag().save_fail);
assert.deepEqual({count: fail.count, stage: fail.stage, event: fail.event, name: fail.name, message: fail.message, chars: fail.chars, hidden: fail.hidden},
  {count: 1, stage: 'write', event: 'abort', name: 'Error', message: '端末に保存できませんでした。', chars: second.length, hidden: false});
assert.equal(await page.evaluate(() => window.__stored()), first, '失敗しても前の本体は変わらない');

// 2. 保存先が返したエラー（例：容量）。
await page.evaluate(() => {
  window.__restore();
  const original = IDBObjectStore.prototype.put;
  window.__restorePut = () => { IDBObjectStore.prototype.put = original; };
  IDBObjectStore.prototype.put = function () { throw new DOMException('quota', 'QuotaExceededError'); };
});
assert.equal(await page.evaluate(t => window.__try(t), second), 'QuotaExceededError|quota');
fail = await page.evaluate(() => window.__diag().save_fail);
assert.equal(fail.count, 2); assert.equal(fail.name, 'QuotaExceededError'); assert.equal(fail.stage, 'write');

// 3. 保存先を開けない。
await page.evaluate(() => {
  window.__restorePut();
  const original = IDBFactory.prototype.open;
  window.__restoreOpen = () => { IDBFactory.prototype.open = original; };
  IDBFactory.prototype.open = function () { throw new DOMException('closed', 'UnknownError'); };
});
assert.equal(await page.evaluate(t => window.__try(t), second), 'UnknownError|closed');
fail = await page.evaluate(() => window.__diag().save_fail);
assert.equal(fail.count, 3); assert.equal(fail.stage, 'open'); assert.equal(fail.name, 'UnknownError');

// 4. 戻せば保存でき、回数は増えない。診断の画面の行にも出る。
await page.evaluate(() => window.__restoreOpen());
assert.equal(await page.evaluate(t => window.__try(t), second), 'ok');
assert.equal(await page.evaluate(() => window.__stored()), second);
assert.equal((await page.evaluate(() => window.__diag().save_fail)).count, 3);
const lines = await page.evaluate(async () => JSON.parse(await window.databaseViewer.storageReport()));
assert.ok(lines.some(l => l.startsWith('端末への保存の失敗：3回（最後：') && l.includes('保存先を開けない・UnknownError')), lines.join(' | '));
await browser.close(); server.close();
console.log('PASS: 保存の失敗の手がかり（エラーの無い中断・保存先のエラー・開けない・前の本体は変わらない・成功は数えない）');
