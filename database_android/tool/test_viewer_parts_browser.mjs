// 実ブラウザ・実IndexedDB・両Webページ。Googleへの通信は合成データで置き換える。
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const roots = {viewer: process.env.VIEWER_WEB_ROOT || fileURLToPath(new URL('../build/web/', import.meta.url)),
  share: process.env.SHARE_WEB_ROOT || fileURLToPath(new URL('../../share_viewer/', import.meta.url))};
const server = http.createServer(async (req, res) => {
  let [area, ...pieces] = new URL(req.url, 'http://x').pathname.slice(1).split('/');
  if (area === 'database-viewer') area = 'viewer';
  if (!roots[area]) return res.writeHead(404).end();
  const root = path.resolve(roots[area]), file = path.resolve(root, pieces.join('/') || 'index.html');
  if (!file.startsWith(root + path.sep)) return res.writeHead(403).end();
  try {res.setHeader('content-type', /\.m?js$/.test(file) ? 'text/javascript' : 'text/html; charset=utf-8'); res.end(await fs.readFile(file));}
  catch {res.writeHead(404).end();}
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const origin = `http://127.0.0.1:${server.address().port}`;
const viewerPage = process.env.VIEWER_PUBLIC_URL || `${origin}/database-viewer/index.html`;
const sharePage = process.env.SHARE_PUBLIC_URL || `${origin}/share/index.html`;
const id = 'AKfycbTEST' + 'x'.repeat(40), url = `https://script.google.com/macros/s/${id}/exec`;
const ym = new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 7);
const hash = text => createHash('sha256').update(text).digest('hex');
function snapshot(site, generation) {
  const records = [1, 2].map(day => ({store: site === 'meruhen' ? 'saiwaichou' : 'c740601', kind_code: 21, rate: '20',
    day: `${ym}-0${day}`, rack: 537, machine: '試験機種', games: 5000, bb: 20, rb: 10, at_art: 0, my: 1000,
    detail_url: `https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/cgi-bin/nc-v06-001.php?cd_dai=537#${ym.replace('-', '')}0${day}`,
    jo_net: day === 1 ? generation * 100 : 200, net_medals: day === 1 ? generation * 100 : 200}));
  const texts = records.map(r => JSON.stringify([r]));
  const parts = texts.map((text, i) => ({hash: hash(text), day: records[i].day, count: 1, bytes: Buffer.byteLength(text)}));
  const header = {format: site === 'meruhen' ? 'database-backup' : 'pscube-viewer', version: 1,
    source: 'pc-viewer', exported_at: `2026-10-13T12:00:0${generation}Z`, machines: site === 'meruhen' ? [] : [
      {store: 'c740601', rate: '20', machine: '試験機種', expected_count: 1,
        url: 'https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/cgi-bin/nc-v05-011.php?bai=20'}], date_events: []};
  return {manifest: {format: 'database-viewer-parts', version: 1, site, revision: hash(JSON.stringify(parts)), header, parts, count: 2}, texts};
}
const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
try {
  for (const area of ['viewer', 'share']) {
    const context = await browser.newContext({viewport: {width: 393, height: 850}}), calls = [];
    let generation = 1;
    await context.route('https://script.google.com/**', route => {
      const params = new URL(route.request().url()).searchParams, key = params.get('file') || '';
      let body;
      if (key === '' || key === 'pscube') {
        const {manifest, texts} = snapshot(key === 'pscube' ? 'pscube' : 'meruhen', generation);
        if (params.has('check')) body = {format: 'drive-check', version: 'parts:' + manifest.revision, parts: manifest};
        else if (params.has('parts')) {
          const hashes = params.get('parts').split(','); calls.push({site: manifest.site, count: hashes.length});
          body = {format: manifest.format, revision: manifest.revision, parts: hashes.map(h => ({hash: h,
            text: texts[manifest.parts.findIndex(p => p.hash === h)]}))};
        } else throw new Error('差分対応後に全件JSONを要求しました');
      } else body = {format: key === 'rainbow' ? 'database-rainbow' : 'database-events', version: 1, events: [], marks: []};
      return route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
    });
    const page = await context.newPage(), errors = [];
    page.on('pageerror', e => errors.push(e.message));
    if (area === 'viewer') {
      // DOMのブリッジを単独で試す。FlutterのUIは既存の全画面試験で別途検証。
      await page.route('**/flutter_bootstrap.js', route => route.fulfill({contentType: 'text/javascript', body: ''}));
      await page.goto(viewerPage);
      const read = () => page.evaluate(async url => {
        const meruhen = JSON.parse(await window.databaseViewer.fromRemote(url, null));
        const {fetchDrive} = await import('./pscube/sync.mjs');
        const pscube = await fetchDrive(url, null);
        return [meruhen.records, pscube.data.records];
      }, url);
      assert.deepEqual((await read()).map(rows => rows.length), [2, 2]);
      assert.deepEqual(calls, [{site: 'meruhen', count: 2}, {site: 'pscube', count: 2}]);
      calls.length = 0; generation = 2;
      assert.deepEqual((await read()).map(rows => rows[0].games), [5000, 5000]);
      assert.deepEqual(calls, [{site: 'meruhen', count: 1}, {site: 'pscube', count: 1}]);
      calls.length = 0; await page.reload(); await read(); assert.equal(calls.length, 0);
    } else {
      await page.goto(`${sharePage}#s=${id}`); await page.waitForSelector('.grid');
      assert.deepEqual(calls.slice().sort((a, b) => a.site.localeCompare(b.site)), [{site: 'meruhen', count: 2}, {site: 'pscube', count: 2}]);
      calls.length = 0; generation = 2; await page.reload(); await page.waitForSelector('.grid');
      assert.equal(calls.length, 0); // 起動時は保存済み。手動更新だけ通信する。
      await page.locator('#reload').click();
      await page.waitForFunction(() => !document.querySelector('#reload').disabled);
      assert.deepEqual(calls.slice().sort((a, b) => a.site.localeCompare(b.site)), [{site: 'meruhen', count: 1}, {site: 'pscube', count: 1}]);
      calls.length = 0; await page.reload(); await page.waitForSelector('.grid'); assert.equal(calls.length, 0);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    }
    assert.deepEqual(errors, []); await context.close();
  }
  console.log('PASS: 両サイト・両ページで初回2日→更新1日だけ→再読込0日（実IndexedDB、模擬Google）');
} finally {await browser.close(); await new Promise(r => server.close(r));}
