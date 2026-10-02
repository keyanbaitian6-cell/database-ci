// P’s CUBEの自動取り込み：ページ判定（assets/pscube_auto_probe.js）とPC版の取り込みカード
// （database/pscube_import.py の overlay_script）を、ダミーページで確かめる。実サイトには接続しない
// （https://www.pscube.jp/ へのリクエストはすべて手元の内容で応答する）。
// 実行：PLAYWRIGHT_MODULE=… CHROMIUM_PATH=… PYTHON=…(省略時 python) node tool/test_pscube_auto_browser.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const probe = readFileSync(new URL('../assets/pscube_auto_probe.js', import.meta.url), 'utf8');
const database = fileURLToPath(new URL('../../database/', import.meta.url));
const overlay = execFileSync(process.env.PYTHON || 'python', ['-c',
  'import sys, pscube_import as m; sys.stdout.buffer.write(m.overlay_script(m.CAPTURE.read_text(encoding="utf-8"), m.ROOT_URL + "cgi-bin/nc-v03-001.php?cd_ps=2").encode("utf-8"))'],
  { cwd: database, env: { ...process.env, PYTHONUTF8: '1' } }).toString('utf8');

const root = 'https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/';
const base = `${root}cgi-bin/`;
const mUrl = `${base}nc-v05-011.php?cd_ps=2&bai=20`;
const indexHtml = `<ul id="ulKI"><li><a class="btn-ki" href="${mUrl}"><span class="nc-label">試験機種</span><span class="nc-lower">2台</span></a></li></ul>`;
const card = rack => `<li id="li-${rack}"><a href="${base}nc-v06-001.php?cd_dai=${rack}#20261001">${rack}</a><table>${Object.entries({ 'toku1-count': 3, 'toku5-count': 1, 'toku4-count': 0, sum_game: 600, sadama_s: 120 }).map(([key, value]) => `<tr data-key="${key}"><td>${key}</td><td>${value}</td></tr>`).join('')}</table><div id="ca-${rack}"><svg><path stroke="#f0e448" stroke-width="2" d="M0,10 L10,2 M0,0 L0,0"/><path stroke="#ffffff" stroke-width="0" d="M0,10 L10,10"/></svg></div></li>`;
const tableHtml = (selected = true) => `<title>P'sCUBE｜試験機種</title><h1>SLOT</h1><li data-ymd="20261001"${selected ? ' class="selected"' : ''}>本日</li><ul>${[1, 3].map(card).join('')}</ul>`;
const rackHtml = `<title>P'sCUBE｜試験機種</title><h1>SLOT</h1><h2>台番号 1</h2><a href="${mUrl}">機種データ</a><table><tr>${Array.from({ length: 7 }, (_, i) => `<td class="column"><div>${[i ? `${i}日前` : '本日', 3, 1, 0, '1/150', 600, 120, 20].map(v => `<div>${v}</div>`).join('')}</div></td>`).join('')}</tr></table>${Array.from({ length: 7 }, (_, i) => `<div id="svg${i}"><svg><path class="amcharts-graph-stroke" d="M0,10 L10,1 M0,0 L0,0"/><path class="amcharts-axis-zero-grid" d="M0,10 L10,10"/></svg></div>`).join('')}`;
let pages = {};
const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
const context = await browser.newContext({ viewport: { width: 1050, height: 780 } });
const external = [];
await context.route('**/*', route => {
  const url = new URL(route.request().url());
  if (url.origin !== 'https://www.pscube.jp') { external.push(url.href); return route.abort(); }
  const key = url.pathname + url.search;
  return route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: `<!doctype html><html><head><meta charset="utf-8"></head><body>${pages[key] ?? '<p>申し訳ありませんが、お客様がロボットでないことを確認させていただく必要があります。</p>'}</body></html>` });
});
const page = await context.newPage();
const errors = [];
page.on('pageerror', e => errors.push(e.message));
const state = () => page.evaluate(src => JSON.parse(eval(src)), probe);
const path = u => new URL(u).pathname + new URL(u).search;

