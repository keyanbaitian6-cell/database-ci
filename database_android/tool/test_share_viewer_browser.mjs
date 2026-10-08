// 閲覧専用の共有ページ（share_viewer/、お試し 2026-10-09）を隔離ブラウザで開く。スクリプトへの通信は偽の返事。
// カレンダーの差枚・イベント、日付を押したTOP10・5選、店の切り替え、リンクの # を消すこと、何も送らないこと、
// 利用者自身の閲覧ページの保存（database-viewer の名前）に触れないこと、狭い画面ではみ出さないこと。
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = fileURLToPath(new URL('../../share_viewer/', import.meta.url));
const server = http.createServer(async (req, res) => {
  const name = new URL(req.url, 'http://x').pathname.replace(/^\/share\//, '') || 'index.html';
  const local = path.resolve(root, name);
  if (!local.startsWith(path.resolve(root))) { res.writeHead(403).end(); return; }
  try {
    const body = await fs.readFile(local);
    res.setHeader('content-type', local.endsWith('.mjs') ? 'text/javascript' : 'text/html; charset=utf-8');
    res.end(body);
  } catch { res.writeHead(404).end(); }
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const origin = `http://127.0.0.1:${server.address().port}`;
// SHARE_PUBLIC_URL（例 https://keyanbaitian6-cell.github.io/database-share/index.html）を渡すと、公開したページで試す。
const pageUrl = process.env.SHARE_PUBLIC_URL || `${origin}/share/index.html`;

// 今月（日本時間）の1日・2日に台を置く（ページは今月から開く）。
const now = new Date(Date.now() + 9 * 3600000);
const ym = now.toISOString().slice(0, 7);
const d1 = `${ym}-01`, d2 = `${ym}-02`;
const curve = (heights) => {
  const c = heights.map((h, i) => [i * 10 + 0.5, 200.5 - h]);
  const ys = c.map(p => p[1]);
  return {baseline_y: 200.5, peak_y: Math.min(...ys), trough_y: Math.max(...ys), end_y: c.at(-1)[1], curve: c};
};
const meruhen = {format: 'database-backup', version: 1, exported_at: '2026-10-09T06:48:00+09:00', records: [
  {store: 'nagamachiminami', day: d1, machine: 'ｺﾞｰｺﾞｰｼﾞｬｸﾞﾗｰ3', rack: 101, games: 6000, bb: 30, rb: 20, max_hold: 2376, graph_measurement: curve([0, -63, 40, 147, 128])},
  {store: 'nagamachiminami', day: d1, machine: 'ｺﾞｰｺﾞｰｼﾞｬｸﾞﾗｰ3', rack: 102, games: 4000, bb: 10, rb: 5, max_hold: 2900, graph_measurement: curve([0, 120, 40, -50])},
  {store: 'nagamachiminami', day: d1, machine: '北斗<script>', rack: 103, games: 88888888, bb: 1, rb: 1, max_hold: 1},
  {store: 'saiwaichou', day: d2, machine: '幸町の機種', rack: 5, games: 3000, bb: 9, rb: 9, max_hold: 2376, graph_measurement: curve([0, -63, 40, 147, 128])},
], date_events: [{store: 'nagamachiminami', day: d1, name: '半列<b>', updated_at: '2026-09-01T00:00:00Z'}]};
const pscube = {format: 'pscube-viewer', version: 1, exported_at: '2026-10-09T06:40:00+09:00', machines: [], records: [
  {store: 'c740601', rate: '20', day: d2, machine: 'ﾏｲｼﾞｬｸﾞﾗｰV', rack: 1, games: 5000, bb: 20, rb: 10, my: 3000, net_medals: 4321},
  {store: 'c740601', rate: '20', day: d2, machine: 'ﾏｲｼﾞｬｸﾞﾗｰV', rack: 2, games: 2000, bb: 5, rb: 3, my: 1000, net_medals: -1200},
]};
const shared = {format: 'database-events', version: 1, kind: 'pscube', events: [
  {store: 'c740601', rate: '20', day: d2, name: '末尾イベ', updated_at: '2026-09-01T00:00:00Z'}]};
const responses = {'': meruhen, pscube, events: {format: 'database-events', version: 1, kind: 'meruhen', events: []}, 'pscube-events': shared};
const id = 'AKfycbTEST' + 'x'.repeat(40);

const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
try {
  for (const width of [320, 393, 1280]) {
    const context = await browser.newContext({viewport: {width, height: 860}});
    const methods = [];
    const urls = [];
    await context.route('https://script.google.com/**', route => {
      const request = route.request();
      methods.push(request.method());
      urls.push(new URL(request.url()).search);
      const file = new URL(request.url()).searchParams.get('file') ?? '';
      route.fulfill({status: 200, contentType: 'application/json', headers: {'access-control-allow-origin': '*'},
        body: JSON.stringify(responses[file] ?? {error: 'no'})});
    });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    // 利用者自身の閲覧ページの保存（同じ github.io で開いたとき）を置いておき、触れないことを確かめる。
    await page.goto(pageUrl);
    await page.evaluate(() => localStorage.setItem('database-viewer-remote', 'mine'));
    await page.goto(`${pageUrl}#s=${id}&u=himawari`);
    await page.waitForSelector('.grid');
    assert.equal(new URL(page.url()).hash, '', 'リンクのIDと呼び名はアドレス欄から消す');
    const storage = await page.evaluate(() => Object.fromEntries(Object.keys(localStorage).map(k => [k, localStorage.getItem(k)])));
    assert.deepEqual(storage, {'database-viewer-remote': 'mine', 'database-share-script-id': id, 'database-share-name': 'himawari'});
    assert.deepEqual(urls.slice().sort(), ['?file=events', '?file=pscube', '?file=pscube-events', '?u=himawari'], '呼び名は最初の読み込みにだけ付ける');
    // 長町南：1日は +1422-1111 = +311、イベント（HTMLとして解釈しない）。
    const cell = page.locator(`[data-open="${d1}"]`);
    assert.match(await cell.innerText(), /半列<b>/);
    assert.match(await cell.innerText(), /\+311/);
    assert.equal(await page.locator('b').count(), 0);
    await cell.click();
    await page.waitForSelector('.sheet');
    const sheet = await page.locator('.sheet').innerText();
    assert.match(sheet, /総推定差枚\s*\+311/);
    assert.match(sheet, /推定差枚がわかった台 2\/2台/, '数値異常の台は数えない');
    assert.match(sheet, /101番\s*ゴーゴージャグラー3\s*\+1,422/);
    assert.match(sheet, /ゴーゴージャグラー3\s*5,000G\s*2台/);
    assert.ok(!/script/.test(await page.locator('.sheet .list').first().innerText()), '数値異常の台はTOP10に入れない');
    await page.keyboard.press('Escape');
    await page.waitForSelector('.sheet', {state: 'detached'});
    // P-STATION（データはP’s CUBE）：元グラフの差枚、共有のイベント。表記は P-STATION だけ。
    assert.equal(await page.getByText(/P’s CUBE/).count(), 0);
    await page.getByRole('button', {name: 'P-STATION（20スロ）'}).click();
    const p2 = page.locator(`[data-open="${d2}"]`);
    assert.match(await p2.innerText(), /末尾イベ/);
    assert.match(await p2.innerText(), /\+3,121/);
    await p2.click();
    assert.match(await page.locator('.sheet').innerText(), /総差枚\s*\+3,121/);
    await page.getByRole('button', {name: '閉じる'}).click();
    // 幸町は選んだまま次に開いても残る。月の切り替え。
    await page.getByRole('button', {name: '幸町'}).click();
    assert.match(await page.locator(`[data-open="${d2}"]`).innerText(), /\+1,422/);
    await page.getByRole('button', {name: '次の月'}).click();
    assert.equal(await page.locator('[data-open]').count(), 0);
    await page.getByRole('button', {name: '今月'}).click();
    assert.equal(await page.locator('[data-open]').count(), 1);
    // はみ出さない。
    const overflow = await page.evaluate(() => document.scrollingElement.scrollWidth - window.innerWidth);
    assert.ok(overflow <= 0, `横にはみ出す（${width}px、${overflow}px）`);
    // 2回目はリンクなしでも開ける（覚えたIDと店）。
    await page.goto(pageUrl);
    await page.waitForSelector('.grid');
    assert.equal(await page.locator('.anchor[aria-pressed="true"]').innerText(), '幸町');
    assert.ok(urls.slice(4).includes('?u=himawari'), 'リンクなしで開き直しても、覚えた呼び名で記録する');
    assert.deepEqual([...new Set(methods)], ['GET'], '読むだけ（POSTしない）');
    assert.deepEqual(errors, []);
    await context.close();
  }
  // リンク無し：貼り付けの画面。形の違うものは断り、正しいリンクで開く。
  const context = await browser.newContext({viewport: {width: 393, height: 860}});
  await context.route('https://script.google.com/**', route => route.fulfill({status: 200, contentType: 'application/json',
    headers: {'access-control-allow-origin': '*'}, body: JSON.stringify(responses[new URL(route.request().url()).searchParams.get('file') ?? ''] ?? {})}));
  const page = await context.newPage();
  await page.goto(pageUrl);
  await page.getByRole('textbox', {name: '受け取ったリンク'}).fill('https://example.com/');
  await page.getByRole('button', {name: '開く'}).click();
  await page.getByText('リンクの形が違います').waitFor();
  await page.getByRole('textbox', {name: '受け取ったリンク'}).fill(`https://keyanbaitian6-cell.github.io/database-share/#s=${id}`);
  await page.getByRole('button', {name: '開く'}).click();
  await page.waitForSelector('.grid');
  await context.close();
  console.log('PASS: share viewer calendar, day sheet, stores, months, read-only GET, own storage untouched, 320/393/1280px');
} finally {
  await browser.close();
  server.close();
}
