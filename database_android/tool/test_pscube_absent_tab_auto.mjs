// 取り込み日のタブが無い機種（新台・入れ替え）を自動取り込みで飛ばす（2026-10-22）。生成済みの判定（assets/pscube_auto_probe.js）と
// 読み取り（assets/pscube_capture.js）を模擬ページで動かし、その出力が test/fixtures/pscube_absent_tab_auto.json と同じかを確かめる。
// PC（database/tests/test_pscube_auto_absent_tab.py）とAndroid（test/pscube_auto_absent_tab_test.dart）は、この同じ出力を
// 「判定→自動の決定→読み取り開始→保存（Store）→次のページ」へ流して確かめる。実サイトには接続しない。
// 共通JSを変えて出力が変わったら：UPDATE_FIXTURE=1 node tool/test_pscube_absent_tab_auto.mjs で作り直し、差分を確かめる。
import assert from 'node:assert/strict';
import {readFileSync, writeFileSync} from 'node:fs';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const probe = readFileSync(new URL('../assets/pscube_auto_probe.js', import.meta.url), 'utf8');
const capture = readFileSync(new URL('../assets/pscube_capture.js', import.meta.url), 'utf8');
const fixtureUrl = new URL('../test/fixtures/pscube_absent_tab_auto.json', import.meta.url);

const base = 'https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/cgi-bin/';
const indexUrl = `${base}nc-v03-001.php?cd_ps=2`;
const fresh = `${base}nc-v05-011.php?cd_ps=2&bai=20&nmk_kisyu=NEW`;   // 入れ替えで入った新台（2台）
const older = `${base}nc-v05-011.php?cd_ps=2&bai=20&nmk_kisyu=JUG`;   // 前からある機種（1台）
const indexHtml = `<h1>SLOT</h1><ul id="ulKI">
  <li><a class="btn-ki" href="${fresh}"><span class="nc-label">L新台</span><span class="nc-lower">2台</span></a></li>
  <li><a class="btn-ki" href="${older}"><span class="nc-label">ﾏｲｼﾞｬｸﾞﾗｰV</span><span class="nc-lower">1台</span></a></li></ul>`;
const rows = Object.entries({'toku1-count': 3, 'toku5-count': 2, 'toku4-count': 0, sum_game: 1200, sadama_s: 150})
  .map(([key, value]) => `<tr data-key="${key}"><td>${key}</td><td>${value}</td></tr>`).join('');
const card = (rack, day) => `<li id="li-${rack}"><a href="${base}nc-v06-001.php?cd_dai=${rack}#${day}">${rack}</a><table>${rows}</table></li>`;
const table = (name, tabs, selected, racks, extra = '') => `<title>P'sCUBE｜${name}</title><h1>SLOT</h1>${extra}
  <p>${selected.slice(0, 4)}/${selected.slice(4, 6)}/${selected.slice(6)} 22:00 更新</p>
  <ul>${tabs.map(d => `<li data-ymd="${d}"${d === selected ? ' class="selected"' : ''}>${d}</li>`).join('')}</ul>
  <ul>${racks.map(r => card(r, selected)).join('')}</ul>`;
const rackHtml = `<title>P'sCUBE｜L新台</title><h1>SLOT</h1><h2>台番号 1526</h2><table><tr>${
  Array.from({length: 7}, (_, i) => `<td class="column"><div><div>${i ? `${i}日前` : '本日'}</div></div></td>`).join('')}</tr></table>`;
const week = ['20261012', '20261013', '20261014', '20261015', '20261016', '20261017', '20261018'];

