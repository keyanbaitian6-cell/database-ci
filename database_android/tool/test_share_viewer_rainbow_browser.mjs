// 共有ページの🌈（2026-10-11 利用者「この虹マークを付けるだけの機能なら共有の方にもつけたい」「共有の方にも店舗別の
// バラエティ一覧つけて同じようにしたい」、RAINBOW.md「共有ページから付ける」）を隔離ブラウザで開く。
// 「バラエティ🌈」：最新の並び・選んだ日の数値・最終🌈・30日、右の🌈で付け外し（{file: 'rainbow', marks} をPOST）、
// 行を押すと台のデータ（🌈 外す）。ほかの端末の🌈（?file=rainbow）も出す。開き直しても残る。320/393pxではみ出さない。
// Googleのスクリプトは偽物（route）で、外へは出ない。
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
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
const pageUrl = `http://127.0.0.1:${server.address().port}/share/index.html`;

const records = [];
for (const day of ['2026-10-09', '2026-10-10']) {
  for (let rack = 1; rack <= 4; rack++) records.push({store: 'saiwaichou', day, machine: '主力', rack, games: 4000, bb: 20, rb: 10, jo_net: 100});
  records.push({store: 'saiwaichou', day, machine: 'ハナハナ', rack: 50, games: day === '2026-10-10' ? 5000 : 300, bb: 1, rb: 1, jo_net: -250,
    ...(day === '2026-10-09' ? {rainbow: true, rainbow_at: '2026-10-09T23:00:00.123456+09:00'} : {})});
  records.push({store: 'saiwaichou', day, machine: 'ハナハナ', rack: 51, games: 800, bb: 2, rb: 2, jo_net: -500});
  records.push({store: 'saiwaichou', day, machine: day === '2026-10-10' ? '新バラエティ' : '旧バラエティ', rack: 60, games: 1200, bb: 3, rb: 3, jo_net: 300});
}
// ほかの端末で 51番台（10/10）に付けた🌈。
const responses = {
  '': {format: 'database-backup', version: 1, exported_at: '2026-10-10T23:00:00+09:00', records},
  pscube: {format: 'pscube-viewer', version: 1, records: []},
  events: {format: 'database-events', version: 1, kind: 'meruhen', events: []},
  'pscube-events': {format: 'database-events', version: 1, kind: 'pscube', events: []},
  rainbow: {format: 'database-rainbow', version: 1, marks: [
    {store: 'saiwaichou', day: '2026-10-10', rack: 51, on: true, updated_at: '2026-10-11T01:00:00.000Z'}]},
};
const id = 'AKfycbTEST' + 'x'.repeat(40);

const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
try {
  for (const width of [320, 393]) {
    const context = await browser.newContext({viewport: {width, height: 860}});
    const posts = [];
    await context.route('https://script.google.com/**', route => {
      const request = route.request();
      const headers = {'access-control-allow-origin': '*'};
      if (request.method() === 'POST') {
        posts.push(JSON.parse(request.postData()));
        return route.fulfill({status: 200, contentType: 'application/json', headers, body: JSON.stringify({ok: true, marks: 2, changed: 1})});
      }
      const file = new URL(request.url()).searchParams.get('file') ?? '';
      route.fulfill({status: 200, contentType: 'application/json', headers, body: JSON.stringify(responses[file] ?? {error: 'no'})});
    });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(`${pageUrl}#s=${id}`);
    await page.waitForSelector('.grid');
    await page.getByRole('button', {name: '幸町', exact: false}).first().click().catch(() => {});
    const open = async () => {
      await page.getByRole('button', {name: 'バラエティ🌈', exact: true}).click();
      await page.waitForSelector('.sheet');
    };
    await open();
    const sheet = page.locator('.sheet');
    const text = async () => (await sheet.innerText()).replace(/\s+/g, ' ');
    // 最新（10/10）の並び：バラエティ（1〜3台）の 50・51・60。主力（4台）は出さない。
    assert.match(await text(), /3台（2機種）・この日の🌈 1台/);
    assert.match(await text(), /51番🌈/, 'ほかの端末の🌈も出す');
    assert.match(await text(), /50番 ハナハナ 5,000G・-250・最終🌈 10\/9（1日前）・30日 1/);
    assert.ok(!/主力/.test(await text()));
    // 右の🌈で付ける → POST・表示。
    await sheet.getByRole('button', {name: '50番台の🌈 付ける'}).click();
    for (let i = 0; i < 40 && !posts.length; i++) await page.waitForTimeout(100);
    assert.equal(posts.length, 1);
    assert.equal(posts[0].file, 'rainbow');
    assert.deepEqual(posts[0].marks.map(m => [m.store, m.day, m.rack, m.on]), [['saiwaichou', '2026-10-10', 50, true]]);
    await sheet.getByRole('button', {name: '50番台の🌈 外す'}).waitFor();
    assert.match(await text(), /この日の🌈 2台/);
    await page.locator('.toast').waitFor();
    // 前の日を選ぶと、並びは最新のまま、その日の機種名を付ける。
    await page.locator('select[data-variety="day"]').selectOption('2026-10-09');
    assert.match(await text(), /60番 新バラエティ（この日：旧バラエティ）/);
    assert.match(await text(), /50番🌈/);
    // 並べ方：最終🌈の古い順（一度も無い60が先）。
    await page.locator('select[data-variety="day"]').selectOption('2026-10-10');
    await page.locator('select[data-variety="sort"]').selectOption('最終🌈の古い順');
    const racks = await sheet.locator('.rack').allInnerTexts();
    assert.equal(racks[0], '60番');
    // 行を押すと台のデータ。そこからも外せる。
    await sheet.locator('button.row', {hasText: '50番'}).click();
    assert.equal(await page.locator('#sheet-title').innerText(), '50番台 🌈');
    await sheet.getByRole('button', {name: '50番台の🌈 外す'}).click();
    for (let i = 0; i < 40 && posts.length < 2; i++) await page.waitForTimeout(100);
    assert.equal(posts[1].marks.find(m => m.rack === 50).on, false);
    await page.locator('#sheet-title', {hasText: /^50番台$/}).waitFor();
    const overflow = await sheet.evaluate(e => e.scrollWidth - e.clientWidth);
    assert.ok(overflow <= 0, `シートが横にはみ出す（${width}px、${overflow}px）`);
    // 開き直しても、この端末で付け外しした分は残る（共有ファイルが古いままでも）。
    await page.getByRole('button', {name: '閉じる'}).click();
    await page.reload();
    await page.waitForSelector('.grid');
    await open();
    assert.match(await text(), /50番 ハナハナ/);
    assert.ok(!/50番🌈/.test(await text()), '外したまま');
    await page.getByRole('button', {name: '閉じる'}).click();
    assert.deepEqual(errors, []);
    await context.close();
  }
  console.log('PASS: share viewer バラエティ🌈 list (latest lineup, day numbers, 最終🌈, 30日), one-tap 🌈 posts {file: rainbow}, rack view toggle, kept on reload, 320/393px');
} finally {
  await browser.close();
  await new Promise(resolve => server.close(resolve));
}
