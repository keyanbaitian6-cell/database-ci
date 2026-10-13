// 実ブラウザの入口・保存・差分キャッシュの試験。Android実機のインストール検証ではない。
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import http from 'node:http';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const repository = fileURLToPath(new URL('../../', import.meta.url));
let temporary = null;
const root = process.env.SHARE_WEB_ROOT || (temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'share-android-browser-')));
if (temporary) {
  const staged = spawnSync(process.env.PYTHON || 'python', ['database_android/tool/stage_share_viewer.py', root],
    {cwd: repository, encoding: 'utf8'});
  assert.equal(staged.status, 0, staged.stderr);
}
const server = http.createServer(async (req, res) => {
  const name = new URL(req.url, 'http://x').pathname.replace(/^\/database-share\//, '') || 'index.html';
  const file = path.resolve(root, name);
  if (!file.startsWith(path.resolve(root) + path.sep)) return res.writeHead(403).end();
  try {
    res.setHeader('content-type', /\.mjs$/.test(file) ? 'text/javascript' : /\.json$/.test(file)
      ? 'application/manifest+json' : /\.png$/.test(file) ? 'image/png' : 'text/html; charset=utf-8');
    res.end(await fs.readFile(file));
  } catch {res.writeHead(404).end();}
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const local = `http://127.0.0.1:${server.address().port}/database-share/`;
const base = process.env.SHARE_ANDROID_PUBLIC_BASE || local;
const id = 'AKfycbTEST' + 'x'.repeat(40);
const month = new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 7);
const day = month + '-02';
const hash = text => createHash('sha256').update(text).digest('hex');
function snapshot(site) {
  const records = site === 'meruhen' ? [
    {store: 'nagamachiminami', kind_code: 21, day, rack: 101, machine: '試験機種A', games: 3000, bb: 8, rb: 4, jo_net: 100},
    {store: 'saiwaichou', kind_code: 21, day, rack: 501, machine: '試験機種B', games: 4000, bb: 10, rb: 5, jo_net: 300},
  ] : [{store: 'c740601', rate: '20', day, rack: 801, machine: '試験機種C', games: 5000, bb: 12, rb: 6, my: 1000, net_medals: 500}];
  const text = JSON.stringify(records), part = {hash: hash(text), day, count: records.length, bytes: Buffer.byteLength(text)};
  return {text, manifest: {format: 'database-viewer-parts', version: 1, site, revision: hash(JSON.stringify(part)),
    header: {format: site === 'meruhen' ? 'database-backup' : 'pscube-viewer', version: 1, exported_at: day + 'T23:00:00+09:00', machines: []},
    parts: [part], count: records.length}};
}
const documents = {meruhen: snapshot('meruhen'), pscube: snapshot('pscube')};
const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
try {
  for (const width of [320, 393]) {
    const context = await browser.newContext({viewport: {width, height: 860}, isMobile: true, hasTouch: true});
    const partCalls = [], posts = [], errors = [];
    await context.route('https://script.google.com/**', async route => {
      const request = route.request(), params = new URL(request.url()).searchParams;
      if (request.method() === 'POST') {
        posts.push(JSON.parse(request.postData()));
        return route.fulfill({contentType: 'application/json', body: JSON.stringify({ok: true, changed: 1})});
      }
      const key = params.get('file') || '';
      let body;
      if (!key || key === 'pscube') {
        const site = key === 'pscube' ? 'pscube' : 'meruhen', data = documents[site];
        if (params.has('check')) body = {format: 'drive-check', version: 'parts:' + data.manifest.revision, parts: data.manifest};
        else if (params.has('parts')) {
          partCalls.push(site);
          body = {format: 'database-viewer-parts', revision: data.manifest.revision, parts: [{hash: data.manifest.parts[0].hash, text: data.text}]};
        } else throw new Error('差分対応の応答で全件取得を要求しました');
      } else body = {format: key === 'rainbow' ? 'database-rainbow' : 'database-events', version: 1, events: [], marks: []};
      return route.fulfill({contentType: 'application/json', body: JSON.stringify(body)});
    });
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(base + 'index.html#s=' + id + '&u=android-test');
    await page.waitForSelector('.grid');
    assert.equal(new URL(page.url()).hash, '');
    assert.deepEqual(partCalls.slice().sort(), ['meruhen', 'pscube']);
    await page.locator('[data-store="saiwaichou"]').click();
    // 既存の保存名と端末の🌈を置き、入口変更で消去されないことを確かめる。
    await page.evaluate(({day}) => {
      localStorage.setItem('database-viewer-remote', 'other-viewer-sentinel');
      localStorage.setItem('database-share-rainbow', JSON.stringify([{store: 'saiwaichou', day, rack: 501, on: true, updated_at: day + 'T23:59:00+09:00'}]));
      localStorage.setItem('database-share-idle-days', '3');
      localStorage.setItem('database-share-idle-games', '1000');
    }, {day});
    const storage = () => page.evaluate(() => Object.fromEntries(Object.keys(localStorage).map(k => [k, localStorage.getItem(k)])));
    const before = await storage();
    const normalManifest = await page.evaluate(async () => (await fetch(document.querySelector('link[rel="manifest"]').href)).json());
    assert.equal(normalManifest.display, 'browser');
    partCalls.length = 0;
    await page.goto(base + 'android.html');
    await page.waitForSelector('.grid');
    assert.deepEqual(await storage(), before);
    assert.deepEqual(partCalls, [], '通常入口のIndexedDBキャッシュを再利用する');
    assert.equal(await page.locator('.anchor[aria-pressed="true"]').innerText(), '幸町');
    const manifest = await page.evaluate(async () => (await fetch(document.querySelector('link[rel="manifest"]').href)).json());
    assert.equal(manifest.display, 'standalone'); assert.equal(manifest.id, './android.html');
    assert.equal(manifest.start_url, './android.html'); assert.equal(manifest.scope, './');
    await page.locator(`[data-open="${day}"]`).click();
    assert.match(await page.locator('.sheet').innerText(), /501番.*🌈/s);
    await page.getByRole('button', {name: '閉じる'}).click();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.reload(); await page.waitForSelector('.grid');
    assert.deepEqual(await storage(), before); assert.deepEqual(partCalls, []);
    const savedContext = await context.storageState({indexedDB: true});
    await context.close();
    // 新しいブラウザコンテキストで設定・IndexedDBを復元してstart_urlへ。
    const restarted = await browser.newContext({viewport: {width, height: 860}, storageState: savedContext});
    await restarted.route('https://script.google.com/**', route => {
      const params = new URL(route.request().url()).searchParams, key = params.get('file') || '';
      assert.equal(route.request().method(), 'GET');
      assert.equal(params.has('parts'), false, '再起動後もキャッシュを再利用する');
      const body = !key || key === 'pscube' ? (() => {
        const data = documents[key === 'pscube' ? 'pscube' : 'meruhen'];
        return {format: 'drive-check', version: 'parts:' + data.manifest.revision, parts: data.manifest};
      })() : {format: key === 'rainbow' ? 'database-rainbow' : 'database-events', version: 1, events: [], marks: []};
      return route.fulfill({contentType: 'application/json', body: JSON.stringify(body)});
    });
    const launched = await restarted.newPage();
    launched.on('pageerror', error => errors.push(error.message));
    await launched.goto(base + 'android.html'); await launched.waitForSelector('.grid');
    assert.equal(await launched.locator('.anchor[aria-pressed="true"]').innerText(), '幸町');
    // Android専用URLでも既存共有リンクの#処理と名前の更新が働く。
    await launched.goto(base + 'android.html#s=' + id + '&u=android-direct');
    await launched.waitForSelector('.grid');
    assert.equal(new URL(launched.url()).hash, '');
    assert.equal(await launched.evaluate(() => localStorage.getItem('database-share-name')), 'android-direct');
    assert.equal(await launched.evaluate(() => localStorage.getItem('database-share-script-id')), id);
    assert.equal(await launched.evaluate(() => localStorage.getItem('database-viewer-remote')), 'other-viewer-sentinel');
    assert.deepEqual(posts, []); assert.deepEqual(errors, []);
    await restarted.close();
  }
  console.log('PASS: 通常→Android入口、320/393px、共有リンクの#処理、店舗・呼び名・🌈・IndexedDBキャッシュ保持、再読込・再起動相当（実機インストールは未確認）');
} finally {
  await browser.close(); await new Promise(resolve => server.close(resolve));
  if (temporary) await fs.rm(temporary, {recursive: true, force: true});
}
