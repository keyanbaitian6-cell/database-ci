// Meruhen browser controls on local fixtures; no shop requests or user data.
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const scripts = JSON.parse(execFileSync(process.env.PYTHON || 'python', ['-c',
  'import json,browser_import as b; from pscube_connection import error_page; c=b._Bridge("unused.db","unused","unused")._connection; c.start(c.url,1); c.navigation_completed(1,False,"HostNameNotResolved"); print(json.dumps([b.OVERLAY_JS,error_page(c,title="メルヘン")]))'],
  {cwd: new URL('../../database/', import.meta.url), encoding: 'utf8'}));
const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || undefined});
try {
  const page = await browser.newPage({viewport:{width:390,height:850}});
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.route('**/*', route => route.fulfill({status:200,contentType:'text/html',body:'<html><body>Local fixture</body></html>'}));
  await page.goto('https://meruhenworld.pt.teramoba2.com/saiwaichou/rack_info');
  await page.evaluate(() => {
    document.cookie='retained=keep;path=/';
    localStorage.setItem('retained','keep');
    window.__calls=[];
    window.pywebview={api:{
      retry_page:async()=>{window.__calls.push('retry');if(window.__rejectRetry) throw Error('saving');},
      progress:async()=>JSON.stringify({text:'Local fixture'}),
      machine_status:async()=>JSON.stringify({status:[]}),
      get_auto_capture:async()=>({enabled:false,seconds:3.5,revision:1,message:'停止中'}),
      save_overlay_layout:async()=>true,
    }};
  });
  await page.evaluate(scripts[0]);
  await page.locator('#database-browser-retry').click();
  assert.deepEqual(await page.evaluate(() => window.__calls), ['retry']);
  assert.match(await page.evaluate(() => document.cookie), /retained=keep/);
  assert.equal(await page.evaluate(() => localStorage.getItem('retained')), 'keep');
  assert.equal(await page.locator('#database-browser-retry').isDisabled(), true);
  await page.evaluate(() => {document.getElementById('database-browser-retry').disabled=false;window.__rejectRetry=true;});
  await page.locator('#database-browser-retry').click();
  await page.waitForFunction(() => !document.getElementById('database-browser-retry').disabled);
  assert.match(await page.locator('#database-capture-status').innerText(), /確認・保存中/);
  const box = await page.locator('#database-overlay').boundingBox();
  assert.ok(box.x >= 0 && box.y >= 0 && box.x+box.width <= 390 && box.y+box.height <= 850);
  // 日付指定取り込み・上から／下から：日付を選ぶとPython側へ伝え、押すと選んだ日と向きで自動取り込みを始める。
  await page.evaluate(() => {
    window.__calls = [];
    const days = ['2026-10-01', '2026-09-30', '2026-09-29'];
    const state = (enabled, day, direction) => ({enabled, seconds: 3.5, revision: 5 + window.__calls.length, message: enabled ? 'ON' : '停止中', target_day: day || null, direction: direction || 'top', days});
    window.__target = {day: '', direction: 'top'};
    window.pywebview.api.set_target_day = async (day, direction) => {
      window.__calls.push(['target', day, direction]);
      window.__target = {day, direction: direction || window.__target.direction};
      return state(false, day, window.__target.direction);
    };
    window.pywebview.api.set_auto_capture = async (enabled, seconds, day, direction) => {
      window.__calls.push(['auto', enabled, seconds, day, direction]);
      window.__target = {day, direction: direction || window.__target.direction};
      return state(enabled, day, window.__target.direction);
    };
    window.__databaseRenderAuto(state(false, '', 'top'));
  });
  assert.deepEqual(await page.locator('#database-auto-day option').allInnerTexts(),
    ['指定なし（サイトの表示どおり）', '10/1（木）　今の営業日', '9/30（水）', '9/29（火）']);
  assert.equal(await page.locator('#database-auto-top').innerText(), '上から取り込む');
  assert.equal(await page.locator('#database-auto-bottom').innerText(), '下から取り込む');
  await page.locator('#database-auto-day').selectOption('2026-09-30');
  await page.waitForFunction(() => window.__calls.some(c => c[0] === 'target'));
  assert.deepEqual(await page.evaluate(() => window.__calls.at(-1)), ['target', '2026-09-30', null]);
  await page.locator('#database-auto-bottom').click();
  await page.waitForFunction(() => document.getElementById('database-auto-toggle').textContent.includes('ON'));
  assert.deepEqual(await page.evaluate(() => window.__calls.at(-1)), ['auto', true, 3.5, '2026-09-30', 'bottom']);
  assert.equal(await page.locator('#database-auto-top').isDisabled(), true, 'ONの間は押せない');
  assert.equal(await page.locator('#database-auto-day').isDisabled(), true, 'ONの間は日付を変えられない');
  // 営業日が変わったら（午前2時）、選択肢を作り直す。選んだ日は残る。
  await page.evaluate(() => window.__databaseRenderAuto({enabled: false, seconds: 3.5, revision: 99, message: '停止中', target_day: '2026-09-30', direction: 'bottom', days: ['2026-10-02', '2026-10-01', '2026-09-30']}));
  assert.deepEqual(await page.locator('#database-auto-day option').allInnerTexts(),
    ['指定なし（サイトの表示どおり）', '10/2（金）　今の営業日', '10/1（木）', '9/30（水）']);
  assert.equal(await page.locator('#database-auto-day').inputValue(), '2026-09-30');
  const box2 = await page.locator('#database-overlay').boundingBox();
  assert.ok(box2.x >= 0 && box2.y >= 0 && box2.x+box2.width <= 390 && box2.y+box2.height <= 850, 'カードは窓に収まる');
  await page.goto('about:blank');
  await page.setContent(scripts[1]);
  assert.equal(await page.locator('#retry').isDisabled(), true);
  await page.evaluate(() => {
    window.__calls=[];
    window.pywebview={api:{retry_page:async()=>window.__calls.push('retry')}};
    window.dispatchEvent(new Event('pywebviewready'));
  });
  assert.match(await page.locator('h2').innerText(), /メルヘン/);
  assert.match(await page.locator('body').innerText(), /DNSエラー/);
  await page.locator('#retry').click();
  assert.deepEqual(await page.evaluate(() => window.__calls), ['retry']);
  assert.deepEqual(errors, []);
  console.log('PASS: Meruhen retry keeps Cookies/storage, handles saving rejection, fits mobile width, and works on DNS error page');
} finally {await browser.close();}