// ---- ページ判定 ----
pages = { [path(`${base}nc-v03-001.php?cd_ps=2`)]: indexHtml, [path(mUrl)]: tableHtml(), [path(`${base}nc-v06-001.php?cd_dai=1`)]: rackHtml,
  [path(`${base}nc-v05-011.php?cd_ps=2&bai=5`)]: tableHtml(false), [path(`${base}nc-v03-001.php?cd_ps=1`)]: indexHtml };
await page.goto(`${base}nc-v03-001.php?cd_ps=2#scroll=3`);
assert.deepEqual(await state(), { ready: true, kind: '機種一覧', signature: `${base}nc-v03-001.php?cd_ps=2`, busy: false, url: `${base}nc-v03-001.php?cd_ps=2#scroll=3` });
await page.goto(`${mUrl}#x`);
let s = await state();
assert.equal(s.ready, true); assert.equal(s.kind, '全台一覧'); assert.equal(s.signature, mUrl, '一覧はスクロールのhashを無視');
await page.goto(`${base}nc-v06-001.php?cd_dai=1#20261001`);
s = await state();
assert.equal(s.kind, '台別7日分'); assert.equal(s.signature, `${base}nc-v06-001.php?cd_dai=1#20261001`, '台別は日付hashを含む');
await page.goto(`${base}nc-v06-001.php?cd_dai=1`);
assert.match((await state()).reason, /日付がまだ決まっていません/);
await page.goto(`${base}nc-v05-011.php?cd_ps=2&bai=5`);
assert.match((await state()).reason, /全台一覧の表示待ち/, '日付が選ばれていない一覧は待つ');
await page.goto(`${base}nc-v03-001.php?cd_ps=1`);
assert.match((await state()).reason, /スロットの機種一覧ではありません/);
await page.goto(`${base}nc-v06-001.php?cd_dai=9#20261001`);
s = await state();
assert.equal(s.challenge, true, '確認画面（注意書き）を見分ける'); assert.match(s.reason, /人間確認・同意の画面/);
pages[path(`${base}nc-v06-001.php?cd_dai=8`)] = '<p>メンテナンス中</p>';
await page.goto(`${base}nc-v06-001.php?cd_dai=8#20261001`);
s = await state();
assert.equal(s.challenge, undefined); assert.equal(s.missing, true, '確認画面でもないのに表が無い＝止められた可能性');
await page.goto(root);
assert.equal((await state()).ready, false, '最初のページでは取り込まない');
await page.goto(`${base}nc-v05-011.php?cd_ps=2&bai=20`);
assert.equal((await page.evaluate(src => JSON.parse(eval(src)), probe)).ready, true);

