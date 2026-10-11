// メルヘンAndroid：機種の表の代わりにサイトが「該当する台情報が見つかりませんでした」を出すページ
// （2026-10-11）。Android版の自動取り込みの確認（_autoProbeScript）は「準備済み」とし、表の読み取り
// （_extractTableScript）は no_racks を返す（画面がそれを見て、その日はこの機種を飛ばす）。
// ふつうの表は今までどおり。web_import_page.dart に埋め込んだJSそのものを偽のページで動かす。
// 対象サイトへは接続しない（すべて page.route で返す）。
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const source = readFileSync(new URL('../lib/web_import_page.dart', import.meta.url), 'utf8');
const script = name => source.match(new RegExp(`const ${name} = r'''([\\s\\S]*?)'''`))[1];
const probeScript = script('_autoProbeScript');
const tableScript = script('_extractTableScript');

const HOST = 'https://meruhenworld.pt.teramoba2.com';
const name = encodeURIComponent(encodeURIComponent('SﾊｲﾊﾟｰﾗｯｼｭSLC8'));
const url = day => `${HOST}/nagamachiminami/standlist_slot/?kind_code=21&machine_name=${name}&target_date=${day}`;
const empty = '<div class="title">個別台情報一覧</div><p>該当する台情報が見つかりませんでした。</p>';
const table = '<table><tr>' + ['台番号', 'BB', 'RB', '総回転数', '合成確率', '前日最終スタート', '最大持玉']
  .map(h => `<th>${h}</th>`).join('') + '</tr><tr><td><a href="/nagamachiminami/standgraph/?rack_no=660&target_date=2026-10-07">660</a></td>' +
  '<td>3</td><td>2</td><td>1500</td><td>1/300</td><td>0</td><td>400</td></tr></table>';

const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || undefined});
try {
  const page = await browser.newPage({viewport: {width: 393, height: 852}});
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  let content = empty;
  await page.route('**/*', route => route.fulfill({status: 200, contentType: 'text/html; charset=utf-8',
    body: `<html><head><meta charset="utf-8"></head><body>${content}</body></html>`}));
  const run = async code => JSON.parse(await page.evaluate(code => (0, eval)(code), code));

  await page.goto(url('2026-10-10'));
  const probe = await run(probeScript);
  assert.equal(probe.ready, true, `表が無くても準備済み：${JSON.stringify(probe)}`);
  const read = await run(tableScript);
  assert.deepEqual([read.no_racks, read.rows.length, read.store, read.day, read.machine],
    [true, 0, 'nagamachiminami', '2026-10-10', 'SﾊｲﾊﾟｰﾗｯｼｭSLC8']);

  // まだ何も表示されていないページは、これまでどおり表の表示を待つ。
  content = '<p>読み込み中</p>';
  await page.goto(url('2026-10-10'));
  assert.equal((await run(probeScript)).reason, '表の表示待ち');

  // ふつうの表は今までどおり。
  content = table;
  await page.goto(url('2026-10-07'));
  assert.equal((await run(probeScript)).ready, true);
  const normal = await run(tableScript);
  assert.equal(normal.no_racks, false);
  assert.equal(normal.rows.length, 1);
  assert.deepEqual(errors, []);
  console.log('PASS: Meruhen Android probe/table scripts mark 該当する台情報が見つかりませんでした as no_racks; normal tables unchanged');
} finally {
  await browser.close();
}
