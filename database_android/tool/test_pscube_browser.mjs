// Run with Playwright installed: node tool/test_pscube_browser.mjs
// Optional: PLAYWRIGHT_MODULE=/absolute/path/to/playwright-core/index.mjs
//           CHROMIUM_PATH=/usr/bin/chromium
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const web = fileURLToPath(new URL('../web/', import.meta.url));
const server = http.createServer(async (req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname;
  const local = path.resolve(web, '.' + (pathname.endsWith('/') ? pathname + 'index.html' : pathname));
  if (!local.startsWith(web)) { res.writeHead(403).end(); return; }
  try {
    const body = await fs.readFile(local);
    res.setHeader('content-type', local.endsWith('.mjs') ? 'text/javascript' : local.endsWith('.css') ? 'text/css' : 'text/html');
    res.end(body);
  } catch { res.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined, args: ['--no-sandbox'] });
const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
const errors = [], external = [];
page.on('pageerror', e => errors.push(e.message));
page.on('request', request => { if (!request.url().startsWith(origin)) external.push(request.url()); });
const base = 'https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c1/cgi-bin/';
const mUrl = `${base}nc-v05-011.php?cd_ps=2&bai=20`;
function archive(url, html) {
  const escape = s => s.replaceAll('&', '&amp;').replaceAll('<', '&lt;');
  return { name: 'synthetic.webarchive', mimeType: 'application/x-webarchive', buffer: Buffer.from(`<?xml version="1.0"?><plist version="1.0"><dict><key>WebMainResource</key><dict><key>WebResourceURL</key><string>${escape(url)}</string><key>WebResourceMIMEType</key><string>text/html</string><key>WebResourceData</key><data>${Buffer.from(html).toString('base64')}</data></dict></dict></plist>`) };
}
const index = archive(`${base}nc-v03-001.php?cd_ps=2`, `<ul id="ulKI"><li><a class="btn-ki" href="${mUrl}"><span class="nc-label">試験機種</span><span class="nc-lower">2台</span></a></li></ul><script>window.injected=true</script><img src="https://invalid.example/tracker"><iframe src="https://invalid.example/"></iframe>`);
function card(rack) {
  return `<li id="li-${rack}"><a href="${base}nc-v06-001.php?cd_dai=${rack}#20261001">${rack}</a><table>${Object.entries({ 'toku1-count': 3, 'toku5-count': 1, 'toku4-count': 0, sum_game: 600, sadama_s: 120 }).map(([key, value]) => `<tr data-key="${key}"><td>${key}</td><td>${value}</td></tr>`).join('')}</table><div id="ca-${rack}"><svg><path stroke="#f0e448" stroke-width="2" d="M0,10 L10,2 M0,0 L0,0"/><path stroke="#ffffff" stroke-width="0" d="M0,10 L10,10"/></svg></div></li>`;
}
const machine = (racks = [1, 3]) => archive(mUrl, `<title>P'sCUBE｜試験機種</title><h1>SLOT</h1><li data-ymd="20261001" class="selected">本日</li><ul>${racks.map(card).join('')}</ul>`);
const rack = archive(`${base}nc-v06-001.php?cd_dai=1#20261001`, `<title>P'sCUBE｜試験機種</title><h1>SLOT</h1><h2>台番号 1</h2><a href="${mUrl}">機種データ</a><table><tr>${Array.from({ length: 7 }, (_, i) => `<td class="column"><div>${[i ? `${i}日前` : '本日', 3, 1, 0, '1/150', 600, 120, 20].map(v => `<div>${v}</div>`).join('')}</div></td>`).join('')}</tr></table>${Array.from({ length: 7 }, (_, i) => `<div id="svg${i}"><svg><path class="amcharts-graph-stroke" d="M0,10 L10,1 M0,0 L0,0"/><path class="amcharts-axis-zero-grid" d="M0,10 L10,10"/></svg></div>`).join('')}`);
async function upload(file) {
  await page.locator('#files').setInputFiles(file);
  await page.waitForFunction(() => !document.getElementById('files').disabled);
}
try {
  await page.goto(`${origin}/pscube/`);
  await upload(index); assert.equal(await page.locator('.machine').count(), 1);
  assert.equal(await page.evaluate(() => window.injected), undefined); assert.deepEqual(external, []);
  await upload(machine([1])); await page.locator('.machine').click();
  assert.match(await page.locator('#progress').innerText(), /1\/2台の数値 （全台は未確認）/);
  await upload(machine()); assert.match(await page.locator('#progress').innerText(), /2\/2台の数値 確認済/);
  await upload(rack); assert.equal(await page.locator('.badge.done').count(), 1);
  assert.match(await page.locator('#next').getAttribute('href'), /cd_dai=3#/);
  assert.equal(await page.locator('#day option').count(), 7);
  await page.locator('#machine-type').selectOption('normal');
  await page.waitForFunction(() => !document.getElementById('machine-type').disabled);
  await page.reload(); await page.locator('.machine').click();
  assert.equal(await page.locator('#machine-type').inputValue(), 'normal');
  assert.equal(await page.locator('.badge.done').count(), 1);
  const downloadPromise = page.waitForEvent('download'); await page.locator('#export').click();
  const download = await downloadPromise, exported = JSON.parse(await fs.readFile(await download.path(), 'utf8'));
  assert.equal(exported.records.length, 8); assert.equal(exported.records[0].max_hold, undefined);
  await upload({ name: 'bad.json', mimeType: 'application/json', buffer: Buffer.from('{broken') });
  assert.match(await page.locator('#status').innerText(), /前の内容が残っています/);
  assert.equal(await page.locator('.badge.done').count(), 1);
  await upload({ name: 'backup.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(exported)) });
  assert.equal(await page.locator('.record').count(), 2);
  for (const width of [320, 390, 768]) {
    await page.setViewportSize({ width, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  }
  assert.deepEqual(errors, []); assert.deepEqual(external, []);
  console.log('PASS: inert archive import, partial/full table, seven days, pending links, type, persistence, export/reimport, failed import preservation, 320/390/768px layout');
} finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
