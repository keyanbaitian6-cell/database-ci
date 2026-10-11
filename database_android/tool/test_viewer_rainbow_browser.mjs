// Build viewer_main.dart and stage_viewer.py before this browser test.
// 閲覧ページ（iPhone）で🌈を付け外しする（2026-10-11、RAINBOW.md「iPhoneから付ける」）。台の画面の
// 「🌈 付ける」で端末に保存して表示に入り、Apps Script へ {file: 'rainbow', marks} を送る。開き直しても残り、
// ほかの端末の🌈（?file=rainbow）も表示に入る。Googleのスクリプトは偽物（page.route）で、外へは出ない。
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = process.env.VIEWER_WEB_ROOT || fileURLToPath(new URL('../build/web/', import.meta.url));
const prefix = '/database-viewer/';
const server = http.createServer(async (req, res) => {
  let url = new URL(req.url, 'http://localhost').pathname;
  if (url === '/setup') { res.setHeader('content-type', 'text/html'); res.end('<!doctype html><body>setup</body>'); return; }
  if (!url.startsWith(prefix)) { res.writeHead(404).end(); return; }
  url = url.slice(prefix.length);
  const local = path.resolve(root, (!url || url.endsWith('/')) ? url + 'index.html' : url);
  if (!local.startsWith(path.resolve(root) + path.sep)) { res.writeHead(403).end(); return; }
  try {
    const body = await fs.readFile(local), ext = path.extname(local);
    res.setHeader('content-type', ({'.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json',
      '.wasm': 'application/wasm', '.html': 'text/html', '.css': 'text/css', '.png': 'image/png'})[ext] || 'application/octet-stream');
    res.end(body);
  } catch { res.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const origin = 'http://127.0.0.1:' + server.address().port;
const script = 'https://script.google.com/macros/s/TEST_RAINBOW/exec';

const records = [];
for (const day of ['2026-10-09', '2026-10-10']) {
  for (let rack = 1085; rack < 1089; rack++) {
    records.push({store: 'nagamachiminami', day, machine: '化物語', rack, games: 3000, bb: 10, rb: 5, max_hold: 1000,
      graph_measurement: {baseline_y: 100, peak_y: 20, trough_y: 100, end_y: 40, curve: [[0, 100], [10, 20], [20, 40]]}});
  }
}
const meruhen = {header: {format: 'database-backup', version: 1, source: 'pc', exported_at: '2026-10-10T23:00:00+09:00'}, records};
// ほかの端末で 1086番台（10/10）に付けた🌈。
const shared = {rainbow: {format: 'database-rainbow', version: 1, marks: [
  {store: 'nagamachiminami', day: '2026-10-10', rack: 1086, on: true, updated_at: '2026-10-10T13:00:00.000Z'}]},
events: {format: 'database-events', version: 1, kind: 'meruhen', events: []}};
const posts = [];

const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
try {
  const context = await browser.newContext({viewport: {width: 393, height: 852}});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await context.route('https://script.google.com/**', route => {
    const request = route.request(), url = new URL(request.url());
    const headers = {'access-control-allow-origin': '*'};
    if (request.method() === 'POST') {
      posts.push(JSON.parse(request.postData()));
      return route.fulfill({status: 200, contentType: 'application/json', headers, body: JSON.stringify({ok: true, marks: 1, changed: 1})});
    }
    const file = url.searchParams.get('file');
    if (file && shared[file]) return route.fulfill({status: 200, contentType: 'application/json', headers, body: JSON.stringify(shared[file])});
    return route.fulfill({status: 200, contentType: 'application/json', headers, body: JSON.stringify({error: 'この試験では閲覧用ファイルを返しません。'})});
  });
  await page.goto(origin + '/setup');
  await page.evaluate(async ({data, script}) => {
    localStorage.setItem('database-viewer-remote', script);
    const db = await new Promise((resolve, reject) => { const q = indexedDB.open('database-viewer', 1); q.onupgradeneeded = () => q.result.createObjectStore('kv'); q.onsuccess = () => resolve(q.result); q.onerror = () => reject(q.error); });
    await new Promise((resolve, reject) => { const tx = db.transaction('kv', 'readwrite'); tx.objectStore('kv').put(JSON.stringify(data), 'data'); tx.oncomplete = resolve; tx.onerror = () => reject(tx.error); }); db.close();
  }, {data: meruhen, script});
  const stored = () => page.evaluate(async () => {
    const db = await new Promise((resolve, reject) => { const q = indexedDB.open('database-viewer', 1); q.onsuccess = () => resolve(q.result); q.onerror = () => reject(q.error); });
    const value = await new Promise((resolve, reject) => { const r = db.transaction('kv').objectStore('kv').get('data'); r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error); });
    db.close(); return JSON.parse(value);
  });
  async function home() {
    await page.goto(origin + prefix);
    await page.waitForSelector('flt-glass-pane', {state: 'attached', timeout: 60000});
    const p = page.locator('flt-semantics-placeholder'); if (await p.count()) await p.evaluate(e => e.click());
    await page.getByText('database 閲覧', {exact: true}).waitFor({timeout: 60000});
  }
  async function rack(number) {
    await page.mouse.move(200, 700); await page.mouse.wheel(0, 2200); await page.waitForTimeout(300);
    const button = page.getByRole('button', {name: /^化物語/}).last();
    await button.scrollIntoViewIfNeeded(); await button.click();
    await page.getByText('データ表示', {exact: true}).waitFor();
    // 🌈の付いた台は「1085🌈」と出るので、台番号で始まる文字で探す。
    await page.getByText(new RegExp(`^${number}`)).first().click();
  }
  await home();
  // ほかの端末の🌈（共有ファイル）が端末の内容に入る。
  for (let i = 0; i < 60 && !((await stored()).rainbow_marks || []).length; i++) await page.waitForTimeout(250);
  assert.deepEqual((await stored()).rainbow_marks.map(m => [m.rack, m.on]), [[1086, true]]);
  await rack(1085);
  const toggle = page.getByRole('button', {name: '🌈 付ける', exact: true});
  await toggle.waitFor();
  await toggle.click();
  await page.getByRole('button', {name: '🌈 外す', exact: true}).waitFor();
  await page.getByText('1085番台 🌈', {exact: true}).waitFor();
  for (let i = 0; i < 40 && !posts.length; i++) await page.waitForTimeout(250);
  const sent = posts.at(-1);
  assert.equal(sent.file, 'rainbow');
  assert.ok(sent.marks.some(m => m.rack === 1085 && m.day === '2026-10-10' && m.on === true && /T/.test(m.updated_at)), JSON.stringify(sent));
  assert.ok(sent.marks.some(m => m.rack === 1086), '前の印もまとめて送る（送れなかった分も届く）');
  // 開き直しても残る。外すと false を送る。
  await home(); await rack(1085);
  await page.getByText('1085番台 🌈', {exact: true}).waitFor();
  const before = posts.length;
  await page.getByRole('button', {name: '🌈 外す', exact: true}).click();
  await page.getByRole('button', {name: '🌈 付ける', exact: true}).waitFor();
  for (let i = 0; i < 40 && posts.length === before; i++) await page.waitForTimeout(250);
  assert.ok(posts.slice(before).some(p => p.marks.some(m => m.rack === 1085 && m.on === false)));
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'no page overflow');
  assert.deepEqual(errors, []);
  console.log('PASS: viewer rack page 🌈 toggle saves on the device, posts {file: rainbow}, survives reload, pulls other devices\' marks');
  await context.close();
} finally {
  await browser.close();
  await new Promise(resolve => server.close(resolve));
}