// ---- PC版の取り込みカード ----
async function install(url, api) {
  await page.goto(url);
  await page.evaluate(stub => {
    window.__calls = [];
    window.pywebview = { api: {
      submit_page: async payload => { window.__calls.push(['submit', JSON.parse(payload)]); sessionStorage.setItem('submitted', payload); if (stub.fail) throw new Error(stub.fail); return stub.result; },
      capture_failed: async message => { window.__calls.push(['failed', message]); return true; },
      retry_page: async () => { window.__calls.push(['retry']); return true; },
      reset_site: async () => { window.__calls.push(['reset']); return 'サイトのCookie・保存データを消しました（取り込んだ記録はそのまま）。'; },
      set_auto_capture: async (enabled, seconds) => { window.__calls.push(['auto', enabled, seconds]); return { enabled, seconds, message: enabled ? 'ON・次の取り込みを待っています' : '停止中', revision: 9 }; },
    } };
  }, api);
  await page.evaluate(overlay);
}
await install(mUrl, { result: { kind: '全台一覧', remaining: 2, next_url: `${base}nc-v06-001.php?cd_dai=1#20261001`, backup: 'バックアップ済み' } });
assert.equal(await page.locator('#database-pscube-auto').innerText(), '自動取り込み：OFF（押すと開始）', '起動時はOFF');
assert.equal(await page.locator('#database-pscube-interval').inputValue(), '7.1', 'PCのP’s CUBEは初期7.1秒');
assert.equal(await page.locator('#database-pscube-interval').getAttribute('step'), '0.1');
assert.match(await page.locator('#database-pscube-card label').innerText(), /7\.1秒/);
await page.locator('#database-pscube-interval').evaluate(e => { e.value = '7.2'; e.dispatchEvent(new Event('input')); });
assert.match(await page.locator('#database-pscube-card label').innerText(), /7\.2秒/);
await page.locator('#database-pscube-interval').evaluate(e => { e.value = '7.1'; e.dispatchEvent(new Event('input')); });
// ON/OFFの切り替えはPython側へ頼み、返ってきた状態を表示する。
await page.locator('#database-pscube-auto').click();
await page.waitForFunction(() => document.getElementById('database-pscube-auto').textContent.includes('ON'));
assert.deepEqual(await page.evaluate(() => window.__calls[0]), ['auto', true, 7.1]);
assert.equal(await page.locator('#database-pscube-capture').isDisabled(), true, 'ONの間は手動の取り込みを押せない');
assert.equal(await page.locator('#database-pscube-interval').isDisabled(), true, 'ONの間は間隔を変えられない');
assert.equal(await page.evaluate(() => getComputedStyle(document.getElementById('database-pscube-auto')).backgroundColor), 'rgb(8, 125, 89)');
// Python側のタイマーが開始を頼む → 手動と同じ取り込み → 保存 → 次のページへ移動。
assert.equal(await page.evaluate(() => window.__pscubeStartCapture()), true);
assert.equal(await page.evaluate(() => window.__pscubeStartCapture()), false, '取り込み中は2つ目を始めない');
await page.waitForURL(`${base}nc-v06-001.php?cd_dai=1#20261001`);
const submitted = JSON.parse(await page.evaluate(() => sessionStorage.getItem('submitted')));
assert.equal(submitted.source_url, mUrl, '保存したのは移動前の全台一覧');
assert.equal(submitted.records.length, 2);
// 失敗：保存の前に失敗したらPythonへ知らせ、取り込み中の印を外す。
await install(mUrl, { fail: '表示は1台、設置台数は2台です。' });
await page.evaluate(() => window.__pscubeStartCapture());
await page.waitForFunction(() => window.__calls.some(c => c[0] === 'failed'));
assert.deepEqual((await page.evaluate(() => window.__calls.map(c => c[0]))), ['submit', 'failed']);
assert.equal((await page.evaluate(() => window.__calls[0][1])).records.length, 2, '取り込んだのは表示中の全台');
assert.equal(await page.evaluate(() => window.__pscubeBusy), false);
assert.match(await page.locator('#database-pscube-capture').innerText(), /設置台数は2台/);
// 最初のページでは自動で始めない（「スロット機種一覧へ」は手動）。
await install(root, {});
assert.equal(await page.evaluate(() => window.__pscubeStartCapture()), false);
assert.equal(await page.locator('#database-pscube-capture').innerText(), 'スロット機種一覧へ');
// 状態の表示（古い番号の状態は無視）。
await page.evaluate(() => window.__pscubeRenderAuto({ enabled: true, seconds: 25, message: 'ON・待機：人間確認', revision: 5 }));
await page.evaluate(() => window.__pscubeRenderAuto({ enabled: false, seconds: 10, message: '古い', revision: 4 }));
assert.equal(await page.locator('#database-pscube-auto-status').innerText(), 'ON・待機：人間確認');
assert.equal(await page.locator('#database-pscube-interval').inputValue(), '25');
// Cookie・保存値を保持する再試行は、消去APIや確認画面を使わない。
await install(mUrl, {});
await page.evaluate(() => { document.cookie='retained=keep; path=/'; localStorage.setItem('retained','keep'); });
await page.locator('#database-pscube-retry').click();
await page.waitForFunction(() => window.__calls.length === 1);
assert.deepEqual(await page.evaluate(() => window.__calls), [['retry']]);
assert.match(await page.evaluate(() => document.cookie), /retained=keep/);
assert.equal(await page.evaluate(() => localStorage.getItem('retained')), 'keep');
await install(mUrl, {});
await page.evaluate(() => { window.__pscubeBusy = true; });
await page.locator('#database-pscube-retry').click();
assert.deepEqual(await page.evaluate(() => window.__calls), [], '保存中は再試行しない');
// 「サイトの記録を消してやり直す」：確認でやめたら何もしない。OKならPython側へ頼み、結果を表示する。
await install(mUrl, {});
let dialogs = [];
const dismiss = d => { dialogs.push(d.message()); d.dismiss(); };
page.once('dialog', dismiss);
await page.locator('#database-pscube-reset').click();
await page.waitForFunction(() => true);
assert.equal(dialogs.length, 1);
assert.match(dialogs[0], /取り込んだ記録は消えません/);
assert.deepEqual(await page.evaluate(() => window.__calls), [], 'やめたら消さない');
page.once('dialog', d => { dialogs.push(d.message()); d.accept(); });
await page.locator('#database-pscube-reset').click();
await page.waitForFunction(() => window.__calls.some(c => c[0] === 'reset'));
await page.waitForFunction(() => document.getElementById('database-pscube-auto-status').textContent.includes('消しました'));
assert.equal(await page.locator('#database-pscube-reset').isDisabled(), true, '二度押ししない');
// 保存中は確認も出さずに断る。
await install(mUrl, {});
await page.evaluate(() => { window.__pscubeBusy = true; });
dialogs = [];
page.once('dialog', dismiss);
await page.locator('#database-pscube-reset').click();
assert.match(await page.locator('#database-pscube-auto-status').innerText(), /保存中です/);
page.removeAllListeners('dialog');
assert.deepEqual(dialogs, []);
assert.deepEqual(await page.evaluate(() => window.__calls), []);
await page.evaluate(() => { window.__pscubeBusy = false; });
// 小さい窓でもカードが画面に収まる。
await page.setViewportSize({ width: 360, height: 300 });
const box = await page.locator('#database-pscube-card').boundingBox();
assert.ok(box.x >= 0 && box.y >= 0 && box.x + box.width <= 360 && box.y + box.height <= 300, JSON.stringify(box));

