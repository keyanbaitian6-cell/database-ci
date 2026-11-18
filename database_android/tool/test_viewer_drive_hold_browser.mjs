// Build viewer_main.dart and stage_viewer.py before this browser test.
// 前回の「Googleドライブの更新」が途中で終わっていたら、そこから6時間は起動時の自動更新をしない
// （2026-11-18：更新のたびにiPhoneのSafariが落ち、ページが開けなくなった。落ちの連鎖を止める保険）。
// 手動の更新ボタンはいつでも使え、最後まで終われば止める印は消える。Googleのスクリプトは偽物（page.route）。
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = process.env.VIEWER_WEB_ROOT || fileURLToPath(new URL('../build/web/', import.meta.url));
const prefix = '/database-viewer/';
const server = http.createServer(async (req, res) => {
  let url = new URL(req.url, 'http://localhost').pathname;
  if (url === '/setup') { res.setHeader('content-type', 'text/html'); res.end('<!doctype html><body>setup</body>'); return; }
  if (!url.startsWith(prefix)) { res.writeHead(404).end(); return; }
  url = url.slice(prefix.length);
  const local = path.resolve(root, (!url || url.endsWith('/')) ? url + 'index.html' : url);
  if (!local.startsWith(path.resolve(root) + path.sep)) { res.writeHead(403).end(); return; }
  try {
    const body = await fs.readFile(local), ext = path.extname(local);
    res.setHeader('content-type', ({'.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json',
      '.wasm': 'application/wasm', '.html': 'text/html', '.css': 'text/css', '.png': 'image/png'})[ext] || 'application/octet-stream');
    res.end(body);
  } catch { res.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const origin = 'http://127.0.0.1:' + server.address().port;
const script = 'https://script.google.com/macros/s/TEST_DRIVE_HOLD/exec';
const HOUR = 3600 * 1000;
const NOTICE = '前回の更新が途中で止まったため、自動更新を止めています';

const records = [{store: 'nagamachiminami', day: '2026-10-10', machine: '化物語', rack: 1085, games: 3000, bb: 10, rb: 5, max_hold: 1000}];
const stored = {header: {format: 'database-backup', version: 1, source: 'pc', exported_at: '2026-10-10T23:00:00+09:00'}, records};
// Googleに新しい書き出し（1時間あと）がある。古いスクリプトの形（全文をそのまま返す）。
const fresh = {format: 'database-backup', version: 1, source: 'pc', exported_at: '2026-10-11T00:00:00+09:00', date_events: [],
  records: [...records, {...records[0], day: '2026-10-11', rack: 1086}]};

const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
try {
  // [running]：前に開いたページが、更新の途中で終わったことにする記録（始めた時刻）。null なら記録なし。
  async function scenario(name, running, work) {
    const context = await browser.newContext({viewport: {width: 393, height: 852}});
    const page = await context.newPage();
    const errors = [], requests = [];
    page.on('pageerror', e => errors.push(e.message));
    await context.route('https://script.google.com/**', route => {
      const url = route.request().url();
      requests.push(url);
      const headers = {'access-control-allow-origin': '*'};
      if (url.includes('check=1')) return route.fulfill({status: 200, contentType: 'application/json', headers, body: JSON.stringify({format: 'drive-check', version: 'v1', name: 'database-viewer.json'})});
      if (url.includes('file=')) return route.fulfill({status: 200, contentType: 'application/json', headers, body: JSON.stringify({error: 'この試験では共有ファイルを返しません。'})});
      return route.fulfill({status: 200, contentType: 'application/json', headers, body: JSON.stringify(fresh)});
    });
    await page.goto(origin + '/setup');
    await page.evaluate(async ({data, script, running}) => {
      localStorage.setItem('database-viewer-remote', script);
      if (running) localStorage.setItem('database-viewer-diag', JSON.stringify({version: 1, running: {phase: 'drive', at: running}, phases: {}}));
      const db = await new Promise((resolve, reject) => { const q = indexedDB.open('database-viewer', 1); q.onupgradeneeded = () => q.result.createObjectStore('kv'); q.onsuccess = () => resolve(q.result); q.onerror = () => reject(q.error); });
      await new Promise((resolve, reject) => { const tx = db.transaction('kv', 'readwrite'); tx.objectStore('kv').put(JSON.stringify(data), 'data'); tx.oncomplete = resolve; tx.onerror = () => reject(tx.error); }); db.close();
    }, {data: stored, script, running});
    const diag = () => page.evaluate(() => JSON.parse(localStorage.getItem('database-viewer-diag') || 'null'));
    const home = async () => {
      await page.goto(origin + prefix);
      await page.waitForSelector('flt-glass-pane', {state: 'attached', timeout: 60000});
      const p = page.locator('flt-semantics-placeholder'); if (await p.count()) await p.evaluate(e => e.click());
      await page.getByText('database 閲覧', {exact: true}).waitFor({timeout: 60000});
    };
    try { await work({page, requests, diag, home, errors}); }
    catch (error) { error.message = `[${name}] ${error.message}`; throw error; }
    assert.deepEqual(errors, [], `[${name}] pageerror`);
    await context.close();
  }
  const updated = (page) => page.getByText('Googleドライブの最新（2台）を読み込みました。', {exact: false}).first();
  const settle = async (page, requests, ms = 4000) => { await page.waitForTimeout(ms); return requests.length; };

  // 1時間前に更新の途中で終わっていた：自動更新は呼ばない。画面に理由を出す。手動なら読める。成功したら印は消える。
  await scenario('途中の印あり', new Date(Date.now() - HOUR).toISOString(), async ({page, requests, diag, home}) => {
    await home();
    await page.getByText(NOTICE, {exact: false}).waitFor({timeout: 30000});
    assert.equal(await settle(page, requests), 0, '起動時の自動更新を呼ばない（Googleへ通信しない）');
    const held = await diag();
    assert.ok(held.drive_halt?.at, '止める印が残っている');
    assert.equal(held.phases.drive.unfinished, 1, '途中で終わった回数は今までどおり数える');
    // 開き直しても、6時間たつまでは止めたまま。
    await home();
    await page.getByText(NOTICE, {exact: false}).waitFor({timeout: 30000});
    assert.equal(await settle(page, requests), 0, '開き直しても自動更新を呼ばない');
    // 手動の更新はいつでも使える。
    await page.getByRole('button', {name: 'Googleドライブの最新を読み込む'}).click();
    await updated(page).waitFor({timeout: 60000});
    assert.ok(requests.some(url => url.includes('check=1')), '手動の更新は通信する');
    // 知らせのあとも、共有の取り込みと日別キャッシュの照合（B0〜B2、`running` が calendar・scores など）が続く。
    // それが終わってから確かめる（2026-11-18、知らせの直後に calendar の途中で落ちた）。
    for (let i = 0; i < 80 && (await diag()).running !== null; i++) await page.waitForTimeout(250);
    const done = await diag();
    assert.equal(done.drive_halt, undefined, '手動の更新が最後まで終わったら印を消す');
    assert.equal(done.running, null);
    // 次に開いたときは、また自動で更新する。
    requests.length = 0;
    await home();
    // 前のページの共有の取り込み（?file=events・?file=rainbow）が、ここで数え直したあとに届くことがある。
    // 「何か通信したか」ではなく、更新の確認（check=1）が来るまで待つ（2026-11-18、CIの遅い機械で落ちた）。
    for (let i = 0; i < 40 && !requests.some(url => url.includes('check=1')); i++) await page.waitForTimeout(250);
    assert.ok(requests.some(url => url.includes('check=1')), '印が消えたあとは自動更新を呼ぶ');
  });

  // 7時間前に終わっていた：6時間たっているので、自動更新を呼ぶ。最後まで終われば印は消える。
  await scenario('6時間たった', new Date(Date.now() - 7 * HOUR).toISOString(), async ({page, requests, diag, home}) => {
    await home();
    await updated(page).waitFor({timeout: 60000});
    assert.ok(requests.some(url => url.includes('check=1')), '6時間たてば自動更新を呼ぶ');
    assert.equal(await page.getByText(NOTICE, {exact: false}).count(), 0, '止めている知らせは出さない');
    const done = await diag();
    assert.equal(done.drive_halt, undefined, '自動の更新が最後まで終わったら印を消す');
    assert.equal(done.phases.drive.unfinished, 1);
  });

  // 記録なし（ふつうの端末）：今までどおり自動で更新する。
  await scenario('記録なし', null, async ({page, requests, home}) => {
    await home();
    await updated(page).waitFor({timeout: 60000});
    assert.ok(requests.some(url => url.includes('check=1')));
    assert.equal(await page.getByText(NOTICE, {exact: false}).count(), 0);
  });
  console.log('PASS: 更新の途中で終わった記録があれば6時間は自動更新しない／手動は使える／終われば印が消える（実ブラウザ・実ビルド）');
} finally {
  await browser.close();
  await new Promise(resolve => server.close(resolve));
}
