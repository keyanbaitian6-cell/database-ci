// 共有カレンダーは、日別の部品から組み立てた内容の日がすべて端末の日別キャッシュにあれば、端末の全履歴をまとめて
// 読み直さない（2026-11-22、Codexの点検 #10・Gemini H-5。以前は rememberViewerHistory が端末の全日の部品を1回の
// 読み出しで集め、2店分の内容と同時にメモリに載っていた）。読み込み・表示・オフラインで開き直したときの内容は変えない。
// 偽のGoogleは、本物の同期スクリプトの部品の作り方（partsPublisher の vpPublish・vpGet）で返事を作る。
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import vm from 'node:vm';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {partsPublisher} from './build_viewer_parts.mjs';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(process.env.SHARE_WEB_ROOT || fileURLToPath(new URL('../../share_viewer', import.meta.url)));

const plain = x => JSON.parse(JSON.stringify(x));
const iterator = values => { let i = 0; return {hasNext: () => i < values.length, next: () => values[i++]}; };
function drive() {
  const files = []; let time = Date.now(), serial = 0;
  const folder = {getFilesByName: name => iterator(files.filter(f => f.name === name && !f.trashed)), getFiles: () => iterator(files)};
  const add = (name, text) => {
    const f = {name, text, id: String(++serial), time: ++time, trashed: false,
      getId: () => f.id, getName: () => f.name, getLastUpdated: () => new Date(f.time), getSize: () => Buffer.byteLength(f.text),
      isTrashed: () => f.trashed, setTrashed: v => { f.trashed = v; }, getBlob: () => ({getDataAsString: () => f.text})};
    files.push(f); return f;
  };
  const write = (_, f, name, text) => { if (!f) return add(name, text); f.text = text; f.time = ++time; return f; };
  const context = vm.createContext({console, Utilities: {DigestAlgorithm: {SHA_256: 'sha256'}, Charset: {UTF_8: 'utf8'},
    computeDigest: (_, text) => [...createHash('sha256').update(text).digest()], newBlob: text => ({getBytes: () => Buffer.from(text)})},
    DriveApp: {getFilesByName: name => folder.getFilesByName(name), getFileById: id => files.find(f => f.id === id)},
    ContentService: {MimeType: {JSON: 'json'}, createTextOutput: text => ({text, setMimeType() { return this; }})}});
  vm.runInContext(partsPublisher(), context);
  const base = add('database-viewer.json', '{}');
  context.vpPublish(folder, base, 'meruhen', {format: 'database-backup', version: 1, source: 'pc-viewer',
    exported_at: new Date(++time).toISOString(), records: [
      {store: 'saiwaichou', day: '2026-11-09', machine: '試験', rack: 1, games: 3000, bb: 20, rb: 10, jo_net: 100},
      {store: 'saiwaichou', day: '2026-11-10', machine: '試験', rack: 1, games: 3200, bb: 22, rb: 11, jo_net: 300},
      {store: 'saiwaichou', day: '2026-11-10', machine: '試験', rack: 2, games: 2800, bb: 15, rb: 9, jo_net: -200}]}, write);
  return url => plain(context.vpGet(base, 'meruhen', Object.fromEntries(new URL(url).searchParams)));
}
const read = drive();

const server = http.createServer(async (req, res) => {
  try {
    const name = new URL(req.url, 'http://x').pathname;
    const local = path.resolve(root, '.' + (name === '/' ? '/index.html' : name));
    if (!local.startsWith(root + path.sep)) { res.writeHead(403).end(); return; }
    res.setHeader('content-type', local.endsWith('.mjs') ? 'text/javascript' : local.endsWith('.json') ? 'application/json' : 'text/html;charset=utf-8');
    res.end(await fs.readFile(local));
  } catch { res.writeHead(404).end(); }
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
try {
  const context = await browser.newContext({viewport: {width: 393, height: 852}, serviceWorkers: 'block'});
  await context.route('https://script.google.com/**', route => {
    const url = new URL(route.request().url()), file = url.searchParams.get('file');
    // メルヘンだけ部品の形で返す。P-STATION・イベントなどは「無い」と返す（共有カレンダーは一部の失敗として続ける）。
    const body = file ? {error: 'この試験では返しません。'} : read(url.href);
    return route.fulfill({json: body, headers: {'access-control-allow-origin': '*'}});
  });
  await context.route('**/character_birthdays.json*', r => r.fulfill({json: {entries: []}}));
  // 端末の日別キャッシュを「全日まとめて読む」読み出し（3つの保存先をまとめて読む読み取り専用の取引）を数える。
  await context.addInitScript(() => {
    window.__bulkReads = 0;
    const original = IDBDatabase.prototype.transaction;
    IDBDatabase.prototype.transaction = function (stores, mode) {
      if (this.name === 'database-viewer-parts-v1' && Array.isArray(stores) && stores.includes('history-days') && mode !== 'readwrite') window.__bulkReads++;
      return original.call(this, stores, mode);
    };
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  const open = async () => {
    await page.goto(`http://127.0.0.1:${server.address().port}/#s=AKfycbTEST${'x'.repeat(40)}`);
    await page.waitForSelector('.grid', {timeout: 30000});
    await page.waitForFunction(() => !document.querySelector('#reload')?.disabled, null, {timeout: 30000});
  };
  // 1回目（端末に何も無い）：部品を読んで保存する読み出しの1回だけ。保存したあとに全履歴を読み直さない。
  await open();
  assert.equal(await page.evaluate(() => window.__bulkReads), 1, '初回：部品を読む前の1回だけ');
  // 2回目（端末に全日ある）：同じく1回だけ。
  await open();
  assert.equal(await page.evaluate(() => window.__bulkReads), 1, '2回目：保存済みでも読み直さない');
  // オフラインで開き直しても、端末の日別キャッシュから同じ日が出る（保存は前と同じに済んでいる）。
  const days = await page.evaluate(async () => {
    const {readViewerHistory} = await import('/viewer_parts.mjs');
    const doc = await readViewerHistory(`https://script.google.com/macros/s/AKfycbTEST${'x'.repeat(40)}/exec`, 'meruhen');
    return {days: doc.history_days, records: doc.records.length};
  });
  assert.deepEqual(days, {days: ['2026-11-09', '2026-11-10'], records: 3});
  assert.deepEqual(errors, []);
  await context.close();
  console.log('PASS: the share calendar does not re-read the whole saved history after loading day parts');
} finally { await browser.close(); await new Promise(r => server.close(r)); }
