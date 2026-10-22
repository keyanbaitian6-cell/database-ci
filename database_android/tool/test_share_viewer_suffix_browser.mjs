// 閲覧専用の共有ページの「末尾別データまとめ」（2026-10-12 利用者「幸町にもつくってもらうだけでいい」）を隔離ブラウザで開く。
// 幸町とP-STATIONにボタン（長町南には出さない）→選んだ日の末尾順位（平均差枚の順）→比較期間→末尾を押すとその末尾の台→台のデータ、日別の首位から
// その日へ、狭い画面ではみ出さない、何も送らない（GETだけ）。
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

// 幸町：10/10 は末尾0が+1000、末尾4が+500、ほかは-100。10/9 は末尾7だけ+800。長町南にも記録がある（ボタンは出さない）。
const records = [];
for (let rack = 1000; rack < 1030; rack++) {
  const tail = rack % 10;
  records.push({store: 'saiwaichou', day: '2026-10-10', machine: `機種${tail}`, rack, games: 3000, bb: 10, rb: 5,
    jo_net: tail === 0 ? 1000 : tail === 4 ? 500 : -100});
  records.push({store: 'saiwaichou', day: '2026-10-09', machine: `機種${tail}`, rack, games: 2000, bb: 5, rb: 5,
    jo_net: tail === 7 ? 800 : -200});
}
records.push({store: 'nagamachiminami', day: '2026-10-10', machine: '長町', rack: 10, games: 1000, bb: 1, rb: 1, jo_net: 0});
const responses = {
  '': {format: 'database-backup', version: 1, exported_at: '2026-10-10T23:00:00+09:00', records},
  // P-STATION（P’s CUBE、20スロ）：末尾8が+600、ほかは-50。
  pscube: {format: 'pscube-viewer', version: 1, records: Array.from({length: 20}, (_, i) => ({
    store: 'c740601', rate: '20', day: '2026-10-10', machine: `P機種${i % 10}`, rack: 500 + i, games: 2500, bb: 5, rb: 5, my: 100,
    net_medals: (500 + i) % 10 === 8 ? 600 : -50}))},
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
    // 長町南にはボタンを出さない。
    await page.locator('[data-store="nagamachiminami"]').click();
    assert.equal(await page.locator('[data-suffix-open]').count(), 0, '長町南には出さない');
    await page.locator('[data-store="saiwaichou"]').click();
    await page.getByRole('button', {name: '末尾別データまとめ'}).click();
    await page.waitForSelector('.sheet');
    const sheet = page.locator('.sheet');
    assert.equal(await page.locator('.head-title').innerText(), '末尾別データまとめ');
    assert.equal(await page.locator('select[data-sheet-day]').inputValue(), '2026-10-10');
    const text = await sheet.innerText();
    assert.match(text, /平均差枚の首位：末尾0/);
    assert.match(text, /1位\s*末尾0[\s\S]*\+1,000[\s\S]*2位\s*末尾4[\s\S]*\+500/);
    assert.match(text, /ゾロ目（下2桁が00・11・22・33・44・55・66・77・88・99/);
    // 過去7日：末尾0は(1000-200)/2=+400、末尾7は(-100+800)/2=+350、末尾4は(500-200)/2=+150。
    await page.locator('select[data-suffix-period]').selectOption('week');
    assert.match(await sheet.innerText(), /1位\s*末尾0[\s\S]*\+400[\s\S]*2位\s*末尾7[\s\S]*\+350/);
    // 末尾を押すとその末尾の台（日ごと）→ 台を押すとその台のデータ → 戻る。
    await page.locator('.sheet .row[data-suffix="7"]').first().click();
    assert.equal(await page.locator('.head-title').innerText(), '末尾7の内訳');
    assert.match(await sheet.innerText(), /3台・2日・6件/);
    // 内訳の並び（日ごと）の順で前後の台へ（2026-10-22）。押す前に画面の並びを読んでおく。
    const shown = (await page.locator('.sheet .row[data-suffix-rack]').allInnerTexts()).map(t => /(\d+)番/.exec(t)[1]);
    const at = shown.indexOf('1007');
    await page.locator('.sheet .row', {hasText: '1007番'}).first().click();
    assert.equal(await page.locator('#sheet-title').innerText(), '1007番台');
    assert.equal(await page.locator('[data-rack-step="-1"]').isDisabled(), at === 0, '先頭の台に前は無い');
    await page.locator('[data-rack-step="1"]').click();
    assert.equal(await page.locator('#sheet-title').innerText(), `${shown[at + 1]}番台`, '内訳の次の行の台');
    assert.match(await page.locator('[data-rack-step="-1"]').innerText(), /前の台（1007番）/);
    await page.locator('[data-back]').click();
    await page.locator('[data-back]').click();
    assert.equal(await page.locator('.head-title').innerText(), '末尾別データまとめ');
    // 日別の首位から、その日の末尾順位へ（10/9 は末尾7）。
    await page.locator('.sheet .row[data-suffix-day="2026-10-09"]').click();
    assert.match(await sheet.innerText(), /平均差枚の首位：末尾7/);
    // P-STATION にも出す（2026-10-12「共有のP-stationの方にも末尾データほしいです」）。末尾4・9は無い。
    await page.locator('[data-back]').click();
    await page.locator('[data-close]').click();
    await page.locator('[data-store="pscube:c740601:20"]').click();
    await page.getByRole('button', {name: '末尾別データまとめ'}).click();
    await page.waitForSelector('.sheet');
    const ps = await page.locator('.sheet').innerText();
    assert.match(ps, /P-STATION（20スロ）・末尾0・1・2・3・5・6・7・8とゾロ目（下2桁が00・11・22・33・55・66・77・88/);
    assert.match(ps, /平均差枚の首位：末尾8/);
    assert.match(ps, /サイトの差枚/);
    const overflow = await page.evaluate(() => {
      const s = document.querySelector('.sheet');
      return Math.max(document.documentElement.scrollWidth - window.innerWidth, s.scrollWidth - s.clientWidth);
    });
    assert.ok(overflow <= 0, `${width}px で横にはみ出さない（${overflow}px）`);
    assert.deepEqual([...new Set(methods)], ['GET'], '何も送らない');
    assert.deepEqual(errors, []);
    await context.close();
  }
  console.log('OK: 共有ページの末尾別データまとめ（幸町・P-STATION・平均差枚の順・期間・末尾の台・日別の首位・320/393px）');
} finally {
  await browser.close();
  server.close();
}
