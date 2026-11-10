// 初回通信を待つ間も本文の開始位置とフッターが跳ねないことを確認する。
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(process.env.SHARE_WEB_ROOT || fileURLToPath(new URL('../../share_viewer', import.meta.url)));
const server = http.createServer(async (req,res) => {
  try {
    const name = new URL(req.url, 'http://x').pathname;
    const local = path.resolve(root, '.' + (name === '/' ? '/index.html' : name));
    if (!local.startsWith(root + path.sep)) { res.writeHead(403).end(); return; }
    res.setHeader('content-type', local.endsWith('.mjs') ? 'text/javascript' : 'text/html;charset=utf-8');
    res.end(await fs.readFile(local));
  } catch { res.writeHead(404).end(); }
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const browser = await chromium.launch({headless:true, executablePath:process.env.CHROMIUM_PATH || undefined, args:['--no-sandbox']});
try {
  for (const width of [320,393,1280]) {
    const context = await browser.newContext({viewport:{width,height:852},serviceWorkers:'block'});
    let release;
    const pending = new Promise(r => { release = r; });
    await context.route('https://script.google.com/**', async route => {
      await pending;
      const file = new URL(route.request().url()).searchParams.get('file');
      const body = !file ? {format:'database-backup',version:1,records:[{store:'saiwaichou',day:'2026-11-10',machine:'試験',rack:1,games:3000,bb:20,rb:10,jo_net:100}]} : file === 'pscube' ? {format:'pscube-viewer',version:1,machines:[],records:[]} : {events:[],marks:[]};
      await route.fulfill({json:body});
    });
    await context.route('**/character_birthdays.json*', r => r.fulfill({json:{entries:[]}}));
    const page = await context.newPage();
    await page.goto(`http://127.0.0.1:${server.address().port}/#s=AKfycbTEST${'x'.repeat(40)}`);
    await page.waitForFunction(() => document.querySelector('#app')?.textContent.includes('Googleドライブから'));
    const before = await page.evaluate(() => ({top:document.querySelector('#app').getBoundingClientRect().top,footer:document.querySelector('footer').getBoundingClientRect().top,height:innerHeight}));
    assert.ok(before.footer >= before.height - 1, `${width}px：通信待ちのフッターを画面下へ確保`);
    release();
    await page.waitForSelector('.grid');
    const after = await page.locator('#app').boundingBox();
    assert.ok(Math.abs(after.y - before.top) < 1, `${width}px：本文の開始位置を維持`);
    assert.ok(await page.locator('footer').isVisible(), '説明文は保持する');
    await context.close();
  }
  console.log('成功：初回通信待ちの表示位置（320・393・1280px）');
} finally { await browser.close(); await new Promise(r => server.close(r)); }
