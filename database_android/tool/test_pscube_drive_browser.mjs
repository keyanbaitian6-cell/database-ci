// Run with Playwright installed: node tool/test_pscube_drive_browser.mjs
// Optional: PLAYWRIGHT_MODULE=/absolute/path/to/playwright-core/index.mjs  CHROMIUM_PATH=/path/to/chrome
// The Drive (Apps Script) endpoint is mocked; nothing leaves the machine.
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
const base = 'https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/cgi-bin/';
const machine = { store: 'c740601', rate: '20', machine: 'テスト機種', expected_count: 2, machine_type: null, url: `${base}nc-v05-011.php?cd_ps=2&bai=20` };
const rec = (rack, day, games) => ({ store: 'c740601', rate: '20', machine: machine.machine, rack, day, bb: 5, rb: 3, at_art: 0, games, my: 900,
  observed_at: `${day}T12:00:00+09:00`, detail_url: `${base}nc-v06-001.php?cd_dai=${rack}#${day.replaceAll('-', '')}`, graph: null });
const doc = (exportedAt, games) => ({ format: 'pscube-viewer', version: 1, kind: 'viewer', source: 'pc', exported_at: exportedAt,
  machines: [machine], records: [rec(1, '2026-10-01', games), rec(2, '2026-10-01', 3100)] });
const SCRIPT = 'https://script.google.com/macros/s/AKfycb_TEST/exec';
let reply = doc('2026-10-01T20:00:00+09:00', 3000), requests = [];
const errors = [], external = [];
async function open(context) {
  const page = await context.newPage();
  page.on('pageerror', e => errors.push(e.message));
  page.on('request', r => { if (!r.url().startsWith(origin)) external.push(r.url()); });
  await page.route('https://script.google.com/**', route => { requests.push(route.request().url());
    route.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: JSON.stringify(reply) }); });
  return page;
}
const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
let page = await open(context);
await page.goto(`${origin}/pscube/index.html`);
await page.waitForSelector('#drive-status');
assert.equal(await page.locator('#drive-refresh').isHidden(), true);
assert.match(await page.innerText('#drive-status'), /未設定/);
assert.equal(requests.length, 0);

// URLの形が違えば保存せず、通信もしない
await page.click('#drive-setup summary');
await page.fill('#drive-url', 'https://evil.example/x');
await page.click('#drive-save');
assert.match(await page.innerText('#drive-status'), /GoogleのスクリプトのURL/);
assert.equal(requests.length, 0);

// 正しいURL：保存して読む → 機種が出る
await page.fill('#drive-url', SCRIPT);
await page.click('#drive-save');
await page.waitForFunction(() => /読み込みました/.test(document.getElementById('drive-status').textContent));
assert.deepEqual(requests, [`${SCRIPT}?file=pscube`]);
assert.equal(await page.locator('.machine').count(), 1);
assert.equal(await page.evaluate(() => localStorage.getItem('database-viewer-remote')), SCRIPT);

// 開き直し：同じ書き出し時刻なら「変わっていません」で中身は触らない
await page.reload();
await page.waitForFunction(() => /変わっていません/.test(document.getElementById('drive-status').textContent));
assert.equal(requests.length, 2);
assert.equal(await page.locator('.machine').count(), 1);

// 新しい書き出し：読み込んで統合（台1の回転数が増える）
reply = doc('2026-10-02T08:00:00+09:00', 3600);
await page.click('#drive-refresh');
await page.waitForFunction(() => /読み込みました/.test(document.getElementById('drive-status').textContent));
await page.locator('.machine').click();
assert.match(await page.locator('.record').first().innerText(), /3,600/);

// 違うファイル（更新前のスクリプト）・エラー・オフラインでは前の内容を残す
reply = { format: 'database-backup', exported_at: 'x' };
await page.click('#drive-refresh');
await page.waitForFunction(() => /Apps Scriptを更新/.test(document.getElementById('drive-status').textContent));
assert.match(await page.locator('.record').first().innerText(), /3,600/);
reply = { error: 'pscube-viewer-drive.json がGoogleドライブに見つかりません。' };
await page.click('#drive-refresh');
await page.waitForFunction(() => /見つかりません/.test(document.getElementById('drive-status').textContent));

// バックアップの書き出し：名前と中身
const [download] = await Promise.all([page.waitForEvent('download'), page.click('#export')]);
assert.match(download.suggestedFilename(), /^pscube-backup-browser-\d{8}-\d{6}\.json$/);
const saved = JSON.parse(await fs.readFile(await download.path(), 'utf8'));
assert.equal(saved.kind, 'backup'); assert.equal(saved.source, 'browser'); assert.equal(saved.records.length, 2);
assert.match(saved.exported_at, /[+-]\d\d:\d\d$/);

// 設定を消す（開き直したので、設定欄は閉じている）
await page.click('#drive-setup summary');
await page.click('#drive-forget');
assert.equal(await page.evaluate(() => localStorage.getItem('database-viewer-remote')), null);
assert.equal(await page.locator('#drive-refresh').isHidden(), true);

assert.deepEqual(errors, []);
assert.deepEqual(external, [`${SCRIPT}?file=pscube`, `${SCRIPT}?file=pscube`, `${SCRIPT}?file=pscube`, `${SCRIPT}?file=pscube`, `${SCRIPT}?file=pscube`]);
await browser.close(); server.close();
console.log('PASS: Drive設定・読み込み・変更なし判定・統合・別ファイル/エラーで内容保持・書き出し名・設定消去');
