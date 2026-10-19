// 入れ替えの日に前日を指定すると、新台の全台一覧には当日のタブしか無い（2026-10-19 利用者が実サイトで確認）。
// 読み取りは日付タブの一覧を返し、台別ページへのリンクが無い台を全台一覧の住所で代用しない。
// 実ページの個人データは含めない。
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const script = readFileSync(new URL('../assets/pscube_capture.js', import.meta.url), 'utf8');
const base = 'https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/cgi-bin/';
const url = `${base}nc-v05-011.php?cd_ps=2&bai=20&nmk_kisyu=L%25E6%2596%25B0%25E5%258F%25B0#3;0;20261019;0;cd_dai;1;0;664`;
const rows = Object.entries({'toku1-count': 0, 'toku5-count': 0, 'toku4-count': 0, sum_game: 0, sadama_s: 0})
  .map(([key, value]) => `<tr data-key="${key}"><td>${key}</td><td>${value}</td></tr>`).join('');
const card = (rack, link, day = '20261019') => `<li id="li-${rack}">${link ? `<a href="${base}nc-v06-001.php?cd_dai=${rack}#${day}">${rack}</a>` : rack}<table>${rows}</table></li>`;
// 増台した台：その日の数値もリンクも無い（数値の欄は「-」）。
const blankCard = rack => `<li id="li-${rack}">${rack}<table>${['toku1-count', 'toku5-count', 'toku4-count', 'sum_game', 'sadama_s']
  .map(key => `<tr data-key="${key}"><td>${key}</td><td>-</td></tr>`).join('')}</table></li>`;
const html = (tabs, cards, selected = '20261019') => `<html><head><title>P'sCUBE｜L新台</title></head><body><h1>SLOT</h1>
  <ul>${tabs.map(d => `<li data-ymd="${d}"${d === selected && !seen.has(d) && seen.add(d) ? ' class="selected"' : ''}>${d}</li>`).join('')}</ul>
  <ul>${cards.join('')}</ul></body></html>`;
const seen = new Set();  // 同じ日付のタブが重なっても、選ばれるのは1つだけ
const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
try {
  const page = await browser.newPage();
  let body = '';
  await page.route('**/*', route => route.request().isNavigationRequest()
    ? route.fulfill({status: 200, contentType: 'text/html; charset=utf-8', body}) : route.abort());
  const capture = async (tabs, cards, selected) => {
    seen.clear();
    body = html(tabs, cards, selected);
    await page.goto('about:blank');  // #以降だけ違う同じ住所では読み込み直されない
    await page.goto(url);
    return JSON.parse(await page.evaluate(script));
  };
  // 新台：当日のタブだけ、台別ページへのリンクがまだ無い。理由を出し、タブと住所は返す（保存側が飛ばすか決める）。
  const fresh = await capture(['20261019'], [card(1526, false), card(1527, true)]);
  assert.match(fresh.error, /1526番台の台別ページへのリンクがありません/);
  assert.deepEqual(fresh.available_days, ['2026-10-19']);
  assert.equal(fresh.source_url, url);
  // 普段の機種：7日分のタブ（並びが崩れていても古い順・重複なし）。リンクがそろえば今までどおり読める。
  const tabs = ['20261019', '20261013', '20261014', '20261015', '20261016', '20261017', '20261018', '20261018'];
  const normal = await capture(tabs, [card(1526, true, '20261018')], '20261018');
  assert.equal(normal.error, undefined, normal.error);
  assert.deepEqual(normal.available_days,
    ['2026-10-13', '2026-10-14', '2026-10-15', '2026-10-16', '2026-10-17', '2026-10-18', '2026-10-19']);
  assert.deepEqual(normal.records.map(r => [r.rack, r.day, new URL(r.detail_url).pathname.endsWith('nc-v06-001.php')]),
    [[1526, '2026-10-18', true]]);
  // 増台の翌日に前日：増えた台は数値もリンクも無い。0で埋めず missing_racks として返す（保存してよいかは保存側が決める）。
  const grown = await capture(tabs, [card(1526, true, '20261018'), blankCard(1530), blankCard(1531)], '20261018');
  assert.equal(grown.error, undefined, grown.error);
  assert.deepEqual(grown.records.map(r => r.rack), [1526]);
  assert.deepEqual(grown.missing_racks, [1530, 1531]);
  // 数値があるのにリンクが無い台は、今までどおり理由を出して止める。
  const half = await capture(tabs, [card(1526, false, '20261018')], '20261018');
  assert.match(half.error, /1526番台の台別ページへのリンクがありません/);
  // 数値のある台が1台も無いページは止める（読み込み途中かもしれない）。
  const empty = await capture(tabs, [blankCard(1530)], '20261018');
  assert.match(empty.error, /台の数値がありません/);
  console.log('OK pscube absent day tab capture');
} finally {
  await browser.close();
}
