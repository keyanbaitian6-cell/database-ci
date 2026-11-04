// 共有カレンダーの「台番の末尾の印」（2026-11-05 利用者「差枚一覧で選んだ末尾を、機種一覧でも追えるようにする」）を
// 隔離ブラウザで開く。日の画面（TOP50）で末尾を選ぶ→印→機種の台一覧・全機種の台一覧へ引き継ぐ（台は全部出したまま）→
// 「末尾7 ×」で解除→日付を変えると解除。320/393pxではみ出さない。Googleのスクリプトは偽物（route）。
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
const pageUrl = process.env.SHARE_PUBLIC_URL || `http://127.0.0.1:${server.address().port}/share/index.html`;

const day = '2026-10-10', before = '2026-10-09';
const records = [];
const at = (d, rack, machine, net, games = 3000) =>
  records.push({store: 'saiwaichou', day: d, machine, rack, games, bb: 5, rb: 5, ...(net === null ? {} : {jo_net: net})});
at(day, 1, '主力', 300);
at(day, 2, '主力', -800);
at(day, 3, '主力', 1500);
at(day, 4, '主力', null);   // 差枚なし（TOP50には出ない）
at(day, 5, '主力', 0);
at(day, 17, '主力', 300);
at(day, 27, 'ハナハナ', 100);
at(day, 50, 'ハナハナ', -200);
at(before, 1, '主力', 100);
at(before, 17, '主力', 200);
const responses = {
  '': {format: 'database-backup', version: 1, exported_at: '2026-10-10T23:00:00+09:00', records},
  pscube: {format: 'pscube-viewer', version: 1, records: []},
  events: {format: 'database-events', version: 1, kind: 'meruhen', events: []},
  'pscube-events': {format: 'database-events', version: 1, kind: 'pscube', events: []},
  rainbow: {format: 'database-rainbow', version: 1, marks: []},
};
const id = 'AKfycbTEST' + 'x'.repeat(40);

const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
try {
  for (const width of [320, 393]) {
    const context = await browser.newContext({viewport: {width, height: 860}});
    await context.route('https://script.google.com/**', route => {
      const file = new URL(route.request().url()).searchParams.get('file') ?? '';
      route.fulfill({status: 200, contentType: 'application/json', headers: {'access-control-allow-origin': '*'},
        body: JSON.stringify(responses[file] ?? {error: 'no'})});
    });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.clock.setFixedTime(new Date('2026-10-10T03:00:00Z'));
    await page.goto(`${pageUrl}#s=${id}`);
    await page.waitForSelector('.grid');
    const sheet = page.locator('.sheet');
    const overflow = async () => sheet.evaluate(e => e.scrollWidth - e.clientWidth);
    const markedRacks = async () => sheet.locator('.suffix-mark').evaluateAll(marks =>
      marks.map(m => m.parentElement.textContent.replace(/末\d|🌈/g, '').trim()));
    const shot = async (name) => { if (process.env.SUFFIX_SHOTS) await page.screenshot({path: `${process.env.SUFFIX_SHOTS}/${name}-${width}.png`, fullPage: false}); };

    await page.locator(`[data-open="${day}"]`).click();
    await page.waitForSelector('.sheet');
    assert.equal(await sheet.locator('.suffix-mark').count(), 0, '選ぶまでは印なし');
    assert.equal(await sheet.locator('[data-suffix-digit]').count(), 10, '0〜9');

    // 1. 差枚の一覧（TOP50）で末尾7を選ぶ。
    await sheet.locator('[data-suffix-digit="7"]').click();
    assert.equal(await sheet.locator('[data-suffix-digit="7"]').getAttribute('aria-pressed'), 'true');
    assert.deepEqual(await markedRacks(), ['17番', '27番'], 'TOP50の末尾7の台番に印');
    assert.equal(await sheet.getByRole('button', {name: '末尾7の印を消す'}).innerText(), '末尾7 ×');
    assert.ok(await overflow() <= 0, `横にはみ出す（${width}px、末尾を選んだ日の画面）`);
    await shot('suffix-day');

    // 2. 同じ店・同じ日の機種の台一覧へ引き継ぐ（台は全部出したまま）。
    await sheet.locator('.list button.row', {hasText: '17番'}).first().click();
    await sheet.locator('#sheet-title', {hasText: '主力'}).waitFor();
    const rackList = (await sheet.locator('.list .machine').allInnerTexts()).map(t => t.replace(/末\d/, '').trim());
    assert.deepEqual(rackList, ['1番', '2番', '3番', '4番', '5番', '17番'], '全台を出したまま');
    assert.deepEqual(await markedRacks(), ['17番']);
    assert.ok(await overflow() <= 0, `横にはみ出す（${width}px、機種の台一覧）`);
    await shot('suffix-machine');

    // 3. 機種の台一覧の「末尾7 ×」で解除。戻っても解除のまま。
    await sheet.getByRole('button', {name: '末尾7の印を消す'}).click();
    assert.equal(await sheet.locator('.suffix-mark').count(), 0);
    await page.getByRole('button', {name: '‹ 戻る'}).click();
    assert.equal(await sheet.locator('.suffix-mark').count(), 0);
    assert.equal(await sheet.locator('[aria-pressed="true"]').count(), 0);

    // 4. 全機種の台一覧にも引き継ぐ。日付を変えると解除。
    await sheet.locator('[data-suffix-digit="7"]').click();
    await sheet.locator('button.row', {hasText: '全機種の台一覧を見る'}).click();
    await sheet.locator('#sheet-title', {hasText: '全機種の台一覧'}).waitFor();
    assert.deepEqual(await markedRacks(), ['17番', '27番']);
    await page.getByRole('button', {name: '‹ 戻る'}).click();
    await page.getByRole('button', {name: '前の日'}).click();
    await sheet.locator('#sheet-title', {hasText: '10月9日'}).waitFor();
    assert.equal(await sheet.locator('.suffix-mark').count(), 0, '日付を変えたら解除');
    await page.getByRole('button', {name: '次の日'}).click();
    await sheet.locator('#sheet-title', {hasText: '10月10日'}).waitFor();
    assert.equal(await sheet.locator('.suffix-mark').count(), 0, '元の日に戻っても解除のまま');

    assert.deepEqual(errors, []);
    await context.close();
  }
  console.log('share suffix mark browser OK');
} finally {
  await browser.close();
  server.close();
}
