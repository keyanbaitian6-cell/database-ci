// Meruhen: the machine table URL built from a row keeps the site's full-width space
// ("L無職転生　NM"); an ASCII space opened an empty page. Local fixture only; no shop requests.
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const overlay = JSON.parse(execFileSync(process.env.PYTHON || 'python', ['-c',
  'import json,browser_import as b; print(json.dumps(b.OVERLAY_JS))'],
  {cwd: new URL('../../database/', import.meta.url), encoding: 'utf8'}));
const rows = ['L炎炎ノ消防隊jG', 'L無職転生　NM', 'S ガメラ2 XR', 'L転生したら\n    スライムだった件']
  .map(name => `<tr class="teram2-link-block"><td class="wrap-machine-name">${name}</td><td>1台</td></tr>`).join('');
const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || undefined});
try {
  const page = await browser.newPage({viewport: {width: 900, height: 850}});
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.route('**/*', route => route.fulfill({status: 200, contentType: 'text/html; charset=utf-8',
    body: `<html><head><meta charset="utf-8"></head><body><table>${rows}</table></body></html>`}));
  await page.goto('https://meruhenworld.pt.teramoba2.com/nagamachiminami/rack_info_kt/?kind_code=21');
  await page.evaluate(() => {
    window.__asked = null;
    window.pywebview = {api: {
      retry_page: async () => {},
      progress: async () => JSON.stringify({text: ''}),
      machine_status: async () => JSON.stringify({status: []}),
      get_auto_capture: async () => ({enabled: true, seconds: 3.5, revision: 1, message: 'ON', days: [], target_day: null, direction: 'bottom'}),
      save_overlay_layout: async () => true,
      commit_auto_move: async () => { if (window.__databaseFinishMachine) window.__databaseFinishMachine(); return true; },
      next_unimported_machine: async raw => { window.__asked = JSON.parse(raw); return JSON.stringify({url: null, message: 'x'}); },
    }};
  });
  await page.evaluate(overlay);
  await page.evaluate(() => window.__databaseAutoMoveMachine(1));
  await page.waitForFunction(() => window.__asked);
  const machines = await page.evaluate(() => window.__asked.machines);
  const name = url => decodeURIComponent(decodeURIComponent(new URL(url).searchParams.get('machine_name')));
  const byName = Object.fromEntries(machines.map(m => [m.name.replace(/\s+/g, ''), m]));
  assert.equal(name(byName['L無職転生NM'].url), 'L無職転生　NM', '全角スペースを保つ');
  assert.match(byName['L無職転生NM'].url, /%25E3%2580%2580/);
  assert.equal(name(byName['SガメラXR'.replace('X', '2X')].url), 'S ガメラ2 XR');
  assert.equal(name(byName['L転生したらスライムだった件'].url), 'L転生したら スライムだった件', '改行・字下げは半角1つへ');
  assert.equal(machines.length, 4);
  // 手動（自動OFFの「この画面を取り込む」）では、URLの印（いま済ませた機種）を渡す。自動では渡さない。
  assert.equal(await page.evaluate(() => window.__asked.after), '', '自動の移動には印を渡さない');
  await page.goto('https://meruhenworld.pt.teramoba2.com/nagamachiminami/rack_info_kt/?kind_code=21#database_next_machine=1&database_day=2026-10-03&database_after=L%E7%84%A1%E8%81%B7%E8%BB%A2%E7%94%9F%E3%80%80NM');
  await page.evaluate(() => {
    window.__asked = null;
    window.pywebview = {api: {
      retry_page: async () => {}, progress: async () => JSON.stringify({text: ''}),
      machine_status: async () => JSON.stringify({status: []}), save_overlay_layout: async () => true,
      get_auto_capture: async () => ({enabled: false, seconds: 3.5, revision: 1, message: '停止中', days: [], target_day: null, direction: 'top', manual_continuation: false}),
      next_unimported_machine: async raw => { window.__asked = JSON.parse(raw); return JSON.stringify({url: null, message: 'x'}); },
    }};
  });
  await page.evaluate(overlay);
  const capture = page.locator('button:has-text("この画面を取り込む")').first();
  await capture.evaluate(button => { button.disabled = false; });   // 試験ではサイトの読み込み完了通知が無い
  await capture.click();
  await page.waitForFunction(() => window.__asked);
  assert.equal(await page.evaluate(() => window.__asked.after), 'L無職転生　NM', '手動は済ませた機種の次から探す');
  assert.deepEqual(errors, []);
  console.log('meruhen machine url test: ok');
} finally {
  await browser.close();
}
