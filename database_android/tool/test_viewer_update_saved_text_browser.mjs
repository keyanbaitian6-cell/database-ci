// Build viewer_main.dart and stage_viewer.py before this browser test.
// Googleドライブの更新のあと、端末に保存される本文（画面＝Flutterまで含む実ビルド）が、メモリの山を下げる変更
// （2026-11-18）の前のビルドで保存されていた本文と、一字一句同じであることを確かめる。期待する文字列（GOLDEN）は、
// 変更前のビルドで同じ手順を流して得たもの。covered＝端末の本文の日がすべてDriveにある（要約で合わせる経路）、
// older＝端末の本文にDriveより古い日がある（本文を読んで合わせる今までの経路）。端末のイベント・🌈の印も引き継ぐ。
import assert from 'node:assert/strict';
const GOLDEN = {
 "covered": {
  "text": "{\"header\":{\"format\":\"database-backup\",\"version\":1,\"source\":\"pc-viewer\",\"exported_at\":\"2026-10-12T00:00:00+09:00\",\"date_events\":[{\"store\":\"nagamachiminami\",\"day\":\"2026-10-11\",\"name\":\"Driveのイベント\",\"updated_at\":\"2026-10-11T10:00:00+09:00\"}]},\"records\":[{\"store\":\"nagamachiminami\",\"day\":\"2026-10-10\",\"machine\":\"化物語\",\"rack\":1085,\"games\":4000,\"bb\":10,\"rb\":5,\"max_hold\":1000,\"graph_measurement\":{\"baseline_y\":100,\"peak_y\":20,\"trough_y\":100,\"end_y\":40,\"curve_index\":1085}},{\"store\":\"nagamachiminami\",\"day\":\"2026-10-10\",\"machine\":\"化物語\",\"rack\":1086,\"games\":3000,\"bb\":10,\"rb\":5,\"max_hold\":1000,\"graph_measurement\":{\"baseline_y\":100,\"peak_y\":20,\"trough_y\":100,\"end_y\":40,\"curve_index\":1086}},{\"store\":\"nagamachiminami\",\"day\":\"2026-10-11\",\"machine\":\"化物語\",\"rack\":1085,\"games\":4000,\"bb\":10,\"rb\":5,\"max_hold\":1000,\"graph_measurement\":{\"baseline_y\":100,\"peak_y\":20,\"trough_y\":100,\"end_y\":40,\"curve_index\":1085}},{\"store\":\"nagamachiminami\",\"day\":\"2026-10-11\",\"machine\":\"化物語\",\"rack\":1086,\"games\":3000,\"bb\":10,\"rb\":5,\"max_hold\":1000,\"graph_measurement\":{\"baseline_y\":100,\"peak_y\":20,\"trough_y\":100,\"end_y\":40,\"curve_index\":1086}}],\"candidates\":[],\"date_events\":[{\"store\":\"nagamachiminami\",\"day\":\"2026-10-10\",\"name\":\"端末のイベント\",\"updated_at\":\"2026-10-11T08:00:00+09:00\"},{\"store\":\"nagamachiminami\",\"day\":\"2026-10-11\",\"name\":\"Driveのイベント\",\"updated_at\":\"2026-10-11T10:00:00+09:00\"}],\"file\":\"Googleドライブ（自動）\",\"rainbow_marks\":[{\"store\":\"nagamachiminami\",\"day\":\"2026-10-10\",\"rack\":1085,\"on\":true,\"updated_at\":\"2026-10-11T09:00:00+09:00\"}]}"
 },
 "older": {
  "text": "{\"header\":{\"format\":\"database-backup\",\"version\":1,\"source\":\"pc-viewer\",\"exported_at\":\"2026-10-12T00:00:00+09:00\",\"date_events\":[{\"store\":\"nagamachiminami\",\"day\":\"2026-10-11\",\"name\":\"Driveのイベント\",\"updated_at\":\"2026-10-11T10:00:00+09:00\"}]},\"records\":[{\"store\":\"nagamachiminami\",\"day\":\"2026-10-10\",\"machine\":\"化物語\",\"rack\":1085,\"games\":4000,\"bb\":10,\"rb\":5,\"max_hold\":1000,\"graph_measurement\":{\"baseline_y\":100,\"peak_y\":20,\"trough_y\":100,\"end_y\":40,\"curve_index\":1085}},{\"store\":\"nagamachiminami\",\"day\":\"2026-10-10\",\"machine\":\"化物語\",\"rack\":1086,\"games\":3000,\"bb\":10,\"rb\":5,\"max_hold\":1000,\"graph_measurement\":{\"baseline_y\":100,\"peak_y\":20,\"trough_y\":100,\"end_y\":40,\"curve_index\":1086}},{\"store\":\"nagamachiminami\",\"day\":\"2026-10-11\",\"machine\":\"化物語\",\"rack\":1085,\"games\":4000,\"bb\":10,\"rb\":5,\"max_hold\":1000,\"graph_measurement\":{\"baseline_y\":100,\"peak_y\":20,\"trough_y\":100,\"end_y\":40,\"curve_index\":1085}},{\"store\":\"nagamachiminami\",\"day\":\"2026-10-11\",\"machine\":\"化物語\",\"rack\":1086,\"games\":3000,\"bb\":10,\"rb\":5,\"max_hold\":1000,\"graph_measurement\":{\"baseline_y\":100,\"peak_y\":20,\"trough_y\":100,\"end_y\":40,\"curve_index\":1086}},{\"store\":\"nagamachiminami\",\"day\":\"2026-10-01\",\"machine\":\"化物語\",\"rack\":1085,\"games\":3000,\"bb\":10,\"rb\":5,\"max_hold\":1000,\"graph_measurement\":{\"baseline_y\":100,\"peak_y\":20,\"trough_y\":100,\"end_y\":40,\"curve_index\":1085,\"preview_image\":\"X\"}}],\"candidates\":[],\"date_events\":[{\"store\":\"nagamachiminami\",\"day\":\"2026-10-10\",\"name\":\"端末のイベント\",\"updated_at\":\"2026-10-11T08:00:00+09:00\"},{\"store\":\"nagamachiminami\",\"day\":\"2026-10-11\",\"name\":\"Driveのイベント\",\"updated_at\":\"2026-10-11T10:00:00+09:00\"}],\"file\":\"Googleドライブ（自動）\",\"kept_older\":1,\"rainbow_marks\":[{\"store\":\"nagamachiminami\",\"day\":\"2026-10-10\",\"rack\":1085,\"on\":true,\"updated_at\":\"2026-10-11T09:00:00+09:00\"}]}"
 }
};
import http from 'node:http'; import fs from 'node:fs/promises'; import path from 'node:path'; import {fileURLToPath} from 'node:url';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const build = process.env.VIEWER_WEB_ROOT || fileURLToPath(new URL('../build/web/', import.meta.url));
const types = {'.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json', '.wasm': 'application/wasm', '.html': 'text/html', '.css': 'text/css', '.png': 'image/png'};
const server = http.createServer(async (req, res) => {
  let url = new URL(req.url, 'http://x').pathname;
  if (url === '/setup') { res.setHeader('content-type', 'text/html'); res.end('<!doctype html><body>s</body>'); return; }
  url = decodeURIComponent(url).replace(/^\/database-viewer\//, '');
  const f = path.resolve(build, url || 'index.html');
  try { res.setHeader('content-type', types[path.extname(f)] || 'application/octet-stream'); res.end(await fs.readFile(f)); } catch { res.writeHead(404).end(); }
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const origin = 'http://127.0.0.1:' + server.address().port, SCRIPT = 'https://script.google.com/macros/s/CROSS/exec';
const row = (day, rack, games) => ({store: 'nagamachiminami', day, machine: '化物語', rack, games, bb: 10, rb: 5, max_hold: 1000, graph_measurement: {baseline_y: 100, peak_y: 20, trough_y: 100, end_y: 40, curve_index: rack, preview_image: 'X'}});
const ev = {store: 'nagamachiminami', day: '2026-10-10', name: '端末のイベント', updated_at: '2026-10-11T08:00:00+09:00'};
const mark = {store: 'nagamachiminami', day: '2026-10-10', rack: 1085, on: true, updated_at: '2026-10-11T09:00:00+09:00'};
const cases = {
  covered: {days: ['2026-10-10', '2026-10-11']},
  older: {days: ['2026-10-01', '2026-10-10']},
};
const results = {};
const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
for (const [name, c] of Object.entries(cases)) {
  const context = await browser.newContext({viewport: {width: 393, height: 852}});
  const fresh = {format: 'database-backup', version: 1, source: 'pc-viewer', exported_at: '2026-10-12T00:00:00+09:00', date_events: [{store: 'nagamachiminami', day: '2026-10-11', name: 'Driveのイベント', updated_at: '2026-10-11T10:00:00+09:00'}],
    records: ['2026-10-10', '2026-10-11'].flatMap(d => [row(d, 1085, 4000), row(d, 1086, 3000)])};
  const stored = {header: {format: 'database-backup', version: 1, source: 'pc', exported_at: '2026-10-11T23:00:00+09:00'}, records: c.days.flatMap(d => [row(d, 1085, 3000)]), date_events: [ev], rainbow_marks: [mark]};
  await context.route('https://script.google.com/**', route => {
    const u = route.request().url(), headers = {'access-control-allow-origin': '*'};
    if (u.includes('check=1')) return route.fulfill({status: 200, contentType: 'application/json', headers, body: JSON.stringify({format: 'drive-check', version: 'v2'})});
    if (u.includes('file=')) return route.fulfill({status: 200, contentType: 'application/json', headers, body: JSON.stringify({error: 'x'})});
    return route.fulfill({status: 200, contentType: 'application/json', headers, body: JSON.stringify(fresh)});
  });
  const page = await context.newPage();
  await page.goto(origin + '/setup');
  await page.evaluate(async ({data, s}) => {
    localStorage.setItem('database-viewer-remote', s);
    const db = await new Promise((res, rej) => { const q = indexedDB.open('database-viewer', 1); q.onupgradeneeded = () => q.result.createObjectStore('kv'); q.onsuccess = () => res(q.result); q.onerror = () => rej(q.error); });
    await new Promise((res, rej) => { const tx = db.transaction('kv', 'readwrite'); tx.objectStore('kv').put(JSON.stringify(data), 'data'); tx.oncomplete = res; tx.onerror = () => rej(tx.error); }); db.close();
  }, {data: stored, s: SCRIPT});
  await page.goto(origin + '/database-viewer/');
  await page.waitForSelector('flt-glass-pane', {state: 'attached', timeout: 60000});
  for (let i = 0; i < 120; i++) {
    await page.waitForTimeout(250);
    const done = await page.evaluate(() => { try { const l = JSON.parse(localStorage.getItem('database-viewer-diag')); return !!l?.phases?.drive?.count && !l.running; } catch { return false; } });
    if (done) break;
  }
  await page.waitForTimeout(1500);
  results[name] = await page.evaluate(async () => {
    const db = await new Promise((res, rej) => { const q = indexedDB.open('database-viewer', 1); q.onsuccess = () => res(q.result); q.onerror = () => rej(q.error); });
    const get = k => new Promise((res, rej) => { const r = db.transaction('kv').objectStore('kv').get(k); r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });
    const data = await get('data'), marks = await get('rainbow_marks'); db.close();
    const doc = JSON.parse(data); delete doc.loaded_at;
    return {text: JSON.stringify(doc), marks};
  });
  await context.close();
}
await browser.close(); server.close();
for (const [name, expected] of Object.entries(GOLDEN)) {
  assert.equal(results[name].text, expected.text, `[${name}] 保存された本文`);
  assert.equal(results[name].marks, expected.marks, `[${name}] 端末の🌈の印`);
}
console.log('PASS: 更新後に端末へ保存される本文が、変更前のビルドと同じ（要約で合わせる経路・本文を読んで合わせる経路）');
