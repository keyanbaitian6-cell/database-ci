// ビルドした閲覧ページ（build/web）の実物の index.html を実ブラウザで動かし、メルヘンのGoogleドライブ読み込みが
// 共通部品（drive_fetch.mjs）を実際に読み込めること、更新の目印が同じなら全文を読まないことを確かめる。
// 先に `flutter build web -t lib/viewer_main.dart --release --base-href /database-viewer/` が必要。Apps Scriptの返事は偽物。
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = fileURLToPath(new URL('../build/web/', import.meta.url));
const types = {'.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json', '.wasm': 'application/wasm'};
const server = http.createServer(async (req, res) => {
  const name = decodeURIComponent(new URL(req.url, 'http://x').pathname).replace(/^\/database-viewer\//, '');
  const file = path.resolve(root, name || 'index.html');
  if (!file.startsWith(root)) { res.writeHead(403).end(); return; }
  try { res.setHeader('content-type', types[path.extname(file)] || 'application/octet-stream'); res.end(await fs.readFile(file)); }
  catch { res.writeHead(404).end(); }
});
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
const SCRIPT = 'https://script.google.com/macros/s/AKfycb_TEST/exec';
const exportedAt = '2026-10-04T12:00:00+09:00';
const backup = JSON.stringify({format: 'database-backup', version: 1, source: 'pc-viewer', exported_at: exportedAt, date_events: [], records: [
  {store: 'nagamachiminami', day: '2026-10-04', machine: 'テスト機種', rack: 101, games: 5000, bb: 20, rb: 10},
]}, null, 0).replace('"records":[', '"records": [\n').replace(/\}\]\}$/, '}\n]}');
try {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const requests = [];
  let version = 'v1';
  await page.route('https://script.google.com/**', (route) => {
    const url = route.request().url();
    requests.push(url);
    const body = url.endsWith('?check=1') ? JSON.stringify({format: 'drive-check', version, name: 'database-viewer.json'}) : backup;
    return route.fulfill({status: 200, contentType: 'application/json', headers: {'access-control-allow-origin': '*'}, body});
  });
  await page.goto(`${origin}/database-viewer/index.html`, {waitUntil: 'domcontentloaded'});
  await page.waitForFunction(() => window.databaseViewer && typeof window.databaseViewer.fromRemote === 'function');
  const read = (known) => page.evaluate(([url, known]) => window.databaseViewer.fromRemote(url, known), [SCRIPT, known]);
  const first = JSON.parse(await read(null));
  assert.equal(first.records.length, 1);
  assert.equal(first.header.exported_at, exportedAt);
  assert.deepEqual(requests, [`${SCRIPT}?check=1`, SCRIPT]);
  requests.length = 0;
  assert.equal(await read(exportedAt), null);
  assert.deepEqual(requests, [`${SCRIPT}?check=1`], '目印も書き出し時刻も同じなら、全文は読まない');
  requests.length = 0;
  version = 'v2';
  assert.equal(await read(exportedAt), null, '目印が変わっても書き出し時刻が同じなら、反映はしない');
  assert.deepEqual(requests, [`${SCRIPT}?check=1`, SCRIPT]);
  requests.length = 0;
  assert.equal(await read(exportedAt), null);
  assert.deepEqual(requests, [`${SCRIPT}?check=1`], '目印を覚え直した');
  assert.deepEqual(errors, []);
  console.log('PASS: built index.html loads drive_fetch.mjs; version check skips the download when nothing changed');
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
