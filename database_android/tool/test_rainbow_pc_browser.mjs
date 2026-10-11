// PCの取り込みカードの🌈ボタン（確定が出た台の印、2026-10-11。RAINBOW.md）。メルヘンの機種の表・個別台の
// ページで、カードに保存済みの台が並び、押すと付け外しする。サイトの表には手を入れない（表の読み取りが
// 台番号を読めなくなるため）。PCの取り込みカード（browser_import.OVERLAY_JS）を偽のページで動かす。
// 対象サイトへは接続しない（すべて page.route で返す）。
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const overlay = JSON.parse(execFileSync(process.env.PYTHON || 'python', ['-c',
  'import json,browser_import as b; print(json.dumps(b.OVERLAY_JS))'],
  {cwd: new URL('../../database/', import.meta.url), encoding: 'utf8'}));

const HOST = 'https://meruhenworld.pt.teramoba2.com';
const name = encodeURIComponent(encodeURIComponent('Lモンキーターン5CE'));
const tableUrl = `${HOST}/nagamachiminami/standlist_slot/?kind_code=21&machine_name=${name}&target_date=2026-10-10`;
const graphUrl = `${HOST}/nagamachiminami/standgraph/?rack_no=661&target_date=2026-10-10`;
const table = '<table><tr>' + ['台番号', 'BB', 'RB', '総回転数', '合成確率', '前日最終スタート', '最大持玉']
  .map(h => `<th>${h}</th>`).join('') + '</tr>' + [660, 661].map(rack =>
  `<tr><td><a href="/nagamachiminami/standgraph/?rack_no=${rack}&target_date=2026-10-10">${rack}</a></td>` +
  '<td>3</td><td>2</td><td>1500</td><td>1/300</td><td>0</td><td>400</td></tr>').join('') + '</table>';

const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || undefined});
try {
  const page = await browser.newPage({viewport: {width: 900, height: 850}});
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.route('**/*', route => route.fulfill({status: 200, contentType: 'text/html; charset=utf-8',
    body: `<html><head><meta charset="utf-8"></head><body>${table}</body></html>`}));
  const open = async url => {
    await page.goto(url);
    await page.evaluate(() => {
      window.__asked = []; window.__set = [];
      const saved = {660: false, 661: true};
      window.pywebview = {api: {
        retry_page: async () => {}, progress: async () => JSON.stringify({text: ''}),
        machine_status: async () => JSON.stringify({status: []}), save_overlay_layout: async () => true,
        get_auto_capture: async () => ({enabled: false, seconds: 3.5, revision: 1, message: '停止中',
          days: [], target_day: null, direction: 'top', manual_continuation: false}),
        rainbow_racks: async raw => {
          const id = JSON.parse(raw);
          window.__asked.push(id);
          const racks = Object.entries(saved).map(([rack, on]) => ({rack: Number(rack), on}))
            .filter(item => id.rack === null || item.rack === id.rack);
          return JSON.stringify({racks});
        },
        set_rainbow: async raw => {
          const body = JSON.parse(raw);
          window.__set.push(body);
          saved[body.rack] = body.on;
          return JSON.stringify({ok: true, on: body.on, message: `${body.rack}番台に🌈を付けました。`});
        },
      }};
    });
    await page.evaluate(overlay);
  };

  // 機種の表：保存済みの2台が並ぶ（660は＋、661は🌈）。押すと付く。
  await open(tableUrl);
  const box = page.locator('#database-rainbow');
  await box.locator('button').first().waitFor();
  assert.deepEqual(await box.locator('button').allInnerTexts(), ['＋660', '🌈661']);
  const asked = await page.evaluate(() => window.__asked[0]);
  assert.deepEqual([asked.store, asked.day, asked.machine, asked.rack], ['nagamachiminami', '2026-10-10', 'Lモンキーターン5CE', null]);
  await box.locator('button', {hasText: '660'}).click();
  await page.waitForFunction(() => window.__set.length === 1);
  assert.deepEqual(await page.evaluate(() => window.__set[0]), {store: 'nagamachiminami', day: '2026-10-10', rack: 660, on: true});
  assert.equal(await box.locator('button', {hasText: '660'}).innerText(), '🌈660');
  assert.equal(await box.locator('button', {hasText: '660'}).getAttribute('aria-pressed'), 'true');
  assert.match(await page.locator('#database-capture-status').innerText(), /660番台に🌈/);
  // サイトの表はそのまま（表の読み取りは台番号を今までどおり読む）。
  assert.deepEqual(await page.locator('table td:first-child').allInnerTexts(), ['660', '661']);
  await box.locator('button', {hasText: '661'}).click();
  await page.waitForFunction(() => window.__set.length === 2);
  assert.equal((await page.evaluate(() => window.__set[1])).on, false, 'もう一度押すと外す');

  // 個別台のページ：その台だけ。
  await open(graphUrl);
  await box.locator('button').first().waitFor();
  assert.deepEqual(await box.locator('button').allInnerTexts(), ['🌈661']);
  assert.equal(await page.evaluate(() => window.__asked[0].rack), 661);
  assert.deepEqual(errors, []);
  console.log('PASS: PC capture card shows 🌈 buttons for saved racks (table page, rack page) and toggles them; site table untouched');
} finally {
  await browser.close();
}
