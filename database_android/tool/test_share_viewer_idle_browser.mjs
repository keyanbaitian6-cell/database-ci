// 閲覧専用の共有ページの「バラエティの回っていない台」（2026-10-11、閲覧ページと同じ仕様）を隔離ブラウザで開く。
// ボタン→日付・期間・ゲーム数を選ぶ→台を押すとその台のデータ→戻る、選んだ期間・ゲーム数を覚えて開き直しても残る、
// 1279番台の聖闘士星矢（稼働停止）は出さない、狭い画面ではみ出さない、何も送らない（GETだけ）。
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
const pageUrl = process.env.SHARE_PUBLIC_URL || `http://127.0.0.1:${server.address().port}/share/index.html`;

// 幸町、10/1〜10/8（10/4〜5 は記録なし＝サイトが落ちていた日）：主力4台、バラエティのハナハナ（毎日300G）・
// ジャグラー（毎日800G）・聖闘士星矢 1279番台（稼働停止、毎日0G）。
const records = [];
for (const d of [1, 2, 3, 6, 7, 8]) {
  const day = `2026-10-0${d}`;
  for (let rack = 1; rack <= 4; rack++) records.push({store: 'saiwaichou', day, machine: '主力', rack, games: 4000, bb: 20, rb: 10, jo_net: 100});
  records.push({store: 'saiwaichou', day, machine: 'ハナハナ', rack: 50, games: 300, bb: 1, rb: 1, max_hold: 120, jo_net: -250});
  records.push({store: 'saiwaichou', day, machine: 'ジャグラー', rack: 60, games: 800, bb: 2, rb: 2, jo_net: -500});
  records.push({store: 'saiwaichou', day, machine: 'L聖闘士星矢海皇覚醒ED', rack: 1279, games: 0, bb: 0, rb: 0, jo_net: 0});
}
const responses = {
  '': {format: 'database-backup', version: 1, exported_at: '2026-10-08T23:00:00+09:00', records},
  pscube: {format: 'pscube-viewer', version: 1, records: []},
  events: {format: 'database-events', version: 1, kind: 'meruhen', events: []},
  'pscube-events': {format: 'database-events', version: 1, kind: 'pscube', events: []},
};
const id = 'AKfycbTEST' + 'x'.repeat(40);

const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
try {
  for (const width of [320, 393]) {
    const context = await browser.newContext({viewport: {width, height: 860}});
    const methods = [];
    await context.route('https://script.google.com/**', route => {
      methods.push(route.request().method());
      const file = new URL(route.request().url()).searchParams.get('file') ?? '';
      route.fulfill({status: 200, contentType: 'application/json', headers: {'access-control-allow-origin': '*'},
        body: JSON.stringify(responses[file] ?? {error: 'no'})});
    });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(`${pageUrl}#s=${id}`);
    await page.waitForSelector('.grid');
    const open = async () => {
      await page.getByRole('button', {name: 'バラエティの回っていない台'}).click();
      await page.waitForSelector('.sheet');
    };
    await open();
    const sheet = page.locator('.sheet');
    // 既定：最新の日（10/8）・7日以上・1,000G未満 → ハナハナ・ジャグラー（10/1〜10/8 の8日間、記録のある日6日）。
    assert.equal(await page.locator('select[data-idle="day"]').inputValue(), '2026-10-08');
    assert.equal(await page.locator('select[data-idle="minDays"]').inputValue(), '7');
    assert.equal(await page.locator('select[data-idle="games"]').inputValue(), '1000');
    assert.match(await sheet.innerText(), /2台/);
    assert.match(await sheet.innerText(), /50番\s*ハナハナ\s*8日間 1,000G未満（10\/1〜、記録のある日6日）・最多300G/);
    assert.ok(!/聖闘士星矢|1279/.test(await sheet.innerText()), '1279番台（稼働停止）は出さない');
    // 500G未満にすると、800Gのジャグラーは外れる。
    await page.locator('select[data-idle="games"]').selectOption('500');
    assert.match(await sheet.innerText(), /1台/);
    assert.ok(!/ジャグラー/.test(await sheet.innerText()));
    // 台を押すとその台のデータ。戻ると選んだ条件のまま。
    await page.locator('.sheet .row', {hasText: '50番'}).click();
    assert.equal(await page.locator('#sheet-title').innerText(), '50番台');
    assert.match(await sheet.innerText(), /差枚\s*-250/);
    assert.match(await sheet.innerText(), /最大持玉\s*120/);
    await page.getByRole('button', {name: '‹ 戻る'}).click();
    assert.equal(await page.locator('select[data-idle="games"]').inputValue(), '500');
    // 日付を戻すと数え直す（10/3 では10/1〜10/3 の3日間なので、7日以上には当たらない）。
    await page.locator('select[data-idle="day"]').selectOption('2026-10-03');
    assert.match(await sheet.innerText(), /当てはまる台はありません/);
    await page.locator('select[data-idle="minDays"]').selectOption('3');
    assert.match(await sheet.innerText(), /3日間 500G未満（10\/1〜）/);
    const overflow = await sheet.evaluate(e => e.scrollWidth - e.clientWidth);
    assert.ok(overflow <= 0, `シートが横にはみ出す（${width}px、${overflow}px）`);
    // 開き直しても期間・ゲーム数は覚えている（日付は最新に戻る）。
    await page.getByRole('button', {name: '閉じる'}).click();
    await page.reload();
    await page.waitForSelector('.grid');
    await open();
    assert.deepEqual(await Promise.all(['day', 'minDays', 'games'].map(k => page.locator(`select[data-idle="${k}"]`).inputValue())),
      ['2026-10-08', '3', '500']);
    await page.getByRole('button', {name: '閉じる'}).click();
    assert.deepEqual([...new Set(methods)], ['GET'], '読むだけ（POSTしない）');
    assert.deepEqual(errors, []);
    await context.close();
  }
  console.log('PASS: share viewer idle variety racks (day/period/games, rack data, remembered, 1279 hidden), 320/393px');
} finally {
  await browser.close();
  await new Promise(resolve => server.close(resolve));
}
