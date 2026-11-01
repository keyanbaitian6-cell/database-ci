// 共有カレンダーの「全機種の台一覧」（2026-11-01 利用者「バラエティ以外の他の機種を一覧でだしつつ、機種だけみたいときは
// （プルダウン）で切り替えられるように」「媒体は全て」「共有カレンダーには採点はいらないよ」）を隔離ブラウザで開く。
// 日のまとめから開き、バラエティ🌈の機種（幸町は1台だけの機種）を入れない・機種のプルダウンで絞る・回転数／差枚で並べ替える・
// 並べ方を覚える・点数を出さない・押した台を取り違えない・320/393pxではみ出さない。Googleのスクリプトは偽物（route）。
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

const day = '2026-10-10';
const records = [];
const at = (rack, machine, games, extra = {}) => records.push({store: 'saiwaichou', day, machine, rack, games, bb: 5, rb: 5, ...extra});
at(1, '主力', 4000, {jo_net: 300});
at(2, '主力', 900, {jo_net: -800});
at(3, '主力', 6000, {jo_net: 1500});
at(4, '主力', 2500);                       // 差枚なし（並べ替えでは最後）
at(50, 'ハナハナ', 3000, {jo_net: 100, rainbow: true});
at(51, 'ハナハナ', 7000, {jo_net: -200});  // 幸町では2台の機種は全機種の一覧に入る（バラエティ🌈は1台だけの機種）
at(1201, '無職転生', 5000, {jo_net: 900}); // 1台だけの機種＝バラエティ🌈。入れない
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
    const open = async () => {
      await page.locator(`[data-open="${day}"]`).click();
      await page.waitForSelector('.sheet');
      await sheet.locator('button.row', {hasText: '全機種の台一覧を見る'}).click();
      await sheet.locator('#sheet-title', {hasText: '全機種の台一覧'}).waitFor();
    };
    const racks = async () => (await sheet.locator('.list .machine').allInnerTexts()).map(t => t.replace('🌈', '').trim());
    const text = async () => (await sheet.innerText()).replace(/\s+/g, ' ');

    await open();
    assert.equal(await page.locator('.sheet-head .head-title').innerText(), '全機種の台一覧');
    assert.deepEqual(await racks(), ['1番', '2番', '3番', '4番', '50番', '51番'], 'バラエティ🌈（1台だけの機種）は入れない');
    assert.match(await text(), /2機種・6台/);
    assert.match(await text(), /50番🌈/, '🌈の印は出す');
    assert.doesNotMatch(await text(), /点/, '共有カレンダーには点数を出さない');
    const overflow = async () => sheet.evaluate(e => e.scrollWidth - e.clientWidth);
    assert.ok(await overflow() <= 0, `横にはみ出す（${width}px）`);
    if (process.env.ALL_RACKS_SHOTS) await page.screenshot({path: `${process.env.ALL_RACKS_SHOTS}/all-racks-${width}.png`});

    await sheet.getByLabel('並べ方', {exact: true}).selectOption('games-desc');
    assert.deepEqual(await racks(), ['51番', '3番', '1番', '50番', '4番', '2番']);
    await sheet.getByLabel('並べ方', {exact: true}).selectOption('net-desc');
    assert.deepEqual(await racks(), ['3番', '1番', '50番', '51番', '2番', '4番'], '差枚の無い台は最後');
    await sheet.getByLabel('並べ方', {exact: true}).selectOption('net-asc');
    assert.deepEqual(await racks(), ['2番', '51番', '50番', '1番', '3番', '4番'], '少ない順でも差枚の無い台は最後');
    // 機種で絞る（並べ方はそのまま）。
    await sheet.getByLabel('機種', {exact: true}).selectOption('主力');
    assert.deepEqual(await racks(), ['2番', '1番', '3番', '4番']);
    assert.match(await text(), /主力・4台/);
    // 押した台を取り違えない。戻ると選んだ機種・並べ方のまま。
    await sheet.locator('button.row', {hasText: '3番'}).click();
    assert.equal(await page.locator('#sheet-title').innerText(), '3番台');
    await page.getByRole('button', {name: '‹ 戻る'}).click();
    assert.equal(await sheet.getByLabel('機種', {exact: true}).inputValue(), '主力');
    assert.equal(await sheet.getByLabel('並べ方', {exact: true}).inputValue(), 'net-asc');
    await sheet.getByLabel('機種', {exact: true}).selectOption('');
    assert.equal((await racks()).length, 6);
    assert.ok(await overflow() <= 0, `絞り込み後も横にはみ出さない（${width}px）`);
    // 並べ方は端末に覚える（機種の絞り込みは開き直すと「すべて」）。
    await page.getByRole('button', {name: '‹ 戻る'}).click();
    await page.locator('[data-close]').click();
    await open();
    assert.equal(await sheet.getByLabel('並べ方', {exact: true}).inputValue(), 'net-asc');
    assert.equal(await sheet.getByLabel('機種', {exact: true}).inputValue(), '');
    assert.deepEqual(errors, []);
    await context.close();
  }
  console.log('share all racks browser OK');
} finally {
  await browser.close();
  server.close();
}
