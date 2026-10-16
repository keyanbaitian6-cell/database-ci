// メルヘンPC：台ページの曲線は描けていても、グラフ内の数字（総回転数・BIG・REG・最大持玉）が
// 少し遅れて入ることがある（2026-10-16、幸町で「734番台の数値を確認できません」が多発。
// 空のまま読んだ送信データを確認）。自動取り込みは数字が空のあいだ送らずに待ち、入ったら送る。
// 入らないままなら20秒で、これまでどおり送る。PCの取り込みカード（browser_import.OVERLAY_JS）を
// 偽のページで動かす。対象サイトへは接続しない（すべて page.route で返す）。
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const overlay = JSON.parse(execFileSync(process.env.PYTHON || 'python', ['-c',
  'import json,browser_import as b; print(json.dumps(b.OVERLAY_JS))'],
  {cwd: new URL('../../database/', import.meta.url), encoding: 'utf8'}));

const HOST = 'https://meruhenworld.pt.teramoba2.com';
const graphUrl = rack => `${HOST}/saiwaichou/standgraph?dai_hall_id=821&rack_no=${rack}&target_date=2026-10-16`;
const svg = numbers => '<svg class="today" viewBox="0 0 300 150" width="300" height="150">' +
  '<g class="path-slump"><path d="M0 75 L30 70 L60 80 L90 65 L120 55 L150 70 L180 60 L210 50 L240 45 L270 40 L300 35"/></g>' +
  '<g class="back-line-middle"><line y1="75"/></g>' +
  ['soukaiten', 'big', 'reg', 'art', 'max_mochidama']
    .map((name, i) => `<text class="info_${name}">${numbers ? numbers[i] : ''}</text>`).join('') + '</svg>';

const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || undefined});
try {
  const page = await browser.newPage({viewport: {width: 900, height: 850}});
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  let content = svg(null);
  await page.route('**/*', route => route.fulfill({status: 200, contentType: 'text/html; charset=utf-8',
    body: `<html><head><meta charset="utf-8"></head><body><h3>734番台</h3>${content}</body></html>`}));
  const open = async url => {
    await page.goto(url);
    await page.evaluate(() => {
      window.pywebview = {api: {
        retry_page: async () => {}, progress: async () => JSON.stringify({text: ''}),
        machine_status: async () => JSON.stringify({status: []}), save_overlay_layout: async () => true,
        get_auto_capture: async () => ({enabled: true, seconds: 3.5, revision: 1, message: 'ON',
          days: [], target_day: '2026-10-16', direction: 'top', manual_continuation: false}),
        submit_graph: async () => {},
      }};
    });
    await page.evaluate(overlay);
    await page.waitForFunction(() => document.getElementById('database-auto-toggle'));
  };
  const probe = () => page.evaluate(() => window.__databaseAutoProbe());

  // 数字が4つとも空：送らずに待つ（Python 側は「ON・待機：…」と表示して次の間隔で読み直す）。
  await open(graphUrl(734));
  const waiting = await probe();
  assert.equal(waiting.kind, undefined, JSON.stringify(waiting));
  assert.match(waiting.error, /台の数値.*表示待ち/);
  assert.match(await probe().then(p => p.error), /表示待ち/, '読み直しても空なら待ち続ける');

  // 同じページで数字が入ったら、その数字つきで送る。
  await page.evaluate(() => {
    const values = ['1348', '12', '6', '', '859'];
    ['soukaiten', 'big', 'reg', 'art', 'max_mochidama'].forEach((name, i) => {
      document.querySelector('.info_' + name).textContent = values[i];
    });
  });
  const ready = await probe();
  assert.equal(ready.kind, 'graph', JSON.stringify(ready));
  const payload = JSON.parse(ready.raw);
  assert.deepEqual([payload.rack, payload.games, payload.bb, payload.rb, payload.max_hold], [734, 1348, 12, 6, 859]);

  // 入らないままの台で止まり続けない：同じページで20秒たっても空なら、これまでどおり送る。
  content = svg(null);
  await open(graphUrl(735));
  assert.match((await probe()).error, /表示待ち/);
  await page.evaluate(() => { const now = Date.now; Date.now = () => now() + 20001; });
  const timedOut = await probe();
  assert.equal(timedOut.kind, 'graph', JSON.stringify(timedOut));
  assert.equal(JSON.parse(timedOut.raw).max_hold, null);

  // 最初から数字の入っているページは待たずに送る（これまでどおり）。
  content = svg(['3496', '21', '20', '', '833']);
  await open(graphUrl(736));
  assert.equal((await probe()).kind, 'graph');
  assert.deepEqual(errors, []);
  console.log('PASS: Meruhen PC auto capture waits while a rack graph shows its numbers empty, sends once filled, gives up waiting after 20s');
} finally {
  await browser.close();
}