// DNSエラー画面は準備完了後だけ再試行する。
const errorHtml = execFileSync(process.env.PYTHON || 'python', ['-c',
  'import sys; from pscube_connection import BrowserConnection,error_page; c=BrowserConnection("https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/"); c.start(c.url,1); c.navigation_completed(1,False,"HostNameNotResolved"); sys.stdout.buffer.write(error_page(c).encode("utf-8"))'],
  { cwd: database, env: { ...process.env, PYTHONUTF8: '1' } }).toString('utf8');
await page.goto('about:blank');
await page.setContent(errorHtml);
assert.equal(await page.locator('#retry').isDisabled(), true);
await page.evaluate(() => {
  window.__retryCalls=0;
  window.pywebview={api:{retry_page:async()=>{window.__retryCalls++}}};
  window.dispatchEvent(new Event('pywebviewready'));
});
assert.match(await page.locator('body').innerText(), /DNSエラー/);
await page.locator('#retry').click();
assert.equal(await page.evaluate(() => window.__retryCalls), 1);
assert.equal(await page.locator('#retry').isDisabled(), true);

assert.deepEqual(errors, []);
assert.deepEqual(external, []);
await browser.close();
console.log('PASS: ページ判定（3種類・確認画面・日付なし・対象外）、カードのON/OFF表示、自動開始→保存→次ページ、二重開始なし、失敗の報告、最初のページ、古い状態の無視、Cookie保持の再試行・DNSエラー画面、サイトの記録を消す（確認・保存中は断る）、360×300に収まる');
