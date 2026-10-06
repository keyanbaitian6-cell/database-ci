// 台別ページの列の日付（2026-10-06 実サイトで確認した形）。7列はURLの#以降の日付に関係なくサイトの
// 「本日」から並び、列 i のグラフ枠 svg{i} は CHART-yyyymmdd の中にある。#以降の日（選んだ日）を1列目と
// みなすと、取り込み日を指定したとき今日の途中の数値をその日として保存し、日付が1日ずつずれていた。
// 実ページの個人データは含めない。
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const script = readFileSync(new URL('../assets/pscube_capture.js', import.meta.url), 'utf8');
const rackUrl = day => `https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/cgi-bin/nc-v06-001.php?cd_dai=1206#${day}`;
const curve = '<svg><path class="amcharts-graph-stroke" d="M0,10 L10,5"/><path class="amcharts-axis-zero-grid" d="M0,10 L10,10"/></svg>';
// 列 i の累計ゲームは 1000+i（どの列を何日として保存したか見分ける）。
const column = i => `<td class="column"><div>${[
  i ? `${i}日前` : '本日', '0', '3', `${50 + i}`, '1/100', `${1000 + i}`, `${2000 + i}`, '0',
].map(v => `<div>${v}</div>`).join('')}</div></td>`;
function html(chartDays) {
  return `<html><head><title>P'sCUBE｜試験機種</title></head><body>
    <h1>SLOT</h1><h2>台番号 1206</h2><a href="nc-v05-011.php?cd_ps=2&bai=20">全台一覧</a>
    <table><tr>${chartDays.map((_, i) => column(i)).join('')}</tr></table>
    ${chartDays.map((day, i) => `<ul id="CHART-${day}"><li><div id="svg${i}">${curve}</div></li></ul>`).join('')}
    </body></html>`;
}
const fromToday = ['20261006', '20261005', '20261004', '20261003', '20261002', '20261001', '20260930'];
const browser = await chromium.launch({headless:true, executablePath:process.env.CHROMIUM_PATH || undefined, args:['--no-sandbox']});
try {
  const page = await browser.newPage();
  let body = '';
  await page.route('**/*', route => route.request().isNavigationRequest()
    ? route.fulfill({status:200, contentType:'text/html; charset=utf-8', body}) : route.abort());
  await page.addInitScript(() => {
    window.api = {apikey:'test', token:{_i:'test', _t:'test'}};
    // 差枚の元データ：サイトは頼んだ日（YMD_biz）までの日を、実際の日付を付けて返す
    // （2026-10-06 実サイトで確認：YMD_biz=20261005 なら 09/29〜10/05）。
    window.jQuery = {ajax:options => {
      const upTo = Number(options.data.YMD_biz);
      const g = [{YMD_biz:20261005, xField:'out-5', yField:'value-5'}];
      if (upTo >= 20261006) g.push({YMD_biz:20261006, xField:'out-6', yField:'value-6'});
      const request = {
        done(callback) {
          queueMicrotask(() => callback({Graph:{src:{datas:{
            g, p:[{'out-6':0, 'value-6':0, 'out-5':0, 'value-5':100}, {'out-6':10, 'value-6':-60, 'out-5':10, 'value-5':400}],
          }}}})); return request;
        }, fail() { return request; },
      }; return request;
    }};
  });
  const capture = async (hashDay, chartDays) => {
    body = html(chartDays);
    await page.goto('about:blank');
    await page.goto(rackUrl(hashDay), {waitUntil:'domcontentloaded'});
    return JSON.parse(await page.evaluate(script));
  };

  // 取り込み日（昨日 10/05）を指定して開いた台別ページ。1列目はサイトの本日 10/06。
  const yesterday = await capture('20261005', fromToday);
  assert.equal(yesterday.error, undefined, yesterday.error);
  assert.equal(yesterday.history_latest_day, '2026-10-06');
  assert.deepEqual(yesterday.records.map(r => r.day),
    ['2026-10-05', '2026-10-04', '2026-10-03', '2026-10-02', '2026-10-01', '2026-09-30'],
    '本日（営業中）の列は保存しない');
  const selected = yesterday.records.find(r => r.day === '2026-10-05');
  assert.equal(selected.games, 1001, '10/05は「1日前」の列の数値（以前は本日の列を10/05として保存していた）');
  assert.equal(selected.at_art, 51);
  assert.equal(selected.detail_url, rackUrl('20261005'));
  assert.equal(selected.net_medals, 300, '差枚もその日のもの');
  assert.equal(yesterday.records.find(r => r.day === '2026-10-04').games, 1002);

  // 日付を指定しない（選んだ日＝サイトの本日）ときは、これまでどおり7列すべて。
  const today = await capture('20261006', fromToday);
  assert.equal(today.error, undefined, today.error);
  assert.equal(today.history_latest_day, '2026-10-06');
  assert.equal(today.records.length, 7);
  assert.equal(today.records[0].day, '2026-10-06');
  assert.equal(today.records[0].games, 1000);
  assert.equal(today.records[0].net_medals, -60);

  // 選んだ日がこの台の7日分に無い・列の日付が連続しない・日付が読めないときは保存しない。
  assert.match((await capture('20260929', fromToday)).error, /7日分にありません/);
  const gap = [...fromToday]; gap[3] = '20261002';
  assert.match((await capture('20261006', gap)).error, /連続していません/);
  body = html(fromToday).replace('id="CHART-20261004"', 'id="chart-x"');
  await page.goto('about:blank');
  await page.goto(rackUrl('20261006'), {waitUntil:'domcontentloaded'});
  assert.match(JSON.parse(await page.evaluate(script)).error, /日付を確認できません/);
  console.log('PASS: rack columns take their dates from the page; a chosen past day saves its own column, never today\'s running numbers');
} finally { await browser.close(); }
