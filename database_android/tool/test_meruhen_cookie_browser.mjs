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
