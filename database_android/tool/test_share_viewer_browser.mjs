// 閲覧専用の共有ページ（share_viewer/、お試し 2026-10-09）を隔離ブラウザで開く。スクリプトへの通信は偽の返事。
// カレンダーの差枚・イベント、日付を押したTOP50（11位からは折りたたみ）・10選、台を押す→その機種の台一覧→台のデータ、店の切り替え、リンクの # を消すこと、何も送らないこと、
// 利用者自身の閲覧ページの保存（database-viewer の名前）に触れないこと、狭い画面ではみ出さないこと。
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
// SHARE_WEB_ROOT（check_before_build.sh が渡す）があれば、公開するステージ（版 ?v= 付き）を試す。
const root = process.env.SHARE_WEB_ROOT || fileURLToPath(new URL('../../share_viewer/', import.meta.url));
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
const d1 = `${ym}-01`, d2 = `${ym}-02`, d3 = `${ym}-03`;
const curve = (heights) => {
  const c = heights.map((h, i) => [i * 10 + 0.5, 200.5 - h]);
  const ys = c.map(p => p[1]);
  return {baseline_y: 200.5, peak_y: Math.min(...ys), trough_y: Math.max(...ys), end_y: c.at(-1)[1], curve: c};
};
const meruhen = {format: 'database-backup', version: 1, exported_at: '2026-10-09T06:48:00+09:00', records: [
  {store: 'nagamachiminami', day: d1, machine: 'ｺﾞｰｺﾞｰｼﾞｬｸﾞﾗｰ3', rack: 101, games: 6000, bb: 30, rb: 20, max_hold: 2376, graph_measurement: curve([0, -63, 40, 147, 128])},
  {store: 'nagamachiminami', day: d1, machine: 'ｺﾞｰｺﾞｰｼﾞｬｸﾞﾗｰ3', rack: 102, games: 4000, bb: 10, rb: 5, max_hold: 2900, graph_measurement: curve([0, 120, 40, -50])},
  {store: 'nagamachiminami', day: d1, machine: '北斗<script>', rack: 103, games: 88888888, bb: 1, rb: 1, max_hold: 1},
  // 3日：ジャグラーオンラインの差枚の台が15台（TOP50の11位からは折りたたみ）。ネオアイム201〜214番は (i-7)*100 枚。
  {store: 'nagamachiminami', day: d3, machine: 'ハナハナ', rack: 301, games: 7000, bb: 30, rb: 20, jo_net: 5000},
  ...Array.from({length: 14}, (_, k) => ({store: 'nagamachiminami', day: d3, machine: 'ネオアイム', rack: 201 + k,
    games: 1000 * (k + 1), bb: 11 + k, rb: k + 6, max_hold: 1500, jo_net: (k - 6) * 100})),
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
    const modules = [];
    page.on('request', r => { if (/\.mjs(\?|$)/.test(r.url())) modules.push(new URL(r.url()).pathname + new URL(r.url()).search); });
    page.on('pageerror', e => errors.push(e.message));
    // 利用者自身の閲覧ページの保存（同じ github.io で開いたとき）を置いておき、触れないことを確かめる。
    await page.goto(pageUrl);
    await page.evaluate(() => localStorage.setItem('database-viewer-remote', 'mine'));
    await page.goto(`${pageUrl}#s=${id}&u=himawari`);
    await page.waitForSelector('.grid');
    assert.equal(new URL(page.url()).hash, '', 'リンクのIDと呼び名はアドレス欄から消す');
    const storage = await page.evaluate(() => Object.fromEntries(Object.keys(localStorage).map(k => [k, localStorage.getItem(k)])));
    assert.deepEqual(storage, {'database-viewer-remote': 'mine', 'database-share-script-id': id, 'database-share-name': 'himawari'});
    assert.deepEqual(urls.slice().sort(), ['?file=events', '?file=pscube&check=1', '?file=pscube-events', '?file=rainbow', '?u=himawari&check=1&access=1'], '呼び名は最初の読み込みにだけ付ける（🌈のファイルも読む、2026-10-11）');
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
    // 3日：はじめの10位までが見え、11〜15位は折りたたみ。台を押す→その機種の台一覧→台のデータ→戻る。
    await page.locator(`[data-open="${d3}"]`).click();
    const rows = page.locator('.sheet .list .row');
    assert.equal(await rows.count(), 15 + 1, '差枚15台と強かった機種1つ（ハナハナは1台なので入らない）');
    assert.equal(await page.locator('.sheet > .list').first().locator('.row').count(), 10);
    const more = page.locator('.sheet details.more');
    assert.match(await more.locator('summary').innerText(), /11〜15位を見る（5台）/);
    assert.equal(await more.locator('.row').first().isVisible(), false, '11位からは折りたたむ');
    await more.locator('summary').click();
    const eleventh = more.locator('.row').first();
    assert.match(await eleventh.innerText(), /^11\s*205番\s*ネオアイム\s*-200/);
    await more.locator('.row').nth(1).click();
    assert.equal(await page.locator('#sheet-title').innerText(), 'ネオアイム');
    assert.match(await page.locator('.sheet').innerText(), /14台・平均7,500G/);
    const machineRows = page.locator('.sheet .list .row');
    assert.equal(await machineRows.count(), 14);
    assert.deepEqual((await machineRows.allInnerTexts()).map(t => Number(/(\d+)番/.exec(t)[1])),
      Array.from({length: 14}, (_, k) => 201 + k), '台番号の順');
    assert.match(await page.locator('.sheet li.current').innerText(), /204番/, '押した台に印');
    await page.locator('.sheet .row', {hasText: '204番'}).click();
    assert.equal(await page.locator('#sheet-title').innerText(), '204番台');
    const rack = await page.locator('.sheet').innerText();
    assert.match(rack, /差枚\s*-300/);
    assert.match(rack, /回転数\s*4,000G/);
    assert.match(rack, /BB確率\s*1\/285\.7/);
    assert.match(rack, /RB確率\s*1\/444\.4/);
    assert.match(rack, /合成確率\s*1\/173\.9/);
    assert.match(rack, /最大持玉\s*1,500/);
    await page.getByRole('button', {name: '‹ 戻る'}).click();
    assert.equal(await page.locator('#sheet-title').innerText(), 'ネオアイム');
    await page.keyboard.press('Escape');
    assert.ok(await page.locator('.sheet details.more').evaluate(e => e.open), '戻ると折りたたみは開いたまま');
    // 強かった機種を押しても、その機種の台一覧。
    await page.locator('.sheet > .list').last().locator('.row').click();
    assert.equal(await page.locator('#sheet-title').innerText(), 'ネオアイム');
    assert.equal(await page.locator('.sheet li.current').count(), 0);
    // 下へ送っても、ボタンの帯の後ろに表が透けない。
    assert.equal(await page.locator('.sheet-head').evaluate(e => getComputedStyle(e).backgroundColor), 'rgb(255, 255, 255)');
    const sheetOverflow = await page.locator('.sheet').evaluate(e => e.scrollWidth - e.clientWidth);
    assert.ok(sheetOverflow <= 0, `シートが横にはみ出す（${width}px）`);
    await page.getByRole('button', {name: '閉じる'}).click();
    await page.waitForSelector('.sheet', {state: 'detached'});
    // P-STATION（データはP’s CUBE）：元グラフの差枚、共有のイベント。表記は P-STATION だけ。
    assert.equal(await page.getByText(/P’s CUBE/).count(), 0);
    // 選んでいる店は青で塗る（どこを選んでいるか分かる）。
    const pressed = page.locator('.anchor[aria-pressed="true"]');
    assert.equal(await pressed.innerText(), '長町南');
    assert.equal(await pressed.evaluate(e => getComputedStyle(e).backgroundColor), 'rgb(0, 113, 227)');
    assert.equal(await page.locator('.anchor[aria-pressed="false"]').first().evaluate(e => getComputedStyle(e).backgroundColor), 'rgba(0, 0, 0, 0)');
    await page.getByRole('button', {name: 'P-STATION', exact: true}).click();
    assert.equal(await pressed.innerText(), 'P-STATION');
    assert.match(await page.locator('.kicker').innerText(), /P-STATION（20スロ）/);
    const p2 = page.locator(`[data-open="${d2}"]`);
    assert.match(await p2.innerText(), /末尾イベ/);
    assert.match(await p2.innerText(), /\+3,121/);
    await p2.click();
    assert.match(await page.locator('.sheet').innerText(), /総差枚\s*\+3,121/);
    await page.locator('.sheet .row', {hasText: '1番'}).first().click();
    await page.locator('.sheet .row', {hasText: '1番'}).first().click();
    const pRack = await page.locator('.sheet').innerText();
    assert.match(pRack, /差枚\s*\+4,321/);
    assert.match(pRack, /MY\s*3,000/, 'P-STATIONはMY');
    assert.ok(!/最大持玉/.test(pRack));
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
    const beforeReload = urls.length;
    await page.goto(pageUrl);
    await page.waitForSelector('.grid');
    assert.equal(await page.locator('.anchor[aria-pressed="true"]').innerText(), '幸町');
    assert.equal(urls.length, beforeReload, '保存済みで起動するときはGoogleへ通信しない');
    await page.locator('#reload').click();
    await page.waitForFunction(() => !document.querySelector('#reload').disabled);
    assert.ok(urls.slice(beforeReload).includes('?u=himawari&check=1&access=1'), '手動更新時は覚えた呼び名で記録する');
    assert.deepEqual([...new Set(methods)], ['GET'], '読むだけ（POSTしない）');
    assert.deepEqual(errors, []);
    if (process.env.SHARE_WEB_ROOT || process.env.SHARE_PUBLIC_URL) {
      // 公開するページは、読むファイルすべてに同じ版を付ける（古い版を覚えた端末でも新しい版を読む）。
      const names = [...new Set(modules)].map(m => /\/(\w+\.mjs)\?v=([0-9a-f]{12})$/.exec(m));
      assert.ok(names.length === 5 && names.every(Boolean), `版の付いていない読み込み：${modules}`);
      assert.deepEqual(names.map(n => n[1]).sort(), ['app.mjs', 'data.mjs', 'net.mjs', 'offline.mjs', 'viewer_parts.mjs']);
      assert.equal(new Set(names.map(n => n[2])).size, 1);
    }
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
