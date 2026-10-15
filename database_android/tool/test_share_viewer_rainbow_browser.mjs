// 共有ページの🌈（2026-10-11 利用者「この虹マークを付けるだけの機能なら共有の方にもつけたい」「共有の方にも店舗別の
// バラエティ一覧つけて同じようにしたい」、2026-10-12「見やすい方法を」→「AとBを切り替え」「幸町のバラエティは1台機種限定」
// 「全部に日付送りが欲しい」、RAINBOW.md「共有ページから付ける」）を隔離ブラウザで開く。
// 「バラエティ🌈」：幸町は1台だけの機種。表（台×7日、マスを押して付け外し、空き日数）と空き順（最後の🌈から長い台が上）を
// 切り替え（端末に覚える）。上に固定した帯の日付送り（下まで送ったままでも）。台のデータからも付け外し。{file: 'rainbow', marks}
// をPOST。ほかの端末の🌈（?file=rainbow）も出す。開き直しても残る。320/393pxではみ出さない。
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
// SHARE_PUBLIC_URL があれば、公開した共有ページに対して試す（公開後の確認）。
const pageUrl = process.env.SHARE_PUBLIC_URL || `http://127.0.0.1:${server.address().port}/share/index.html`;

const records = [];
for (const day of ['2026-10-09', '2026-10-10']) {
  const at = (rack, machine, games, extra = {}) => records.push({store: 'saiwaichou', day, machine, rack, games, bb: 5, rb: 5, jo_net: 100, ...extra});
  for (let rack = 1; rack <= 4; rack++) at(rack, '主力', 4000);
  at(50, 'ハナハナ', 3000);
  at(51, 'ハナハナ', 3000);                          // 幸町では2台の機種はバラエティ🌈に入れない
  at(1201, '無職転生', day === '2026-10-10' ? 5000 : 300,
    day === '2026-10-09' ? {rainbow: true, rainbow_at: '2026-10-09T23:00:00.123456+09:00'} : {});
  at(1202, '頭文字D', 800);
  at(1203, day === '2026-10-10' ? '新バラエティ' : '旧バラエティ', 1200);
}
const responses = {
  '': {format: 'database-backup', version: 1, exported_at: '2026-10-10T23:00:00+09:00', records},
  pscube: {format: 'pscube-viewer', version: 1, records: []},
  events: {format: 'database-events', version: 1, kind: 'meruhen', events: []},
  'pscube-events': {format: 'database-events', version: 1, kind: 'pscube', events: []},
  // ほかの端末で 1202番台（10/10）に付けた🌈。
  rainbow: {format: 'database-rainbow', version: 1, marks: [
    {store: 'saiwaichou', day: '2026-10-10', rack: 1202, on: true, updated_at: '2026-10-11T01:00:00.000Z'}]},
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
    // 🌈の記録は本日（開いた日）を右端にして開く（2026-10-16）。ここでは本日＝最新の記録の日（10/10 正午）。
    await page.clock.setFixedTime(new Date('2026-10-10T03:00:00Z'));
    await page.goto(`${pageUrl}#s=${id}`);
    await page.waitForSelector('.grid');
    const open = async () => {
      await page.getByRole('button', {name: 'バラエティ🌈', exact: true}).click();
      await page.waitForSelector('.sheet');
    };
    await open();
    const sheet = page.locator('.sheet');
    // 幸町の初回は過去7日。従来の表・付け外しも切り替えて確認する。
    await page.getByRole('button', {name: '🌈の記録', exact: true}).click();
    const text = async () => (await sheet.innerText()).replace(/\s+/g, ' ');
    const cell = (rack, md, verb) => sheet.getByRole('button', {name: `${rack}番台 ${md}の🌈${verb}`});
    const waitPosts = async (n) => { for (let i = 0; i < 40 && posts.length < n; i++) await page.waitForTimeout(100); };

    // 表（初めは表）：幸町は1台だけの機種の 1201・1202・1203。ハナハナ（2台）・主力は出さない。
    assert.equal(await page.locator('.sheet-head .head-title').innerText(), 'バラエティ🌈一覧');
    assert.match(await text(), /スーパーメルヘンワールド幸町・記録のそろった最新の日に1台だけの機種の台（入れ替えは自動で変わります）。3台・10月10日（土）（本日）の🌈 1台/);
    assert.deepEqual(await sheet.locator('.rotation .who .num').allInnerTexts(), ['1201', '1202', '1203']);
    assert.ok(await cell(1201, '10/9', 'を外す').isVisible(), '10/9に付いている（PC）');
    assert.ok(await cell(1202, '10/10', 'を外す').isVisible(), 'ほかの端末の🌈');
    assert.equal(await sheet.locator('.rotation .r').nth(1).locator('.gap').innerText(), '1日', '1201：最後の🌈から1日');
    // RAINBOW_SHOTS（フォルダ）があれば、見た目の確認用に画面を残す。
    const shot = (name) => (process.env.RAINBOW_SHOTS ? page.screenshot({path: `${process.env.RAINBOW_SHOTS}/${name}-${width}.png`}) : null);
    await shot('grid');
    // マスを押すと付く（POST）。
    await cell(1201, '10/10', 'を付ける').click();
    await waitPosts(1);
    assert.deepEqual(posts[0].marks.map(m => [m.rack, m.day, m.on]), [[1201, '2026-10-10', true]]);
    assert.ok(await cell(1201, '10/10', 'を外す').isVisible());
    const overflow = await sheet.evaluate(e => e.scrollWidth - e.clientWidth);
    assert.ok(overflow <= 0, `表が横にはみ出す（${width}px、${overflow}px）`);

    // 日付送り（上に固定）：下まで送ったままでも前の日へ。位置はそのまま。
    await sheet.evaluate(e => { e.scrollTop = e.scrollHeight; });
    const scrolled = await sheet.evaluate(e => e.scrollTop);
    await page.getByRole('button', {name: '前の日'}).click();
    assert.equal(await page.locator('select[data-sheet-day]').inputValue(), '2026-10-09');
    assert.ok(await page.getByRole('button', {name: '前の日'}).isDisabled(), 'いちばん古い日');
    assert.equal(await sheet.evaluate(e => e.scrollTop), scrolled, 'スクロール位置はそのまま');
    await page.getByRole('button', {name: '次の日'}).click();
    assert.equal(await page.locator('select[data-sheet-day]').inputValue(), '2026-10-10');

    // 空き順：一度も無い 1203 が上。覚える。
    await sheet.getByLabel('並べ方', {exact: true}).selectOption('gap');
    assert.equal(await page.getByRole('button', {name: '空き順', exact: true}).count(), 0);
    assert.deepEqual(await sheet.locator('.list .rack').allInnerTexts(), ['1203番', '1201番🌈', '1202番🌈']);
    assert.match(await text(), /1203番 新バラエティ なし/);
    // 「🌈 外す」の文字は白（2026-10-12、ボタンの大きさの名前が一覧の小さい文字の指定とぶつかり、灰色で薄く見えていた）。
    assert.equal(await sheet.locator('.mark-btn.pill-blue').first().evaluate(e => getComputedStyle(e).color), 'rgb(255, 255, 255)');
    await shot('gap');
    // 行を押すと台のデータ。そこから付ける。台のデータの日付送りは同じ機種の日だけ（10/9は旧バラエティ）。
    await sheet.locator('button.row', {hasText: '1203番'}).click();
    assert.equal(await page.locator('#sheet-title').innerText(), '1203番台');
    assert.ok(await page.getByRole('button', {name: '前の日'}).isDisabled());
    await sheet.getByRole('button', {name: '1203番台の🌈 付ける'}).click();
    await waitPosts(2);
    assert.ok(posts[1].marks.some(m => m.rack === 1203 && m.on === true));
    await page.locator('#sheet-title', {hasText: '1203番台 🌈'}).waitFor();
    await page.getByRole('button', {name: '‹ 戻る'}).click();
    assert.equal(await sheet.locator('.list .rack').first().innerText(), '1201番🌈', '戻ると空き順の並び直し');

    // 開き直しても、見せ方（空き順）とこの端末の🌈は残る（共有ファイルが古いままでも）。
    await page.getByRole('button', {name: '閉じる'}).click();
    await page.reload();
    await page.waitForSelector('.grid');
    await open();
    assert.equal(await page.getByRole('button', {name: '🌈の記録', exact: true}).getAttribute('aria-pressed'), 'true');
    assert.equal(await sheet.getByLabel('並べ方', {exact: true}).inputValue(), 'gap');
    assert.match(await text(), /1203番🌈/);
    await page.getByRole('button', {name: '🌈の記録', exact: true}).click();
    await sheet.getByLabel('並べ方', {exact: true}).selectOption('grid');
    assert.ok(await cell(1203, '10/10', 'を外す').isVisible());
    await page.getByRole('button', {name: '閉じる'}).click();
    assert.deepEqual(errors, []);
    await context.close();
  }

  // 2026-10-16 利用者「青い枠で囲まれてるところが本日みたいな雰囲気でてしまうので、本日＝開いている日、見ている日に」。
  // 本日（10/11）の数値が未取得でも、🌈の記録は本日を右端・青枠にして開き、幸町は取り込み前の印を付け外しできる。
  {
    const context = await browser.newContext({viewport: {width: 393, height: 860}});
    const posts = [];
    await context.route('https://script.google.com/**', route => {
      const request = route.request();
      const headers = {'access-control-allow-origin': '*'};
      if (request.method() === 'POST') {
        posts.push(JSON.parse(request.postData()));
        return route.fulfill({status: 200, contentType: 'application/json', headers, body: JSON.stringify({ok: true})});
      }
      const file = new URL(request.url()).searchParams.get('file') ?? '';
      route.fulfill({status: 200, contentType: 'application/json', headers, body: JSON.stringify(responses[file] ?? {error: 'no'})});
    });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.clock.setFixedTime(new Date('2026-10-11T03:00:00Z'));
    await page.goto(`${pageUrl}#s=${id}`);
    await page.waitForSelector('.grid');
    await page.getByRole('button', {name: 'バラエティ🌈', exact: true}).click();
    await page.waitForSelector('.sheet');
    const sheet = page.locator('.sheet');
    const text = async () => (await sheet.innerText()).replace(/\s+/g, ' ');
    const cell = (rack, md, verb) => sheet.getByRole('button', {name: `${rack}番台 ${md}の🌈${verb}`});
    const day = () => page.locator('select[data-sheet-day]').inputValue();
    await page.getByRole('button', {name: '🌈の記録', exact: true}).click();
    assert.equal(await day(), '2026-10-11', '本日（開いた日）で開く');
    assert.equal(await sheet.locator('.rotation .head .d.today').innerText(), '11', '青枠の列＝本日');
    assert.match(await text(), /10月11日（日）（本日）の🌈 0台/);
    assert.match(await text(), /本日分の数値はまだ取り込まれていません。🌈は取り込み前でも付けられ/);
    assert.match(await cell(1201, '10/11', 'を付ける').getAttribute('class'), /\btoday\b/);
    await cell(1201, '10/11', 'を付ける').click();
    for (let i = 0; i < 40 && !posts.length; i++) await page.waitForTimeout(100);
    assert.deepEqual(posts[0].marks.map(m => [m.rack, m.day, m.on]), [[1201, '2026-10-11', true]]);
    assert.ok(await cell(1201, '10/11', 'を外す').isVisible());
    assert.equal(await sheet.locator('.rotation .r').nth(1).locator('.gap').innerText(), '当日');
    // 台番号は、本日が未取得でもその台の最新の記録（10/10）を開ける。
    await sheet.locator('.rotation .who', {hasText: '1201'}).click();
    assert.equal(await page.locator('#sheet-title').innerText(), '1201番台');
    assert.equal(await day(), '2026-10-10');
    await page.getByRole('button', {name: '‹ 戻る'}).click();
    // 前の日へ送ると、青枠もその日（見ている日）へ。
    await page.getByRole('button', {name: '前の日'}).click();
    assert.equal(await day(), '2026-10-10');
    assert.match(await cell(1202, '10/10', 'を外す').getAttribute('class'), /\btoday\b/);
    // 候補は記録のある日だけ（本日が未取得なら最新の記録の日）。🌈の記録へ戻すと本日。
    await page.getByRole('button', {name: '候補', exact: true}).click();
    assert.equal(await day(), '2026-10-10');
    await page.getByRole('button', {name: '🌈の記録', exact: true}).click();
    assert.equal(await day(), '2026-10-11');
    // 開いたまま日付が変わったら、前の日の列に付けずに本日の列を移す。
    await page.clock.setFixedTime(new Date('2026-10-12T03:00:00Z'));
    await cell(1202, '10/11', 'を付ける').click();
    assert.match(await page.locator('.toast').innerText(), /日付が変わりました。表を確認してから押してください。/);
    assert.equal(await day(), '2026-10-12');
    assert.equal(posts.length, 1, '日付が変わった後の押下は送らない');
    assert.deepEqual(errors, []);
    await context.close();
  }
  console.log('PASS: share viewer バラエティ🌈 (幸町 1-rack machines, grid 7 days / gap order, remembered), one-tap 🌈 posts, pinned date stepping, rack view toggle, kept on reload, 320/393px, grid opens on today (pending marks, date change)');
} finally {
  await browser.close();
  await new Promise(resolve => server.close(resolve));
}
