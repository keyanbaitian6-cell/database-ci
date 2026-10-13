// Build viewer_main.dart and stage_viewer.py before this browser test.
// バラエティの回っていない台（2026-10-10）：ホームのボタンから開き、期間・ゲーム数のプルダウンで
// 選び直せること、選んだ値を端末（localStorage）に覚えて開き直しても残ること。localStorage を
// 直接呼ぶ橋渡し（viewer_bridge_web.dart）は、Webでしか動かないのでここで確かめる。
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

// 10/1〜10/8：北斗4台（主力）と、バラエティのハナハナ（毎日300G）・ジャグラー（毎日800G）。
const records = [];
for (let d = 1; d <= 8; d++) {
  const day = `2026-10-0${d}`;
  for (let rack = 1; rack <= 4; rack++) records.push({store: 'saiwaichou', day, machine: '北斗', rack, games: 3000, bb: 10, rb: 5});
  for (let rack = 70; rack <= 72; rack++) records.push({store: 'saiwaichou', day, machine: '三台機種', rack, games: 300, bb: 1, rb: 1}); // 1〜2台だけにまとめ、3台機種を除く
  records.push({store: 'saiwaichou', day, machine: 'ハナハナ', rack: 50, games: 300, bb: 1, rb: 1});
  records.push({store: 'saiwaichou', day, machine: 'ジャグラー', rack: 60, games: 800, bb: 2, rb: 2});
}
const meruhen = {header: {format: 'database-backup', version: 1, source: 'pc', exported_at: '2026-10-08T23:00:00+09:00'}, records};

const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
const context = await browser.newContext({viewport: {width: 393, height: 852}});
const page = await context.newPage();
const errors = [];
page.on('pageerror', e => { errors.push(e.message); console.error('pageerror', e.message); });

async function home() {
  await page.goto(process.env.VIEWER_PUBLIC_URL || origin + prefix);
  await page.waitForSelector('flt-glass-pane', {state: 'attached', timeout: 60000});
  const placeholder = page.locator('flt-semantics-placeholder');
  if (await placeholder.count()) await placeholder.evaluate(e => e.click());
  await page.getByText('database 閲覧', {exact: true}).waitFor({timeout: 60000});
}
async function labels() {
  return page.evaluate(() => [...document.querySelectorAll('flt-semantics')].map(e => e.getAttribute('aria-label') || e.textContent || ''));
}
async function waitSeen(pattern) {
  for (let i = 0; i < 60; i++) { if ((await labels()).some(l => pattern.test(l))) return; await page.waitForTimeout(250); }
  assert.fail(`not shown: ${pattern}\n${(await labels()).join('\n')}`);
}
async function openPage() {
  const button = page.getByRole('button', {name: 'バラエティの回っていない台（期間・ゲーム数を選べる）'});
  for (let i = 0; i < 20 && !(await button.count()); i++) { await page.mouse.wheel(0, 300); await page.waitForTimeout(200); }
  await button.click();
  await page.getByText('バラエティの回っていない台', {exact: true}).waitFor();
}
async function choose(current, next) {
  await page.getByText(current).first().click();
  await page.getByRole('menuitem', {name: next, exact: true}).click();
  await page.waitForTimeout(300);
}

try {
  await page.goto(process.env.VIEWER_PUBLIC_URL || origin + '/setup');
  await page.evaluate(async data => {
    const db = await new Promise((resolve, reject) => { const q = indexedDB.open('database-viewer', 1); q.onupgradeneeded = () => q.result.createObjectStore('kv'); q.onsuccess = () => resolve(q.result); q.onerror = () => reject(q.error); });
    await new Promise((resolve, reject) => { const tx = db.transaction('kv', 'readwrite'); tx.objectStore('kv').put(JSON.stringify(data), 'data'); tx.objectStore('kv').put('meruhen', 'active_source'); tx.oncomplete = resolve; tx.onerror = () => reject(tx.error); }); db.close();
  }, meruhen);
  await home();
  await openPage();
  // 既定：7日以上・1,000G未満 → ハナハナとジャグラー（10/1〜10/8 の8日間）。
  await waitSeen(/^2台$/);
  assert.equal((await labels()).some(l => l.includes('三台機種')), false, '3台機種はバラエティの回っていない台に入れない');
  await waitSeen(/8日間 1,000G未満/);
  assert.equal(await page.evaluate(() => localStorage.getItem('database-viewer-idle-games')), null, '選ぶまでは覚えない');
  // 500G未満にすると、800Gのジャグラーは外れる。
  await choose(/1,000G未満/, '500G未満');
  await waitSeen(/^1台$/);
  await waitSeen(/8日間 500G未満/);
  // 期間を10日以上にすると、8日分しかないので当てはまらない。
  await choose(/7日以上/, '10日以上');
  await waitSeen(/当てはまる台はありません/);
  assert.deepEqual(await page.evaluate(() => [localStorage.getItem('database-viewer-idle-days'), localStorage.getItem('database-viewer-idle-games')]), ['10', '500']);
  for (const width of [320, 393]) {
    await page.setViewportSize({width, height: 852}); await page.waitForTimeout(250);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `no page overflow at ${width}px`);
  }
  await page.setViewportSize({width: 393, height: 852});
  // 開き直しても選んだ値のまま。
  await home();
  await openPage();
  await waitSeen(/10日以上/);
  await waitSeen(/500G未満/);
  await waitSeen(/当てはまる台はありません/);
  await choose(/10日以上/, '7日以上');
  await waitSeen(/^1台$/);
  assert.deepEqual(errors, []);
  console.log('PASS: variety idle racks page (period/games dropdowns, remembered in localStorage), 320/393px');
} finally {
  await browser.close();
  await new Promise(resolve => server.close(resolve));
}
