// 実IndexedDB・Service Worker・オフライン再起動。Googleの記録は合成データだけ。
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(process.env.SHARE_WEB_ROOT || fileURLToPath(new URL('../../share_viewer/', import.meta.url)));
const server = http.createServer(async (req, res) => {
  const file = path.resolve(root, new URL(req.url, 'http://x').pathname.slice(7) || 'index.html');
  if (!file.startsWith(root + path.sep)) return res.writeHead(403).end();
  try { res.setHeader('content-type', /\.m?js$/.test(file) ? 'text/javascript' : file.endsWith('.png') ? 'image/png' : file.endsWith('.json') ? 'application/json' : 'text/html');
    res.end(await fs.readFile(file)); } catch { res.writeHead(404).end(); }
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const origin = process.env.SHARE_HISTORY_PUBLIC_BASE || `http://127.0.0.1:${server.address().port}/share/`;
const id = 'AKfycbTEST' + 'x'.repeat(40), endpoint = `https://script.google.com/macros/s/${id}/exec`;
const hash = text => createHash('sha256').update(text).digest('hex');
const ym = new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 7);
let generation = 1, requests = [], broken = false;
function snapshot(site) {
  const dayList = ['2025-01-01', `${ym}-02`];
  const rows = dayList.filter((_, i) => generation < 3 || i === 0).map((day, i) => ({
    store: site === 'meruhen' ? 'saiwaichou' : 'c740601', kind_code: 21, rate: '20',
    day, rack: 537, machine: '履歴試験機種', games: 5000, bb: 20, rb: 10, at_art: 0, my: 1000,
    detail_url: `https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/cgi-bin/nc-v06-001.php?cd_dai=537#${day.replaceAll('-', '')}`,
    jo_net: i ? generation * 100 : 200, net_medals: i ? generation * 100 : 200}));
  const texts = rows.map(r => JSON.stringify([r]));
  const parts = texts.map((text, i) => ({hash: hash(text), day: rows[i].day, count: 1, bytes: Buffer.byteLength(text)}));
  const header = {format: site === 'meruhen' ? 'database-backup' : 'pscube-viewer', version: 1, source: 'pc-viewer',
    exported_at: `2026-10-14T12:00:0${generation}Z`, date_events: [], machines: site === 'meruhen' ? [] : [{
      store: 'c740601', rate: '20', machine: '履歴試験機種', expected_count: 1,
      url: 'https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/cgi-bin/nc-v05-011.php?bai=20'}]};
  return {m: {format: 'database-viewer-parts', version: 2, site, days: dayList, revision: hash(JSON.stringify(parts)), header, parts, count: rows.length}, texts};
}
const browser = await chromium.launch({executablePath: process.env.CHROMIUM_PATH || undefined, headless: true, args: ['--no-sandbox']});
try {
  const context = await browser.newContext({viewport: {width: 393, height: 850}}), page = await context.newPage(), errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await context.route('https://script.google.com/**', route => {
    const p = new URL(route.request().url()).searchParams; requests.push(Object.fromEntries(p));
    let doc;
    if (!p.get('file') || p.get('file') === 'pscube') {
      const {m, texts} = snapshot(p.get('file') ? 'pscube' : 'meruhen');
      if (p.has('check')) doc = {format: 'drive-check', version: 'parts:' + m.revision, parts: m};
      else if (p.has('parts')) doc = {format: m.format, revision: m.revision,
        parts: p.get('parts').split(',').map(h => ({hash: h, text: broken ? '[]' : texts[m.parts.findIndex(p => p.hash === h)]}))};
      else throw new Error('全件を要求しました');
    } else doc = {format: p.get('file') === 'rainbow' ? 'database-rainbow' : 'database-events', version: 1, events: [], marks: []};
    return route.fulfill({contentType: 'application/json', body: JSON.stringify(doc)});
  });
  await page.goto(origin + 'index.html');
  // 昨夜のv1 DBを先に用意し、旧保存を残したままv2へ上げる。
  await page.evaluate(async ({endpoint, text, digest}) => {
    await new Promise((resolve, reject) => {
      const req = indexedDB.open('database-viewer-parts-v1', 1);
      req.onupgradeneeded = () => req.result.createObjectStore('snapshots');
      req.onsuccess = () => {
        const db = req.result, tx = db.transaction('snapshots', 'readwrite');
        tx.objectStore('snapshots').put({parts: {[digest]: text}}, endpoint + '|meruhen');
        tx.oncomplete = () => {db.close(); resolve();}; tx.onerror = () => reject(tx.error);
      };
    });
  }, {endpoint, text: snapshot('meruhen').texts[0], digest: snapshot('meruhen').m.parts[0].hash});
  await page.goto(origin + 'index.html#s=' + id); await page.waitForSelector('.grid');
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.waitForFunction(() => !!navigator.serviceWorker.controller);
  const read = () => page.evaluate(async endpoint => {
    const {readViewerHistory} = await import('./viewer_parts.mjs');
    return Promise.all(['meruhen', 'pscube'].map(s => readViewerHistory(endpoint, s)));
  }, endpoint);
  assert.deepEqual((await read()).map(d => d.records.length), [2, 2]);
  const noRewrite = await page.evaluate(async ({endpoint, m, texts}) => {
    const {fetchViewerParts} = await import('./viewer_parts.mjs');
    const put = IDBObjectStore.prototype.put; let dayWrites = 0;
    IDBObjectStore.prototype.put = function(...args) { if (this.name === 'history-days') dayWrites++; return put.apply(this, args); };
    try {
      await fetchViewerParts(endpoint, 'meruhen', m, async () => {throw new Error('変更なしで通信しました');});
      return dayWrites;
    } finally { IDBObjectStore.prototype.put = put; }
  }, {endpoint, ...snapshot('meruhen')});
  assert.equal(noRewrite, 0, '変更のない日を保存し直さない');
  requests = []; generation = 2;
  await page.reload(); await page.waitForSelector('.grid'); assert.equal(requests.length, 0);
  await context.setOffline(true);
  await page.reload(); await page.waitForSelector('.grid'); assert.equal(requests.length, 0);
  if (await fs.stat(path.join(root, 'android.html')).catch(() => null)) {
    await page.goto('about:blank'); await page.goto(origin + 'android.html');
    await page.waitForSelector('.grid');
    assert.equal(requests.length, 0);
    assert.match(await page.locator('link[rel="manifest"]').getAttribute('href'), /manifest-android/);
    assert.equal(await page.evaluate(async () => (await (await fetch(document.querySelector('link[rel="manifest"]').href)).json()).display), 'standalone');
    await page.goto(origin + 'index.html'); await page.waitForSelector('.grid');
  }
  // Chromiumのネットワーク遮断と、OSが通知するオフライン状態をそれぞれ再現する。
  await page.evaluate(() => Object.defineProperty(navigator, 'onLine', {get: () => false, configurable: true}));
  await page.locator('#reload').click();
  await page.waitForFunction(() => document.querySelector('[role=status]')?.textContent.includes('オフライン'));
  assert.deepEqual((await read()).map(d => d.records.length), [2, 2]);
  await context.setOffline(false);
  await page.evaluate(() => Object.defineProperty(navigator, 'onLine', {get: () => true, configurable: true}));
  await page.locator('#reload').click(); await page.waitForFunction(() => !document.querySelector('#reload').disabled);
  assert.deepEqual(requests.filter(p => p.parts).map(p => p.parts.split(',').length), [1, 1]);
  assert.deepEqual((await read()).map(d => d.records.find(r => r.day.endsWith('-02')).games), [5000, 5000]);
  const newer = snapshot('meruhen'); generation = 1;
  const stale = snapshot('meruhen'); generation = 2;
  assert.equal(await page.evaluate(async ({endpoint, m, texts}) => {
    const {fetchViewerParts} = await import('./viewer_parts.mjs');
    try {
      await fetchViewerParts(endpoint, 'meruhen', m, async url => ({format: m.format, revision: m.revision,
        parts: new URL(url).searchParams.get('parts').split(',').map(hash => ({hash, text: texts[m.parts.findIndex(p => p.hash === hash)]}))}));
      return false;
    } catch { return true; }
  }, {endpoint, ...stale}), true, '古い通信が後で完了しても保存を巻き戻さない');
  assert.equal((await read())[0].exported_at, newer.m.header.exported_at);
  generation = 3; requests = [];
  await page.locator('#reload').click(); await page.waitForFunction(() => !document.querySelector('#reload').disabled);
  assert.equal(requests.filter(p => p.parts).length, 0);
  assert.deepEqual((await read()).map(d => d.records.map(r => r.day)), [['2025-01-01'], ['2025-01-01']]);
  generation = 2; broken = true;
  await page.locator('#reload').click(); await page.waitForFunction(() => !document.querySelector('#reload').disabled);
  assert.ok(await page.locator('.grid').isVisible());
  assert.deepEqual((await read()).map(d => d.records.length), [1, 1]);
  // 保存が欠損した場合も、残った履歴を空と見なして自動上書きしない。
  await page.evaluate(async endpoint => {
    await new Promise((resolve, reject) => {
      const request = indexedDB.open('database-viewer-parts-v1', 2);
      request.onsuccess = () => {
        const db = request.result, tx = db.transaction('history-days', 'readwrite');
        tx.objectStore('history-days').delete(endpoint + '|meruhen|2025-01-01');
        tx.oncomplete = () => {db.close(); resolve();}; tx.onerror = () => reject(tx.error);
      };
    });
  }, endpoint);
  requests = []; await page.reload(); await page.waitForSelector('.grid');
  assert.equal(requests.length, 0); assert.match(await page.locator('[role=status]').innerText(), /保存データを開けません/);
  assert.deepEqual(errors, []);
  await context.close();
  console.log('PASS: 旧DB移行・起動時通信0・完全オフライン再起動・手動差分・日削除・破損通信時の保存保持');
} finally { await browser.close(); await new Promise(r => server.close(r)); }