// name：場面、target_day：取り込み日、url：表示中の住所（#以降はサイトが書いたもの）。capture は保存側を確かめるためだけに読む。
const scenes = [
  {name: 'index', target_day: '2026-10-18', url: indexUrl, html: indexHtml, capture: true},
  // 新台：10/19のタブしか無く、10/18を指定して開いてもサイトは10/19を選ぶ → 飛ばす。
  {name: 'only_newer_tab', target_day: '2026-10-18', url: `${fresh}#3;0;20261019;0;cd_dai;1;0;664`,
    html: table('L新台', ['20261019'], '20261019', [1526, 1527]), capture: true},
  // タブの範囲の途中で取り込み日だけが無い → 飛ばす。
  {name: 'gap_in_tabs', target_day: '2026-10-18', url: `${fresh}#3;0;20261019;0;cd_dai;1;0;664`,
    html: table('L新台', ['20261017', '20261019'], '20261019', [1526, 1527]), capture: true},
  // 取り込み日のタブはあるのに別の日が選ばれている → 待つ。
  {name: 'target_tab_not_selected', target_day: '2026-10-18', url: `${fresh}#3;0;20261019;0;cd_dai;1;0;664`,
    html: table('L新台', ['20261018', '20261019'], '20261019', [1526, 1527]), capture: true},
  // 取り込み日がタブより新しい（早朝で今日のタブがまだ出ていない） → 待つ。飛ばさない。
  {name: 'target_newer_than_tabs', target_day: '2026-10-19', url: `${older}#0;0;20261019;0;cd_dai;1;0;0`,
    html: table('ﾏｲｼﾞｬｸﾞﾗｰV', week, '20261018', [2001]), capture: true},
  // 日付タブを読めない（タブが無い）→ 待つ。
  {name: 'no_tabs', target_day: '2026-10-18', url: `${fresh}#3;0;20261019;0;cd_dai;1;0;664`,
    html: table('L新台', [], '20261019', [1526, 1527]), capture: true},
  // 人間確認の窓が出ている → 待つ。
  {name: 'challenge', target_day: '2026-10-18', url: `${fresh}#3;0;20261019;0;cd_dai;1;0;664`,
    html: table('L新台', ['20261019'], '20261019', [1526, 1527], '<iframe src="data:text/html,hcaptcha"></iframe>'), capture: false},
  // 台別ページの日付違い → 今までどおり待つ。
  {name: 'rack_other_day', target_day: '2026-10-18', url: `${base}nc-v06-001.php?cd_dai=1526#20261019`, html: rackHtml, capture: false},
  // 飛ばしたあとに開く次の機種（アプリが日付つきで開く住所そのもの）→ 取り込み日のタブで保存する。
  {name: 'next_machine', target_day: '2026-10-18', url: `${older}#0;0;20261018;0;cd_dai;1;0;0`,
    html: table('ﾏｲｼﾞｬｸﾞﾗｰV', [...week, '20261019'], '20261018', [2001]), capture: true},
];

// 先回りの接続（preconnect）やブラウザ自身の通信も外へ出さない：届かない手元の住所をプロキシに指定する
// （ページの読み込みは下の route が手元の内容で応答する）。
const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || undefined,
  args: ['--no-sandbox', '--proxy-server=http://127.0.0.1:9', '--disable-background-networking']});
const external = [];
const output = {note: '生成元: tool/test_pscube_absent_tab_auto.mjs（UPDATE_FIXTURE=1 で作り直す）。手で直さない。', scenes: []};
try {
  const page = await browser.newPage();
  let body = '';
  await page.route('**/*', route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'https://www.pscube.jp') { external.push(url.href); return route.abort(); }
    return route.request().isNavigationRequest()
      ? route.fulfill({status: 200, contentType: 'text/html; charset=utf-8', body: `<!doctype html><html><head><meta charset="utf-8"></head><body>${body}</body></html>`})
      : route.abort();
  });
  for (const scene of scenes) {
    body = scene.html;
    await page.goto('about:blank');  // #以降だけ違う同じ住所では読み込み直されない
    await page.goto(scene.url);
    const entry = {name: scene.name, target_day: scene.target_day, url: scene.url,
      probe: JSON.parse(await page.evaluate(src => eval(src), probe))};
    if (scene.capture) entry.capture = JSON.parse(await page.evaluate(src => eval(src), capture));
    output.scenes.push(entry);
  }
} finally {
  await browser.close();
}
assert.deepEqual(external, [], '外部への通信はしない');
const by = Object.fromEntries(output.scenes.map(s => [s.name, s]));
// 判定（probe）：全台一覧は並んでいる日付タブを古い順で返す。読めないものは空。
assert.deepEqual(by.only_newer_tab.probe.days, ['2026-10-19']);
assert.equal(by.only_newer_tab.probe.day, '2026-10-19');
assert.deepEqual(by.gap_in_tabs.probe.days, ['2026-10-17', '2026-10-19']);
assert.deepEqual(by.target_tab_not_selected.probe.days, ['2026-10-18', '2026-10-19']);
assert.equal(by.no_tabs.probe.ready, false, 'タブが無い一覧は「表示待ち」');
assert.equal(by.challenge.probe.challenge, true);
assert.equal(by.rack_other_day.probe.kind, '台別7日分');
assert.equal(by.rack_other_day.probe.days, undefined, '台別ページには日付タブを返さない');
assert.equal(by.index.probe.days, undefined);
// 読み取り（capture）：保存側が飛ばすか決める日付タブと住所を返す。
assert.deepEqual(by.only_newer_tab.capture.available_days, ['2026-10-19']);
assert.equal(by.only_newer_tab.capture.source_url, by.only_newer_tab.url);
assert.deepEqual(by.next_machine.capture.records.map(r => [r.rack, r.day]), [[2001, '2026-10-18']]);
assert.deepEqual(by.no_tabs.capture.available_days, []);
const text = JSON.stringify(output, null, 2) + '\n';
if (process.env.UPDATE_FIXTURE) {
  writeFileSync(fixtureUrl, text);
  console.log('updated', fixtureUrl.pathname);
} else {
  assert.deepEqual(JSON.parse(readFileSync(fixtureUrl, 'utf8')), output,
    '共通JSの出力が固定データと違います。UPDATE_FIXTURE=1 で作り直し、差分を確かめてください。');
}
console.log('OK pscube absent tab auto fixture');
