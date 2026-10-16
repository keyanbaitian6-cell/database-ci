// メルヘンAndroid：台ページの曲線は描けていても、グラフ内の数字（総回転数・BIG・REG・最大持玉）が
// 少し遅れて入ることがある（2026-10-16、PCの幸町で「734番台の数値を確認できません」が多発）。
// 自動取り込みの確認（_autoProbeScript）は数字が空のあいだ待ち、入ったら準備済み、20秒で打ち切り
// （PC版 test_meruhen_graph_numbers_wait.mjs と同じ規則）。グラフの読み取り（_extractGraphScript）は、
// 数字の欄が空でも本文の「最大持玉」の後ろ（7セグ背景の88888888）を拾わない。
// web_import_page.dart に埋め込んだJSそのものを偽のページで動かす。対象サイトへは接続しない。
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const source = readFileSync(new URL('../lib/web_import_page.dart', import.meta.url), 'utf8');
const script = name => source.match(new RegExp(`const ${name} = r'''([\\s\\S]*?)'''`))[1];
const probeScript = script('_autoProbeScript');
const graphScript = script('_extractGraphScript');

const HOST = 'https://meruhenworld.pt.teramoba2.com';
const graphUrl = rack => `${HOST}/saiwaichou/standgraph?dai_hall_id=821&rack_no=${rack}&target_date=2026-10-16`;
const NAMES = ['soukaiten', 'big', 'reg', 'art', 'max_mochidama'];
const svg = numbers => '<svg class="today" viewBox="0 0 300 150" width="300" height="150">' +
  '<g class="path-slump"><path d="M0 75 L30 70 L60 80 L90 65 L120 55 L150 70 L180 60 L210 50 L240 45 L270 40 L300 35"/></g>' +
  '<g class="back-line-middle"><line y1="75"/></g>' +
  NAMES.map((name, i) => `<text class="info_${name}">${numbers ? numbers[i] : ''}</text>`).join('') + '</svg>';
// 実ページの本文のように、数字の欄の外に7セグ表示の背景の8が並ぶ。
const sevenSegment = '<div>BB 888 5</div><div>総回転数 88888888 1414</div><div>最大持玉 88888888 688</div>';

const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || undefined});
try {
  const page = await browser.newPage({viewport: {width: 393, height: 852}});
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  let content = svg(null);
  await page.route('**/*', route => route.fulfill({status: 200, contentType: 'text/html; charset=utf-8',
    body: `<html><head><meta charset="utf-8"></head><body><h3>734番台</h3>${content}</body></html>`}));
  const run = async code => JSON.parse(await page.evaluate(code => (0, eval)(code), code));

  // 数字が4つとも空：待つ。読み直しても空なら待ち続ける。
  await page.goto(graphUrl(734));
  const waiting = await run(probeScript);
  assert.equal(waiting.ready, false, JSON.stringify(waiting));
  assert.match(waiting.reason, /台の数値.*表示待ち/);
  assert.equal((await run(probeScript)).ready, false);

  // 同じページで数字が入ったら準備済み。読み取りはその数字。
  await page.evaluate(() => {
    const values = ['1348', '12', '6', '', '859'];
    ['soukaiten', 'big', 'reg', 'art', 'max_mochidama'].forEach((name, i) => {
      document.querySelector('.info_' + name).textContent = values[i];
    });
  });
  assert.equal((await run(probeScript)).ready, true);
  const read = await run(graphScript);
  assert.deepEqual([read.rack, read.games, read.bb, read.rb, read.max_hold], [734, 1348, 12, 6, 859]);

  // 入らないままなら、同じページで20秒たって準備済み（そのあと保存側が判断する）。
  content = svg(null) + sevenSegment;
  await page.goto(graphUrl(735));
  assert.equal((await run(probeScript)).ready, false);
  await page.evaluate(() => { const now = Date.now; Date.now = () => now() + 20001; });
  assert.equal((await run(probeScript)).ready, true);
  // 数字の欄が空のままなら、本文の88888888などを拾わず「不明」のまま。
  const empty = await run(graphScript);
  assert.deepEqual([empty.games, empty.bb, empty.rb, empty.max_hold], [null, null, null, null]);

  // 最初から数字の入っているページは待たない（これまでどおり）。
  content = svg(['3496', '21', '20', '', '833']) + sevenSegment;
  await page.goto(graphUrl(736));
  assert.equal((await run(probeScript)).ready, true);
  assert.equal((await run(graphScript)).max_hold, 833);
  assert.deepEqual(errors, []);
  console.log('PASS: Meruhen Android probe waits while rack graph numbers are empty (20s cap); graph read ignores 7-segment 8s in the body');
} finally {
  await browser.close();
}
