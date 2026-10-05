// 新台の空の過去列と、読み込み途中の欠損を区別する。実ページの個人データは含めない。
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const script = readFileSync(new URL('../assets/pscube_capture.js', import.meta.url), 'utf8');
const url = 'https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/cgi-bin/nc-v06-001.php?cd_dai=1085#20261005';
const values = ['2', '1', '0', '1/61', '183', '192', '2'];
const curve = '<svg><path class="amcharts-graph-stroke" d="M0,10 L10,5"/><path class="amcharts-axis-zero-grid" d="M0,10 L10,10"/></svg>';
function html(rows, graphs = {}) {
  const columns = rows.map((row, i) => `<td class="column"><div>${[
    i ? `${i}日前` : '本日', ...row,
  ].map(v => `<div>${v}</div>`).join('')}</div></td>`).join('');
  return `<html><head><title>P'sCUBE｜新台試験機種</title></head><body>
    <h1>SLOT</h1><h2>台番号 1085</h2><a href="nc-v05-011.php?cd_ps=2&bai=20">全台一覧</a>
    <table><tr>${columns}</tr></table>${rows.map((_, i) => `<div id="svg${i}">${graphs[i] ?? ''}</div>`).join('')}
    </body></html>`;
}
const blank = () => Array(7).fill('');
const fresh = () => [values, ...Array.from({length:6}, blank)];
const browser = await chromium.launch({headless:true, executablePath:process.env.CHROMIUM_PATH || undefined, args:['--no-sandbox']});
try {
  const page = await browser.newPage();
  let body = html(fresh(), {0:curve});
  await page.route('**/*', route => route.request().isNavigationRequest()
    ? route.fulfill({status:200, contentType:'text/html; charset=utf-8', body}) : route.abort());
  await page.addInitScript(() => {
    window.api = {apikey:'test', token:{_i:'test',_t:'test'}};
    window.jQuery = {ajax:() => {
      const request = {
        done(callback) {
          queueMicrotask(() => callback({Graph:{src:{datas:{
            g:[{YMD_biz:20261005,xField:'out-1',yField:'value-1'}],
            p:[{'out-1':0,'value-1':50},{'out-1':10,'value-1':175}],
          }}}})); return request;
        }, fail() { return request; },
      }; return request;
    }};
  });
  const capture = async (rows, graphs = {}) => {
    body = html(rows, graphs);
    await page.goto('about:blank');
    await page.goto(url, {waitUntil:'domcontentloaded'});
    return JSON.parse(await page.evaluate(script));
  };
  const first = await capture(fresh(), {0:curve});
  assert.equal(first.error, undefined, first.error);
  assert.equal(first.records.length, 1);
  assert.deepEqual([first.records[0].bb, first.records[0].rb, first.records[0].games, first.records[0].my], [2,1,183,192]);
  assert.equal(first.records[0].graph.kind, 'daily');
  assert.equal(first.records[0].net_medals, 125);
  assert.deepEqual(first.missing_history_days, ['2026-10-04','2026-10-03','2026-10-02','2026-10-01','2026-09-30','2026-09-29']);
  const second = fresh(); second[1] = values;
  assert.equal((await capture(second)).records.length, 2, '導入2日目もある日だけ保存');
  const zero = fresh(); zero[1] = Array(7).fill('0');
  const withZero = await capture(zero);
  assert.equal(withZero.records.length, 2);
  assert.equal(withZero.records[1].games, 0, '表示された0は有効な記録');
  const all = await capture(Array.from({length:7}, () => values));
  assert.equal(all.records.length, 7);
  assert.equal(all.missing_history_days, undefined, '従来の7日履歴はそのまま');
  const noToday = fresh(); noToday[0] = blank();
  assert.match((await capture(noToday)).error, /数値が未表示/);
  const partial = fresh(); partial[1] = [...values]; partial[1][0] = '';
  assert.match((await capture(partial)).error, /数値が未表示/, '部分的な欠損は省略しない');
  assert.match((await capture(fresh(), {1:curve})).error, /数値が未表示/, 'グラフだけある日も省略しない');
  const malformed = fresh(); malformed[2] = ['?', ...blank().slice(1)];
  assert.match((await capture(malformed)).error, /数値が未表示/);
  console.log('PASS: new installations save existing days and exact net; blank/malformed current or partial histories remain errors');
} finally { await browser.close(); }
