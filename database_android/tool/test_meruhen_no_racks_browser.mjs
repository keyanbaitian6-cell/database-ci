// メルヘンPC：機種の表の代わりにサイトが「該当する台情報が見つかりませんでした」を出す機種は、
// その日は飛ばして機種一覧へ戻る（2026-10-11）。PCの取り込みカード（browser_import.OVERLAY_JS）を
// 偽のページで動かす。対象サイトへは接続しない（すべて page.route で返す）。
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const overlay = JSON.parse(execFileSync(process.env.PYTHON || 'python', ['-c',
  'import json,browser_import as b; print(json.dumps(b.OVERLAY_JS))'],
  {cwd: new URL('../../database/', import.meta.url), encoding: 'utf8'}));

const HOST = 'https://meruhenworld.pt.teramoba2.com';
const name = encodeURIComponent(encodeURIComponent('SﾊｲﾊﾟｰﾗｯｼｭSLC8'));
const tableUrl = day => `${HOST}/nagamachiminami/standlist_slot/?kind_code=21&machine_name=${name}` + (day ? `&target_date=${day}` : '');
// 実サイトの空のページ（2026-10-11 の画面）：見出しと検索欄はあるが、台の表は無い。
const empty = '<div class="title">個別台情報一覧</div><p>該当する台情報が見つかりませんでした。</p>' +
  '<table><tr><td>台番号検索</td><td><input></td></tr></table>';
const table = '<table><tr>' + ['台番号', 'BB', 'RB', '総回転数', '合成確率', '前日最終スタート', '最大持玉']
  .map(h => `<th>${h}</th>`).join('') + '</tr><tr><td><a href="/nagamachiminami/standgraph/?rack_no=660&target_date=2026-10-07">660</a></td>' +
  '<td>3</td><td>2</td><td>1500</td><td>1/300</td><td>0</td><td>400</td></tr></table>';

const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || undefined});
try {
  const page = await browser.newPage({viewport: {width: 900, height: 850}});
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  let content = empty;
  await page.route('**/*', route => route.fulfill({status: 200, contentType: 'text/html; charset=utf-8',
    body: `<html><head><meta charset="utf-8"></head><body>${content}</body></html>`}));
  const open = async (url, auto, tablesOnly=false) => {
    await page.goto(url);
    await page.evaluate(({auto,tablesOnly}) => {
      window.__skipped = null;
      window.pywebview = {api: {
        retry_page: async () => {}, progress: async () => JSON.stringify({text: ''}),
        machine_status: async () => JSON.stringify({status: []}), save_overlay_layout: async () => true,
        get_auto_capture: async () => ({enabled: auto, seconds: 3.5, revision: 1, message: auto ? 'ON' : '停止中',
          days: [], target_day: '2026-10-10', direction: 'bottom', manual_continuation: false,tables_only:tablesOnly}),
        submit_table: async () => { window.__submitted = true; },
        next_ungraphed_rack: async () => JSON.stringify({url:'https://meruhenworld.pt.teramoba2.com/nagamachiminami/rack_info_kt/?kind_code=21',reason:'tables_only',message:'表だけ取り込みます。'}),
        skip_machine_without_racks: async raw => {
          window.__skipped = JSON.parse(raw);
          return JSON.stringify({url: 'https://meruhenworld.pt.teramoba2.com/nagamachiminami/rack_info_kt/?kind_code=21#database_next_machine=1&database_day=2026-10-10',
            message: '10/10のSﾊｲﾊﾟｰﾗｯｼｭSLC8は、サイトに台情報がありません（該当する台情報が見つかりませんでした）。この日は飛ばして、次の機種へ進みます。'});
        },
      }};
    }, {auto,tablesOnly});
    await page.evaluate(overlay);
    await page.waitForFunction(() => document.getElementById('database-auto-toggle'));
  };

  // 自動取り込みの確認：「台情報なし」を返す（表として保存しない）。店舗・日・機種名つき。
  await open(tableUrl('2026-10-10'), true);
  const probe = await page.evaluate(() => window.__databaseAutoProbe());
  assert.equal(probe.kind, 'no_racks');
  assert.deepEqual([probe.store, probe.day, probe.machine], ['nagamachiminami', '2026-10-10', 'SﾊｲﾊﾟｰﾗｯｼｭSLC8']);

  // 手動：「この画面を取り込む」で、送らずに飛ばして機種一覧へ。
  await open(tableUrl('2026-10-10'), false);
  const capture = page.locator('button:has-text("この画面を取り込む")').first();
  await capture.evaluate(button => { button.disabled = false; });
  await Promise.all([page.waitForURL(/rack_info_kt/), capture.click()]);
  assert.match(page.url(), /database_next_machine=1/);

  // 日付の分からないページ（URLに target_date が無い）は飛ばさない（これまでどおり表の読み取りエラー）。
  await open(tableUrl(null), true);
  const unknown = await page.evaluate(() => window.__databaseAutoProbe());
  assert.notEqual(unknown.kind, 'no_racks');
  assert.ok(unknown.error, '表が無いという読み取りエラーのまま');

  // ふつうの表のページは、これまでどおり表として取り込む。
  content = table;
  await open(tableUrl('2026-10-07'), true);
  const normal = await page.evaluate(() => window.__databaseAutoProbe());
  assert.equal(normal.kind, 'table', JSON.stringify(normal));
  // 表があれば、同じ文がページのどこかにあっても台情報ありとして扱う。
  content = table + '<p>該当する台情報がありません</p>';
  await open(tableUrl('2026-10-07'), true);
  assert.equal((await page.evaluate(() => window.__databaseAutoProbe())).kind, 'table');
  // 表だけモードでも機種の表は読み、台のグラフページでは抽出せず一覧へ戻る。
  await open(tableUrl('2026-10-07'), true, true);
  await page.waitForFunction(()=>document.getElementById('database-tables-only').checked);
  assert.equal((await page.evaluate(() => window.__databaseAutoProbe())).kind,'table');
  const graphUrl=HOST+'/nagamachiminami/standgraph/?rack_no=660&target_date=2026-10-07';
  await open(graphUrl,true,true);
  await page.waitForFunction(()=>document.getElementById('database-tables-only').checked);
  assert.equal((await page.evaluate(() => window.__databaseAutoProbe())).kind,'table_only_return');
  await open(graphUrl,false,true);
  await page.waitForFunction(()=>document.getElementById('database-tables-only').checked);
  await capture.evaluate(button=>{button.disabled=false;});
  await Promise.all([page.waitForURL(/rack_info_kt/),capture.click()]);
  assert.deepEqual(errors, []);
  console.log('PASS: Meruhen PC skips a machine whose table says 該当する台情報が見つかりませんでした (auto probe, manual button), keeps normal tables');
} finally {
  await browser.close();
}
