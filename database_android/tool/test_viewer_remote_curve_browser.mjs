// Build viewer_main.dart and stage_viewer.py before this browser test.
// 閲覧ページ（iPhone）のグラフの線は起動時に読まず、機種・台の画面を開いたときにその日の分だけ読む
// （2026-10-25、Safariがメモリ不足で落ちていた）。線を読む前も後も、推定差枚は線から計算した値と同じ。
// Googleのスクリプトは偽物（context.route）で、外へは出ない。
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {signedMedalsForTest} from './viewer_test_format.mjs';
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
const script = 'https://script.google.com/macros/s/TEST_REMOTE_CURVE/exec';
const sha = text => createHash('sha256').update(text).digest('hex');

// 合成データ（tool/make_meruhen_net_parity.mjs）から、推定差枚が出る3台を使う。
const parity = JSON.parse(await fs.readFile(new URL('../test/fixtures/meruhen_net_parity.json', import.meta.url), 'utf8'));
const day = '2026-10-10', picked = [];
parity.records.forEach((r, i) => {
  if (picked.length < 3 && parity.expected[i].value !== null && r.games <= 20000 && (r.max_hold ?? 0) <= 100000) picked.push(i);
});
const curves = [], records = picked.map((i, k) => {
  const r = parity.records[i], {curve, ...graph} = r.graph_measurement;
  curves.push([k, curve]);
  return {store: 'saiwaichou', kind_code: 21, day, machine: '線試験機種', rack: 1085 + k, games: r.games, bb: 10, rb: 5,
    ...(r.max_hold === undefined ? {} : {max_hold: r.max_hold}),
    graph_measurement: {...graph, curve_remote: true, curve_index: k,
      net_estimate: {...parity.expected[i], max_hold: r.max_hold ?? null, games: r.games ?? 0}}};
});
const expectedText = picked.map(i => signedMedalsForTest(parity.expected[i].value) + (parity.expected[i].needs_check ? '※' : ''));
const curveText = JSON.stringify({curves, day});
const ref = {day, hash: sha(curveText), count: curves.length, bytes: Buffer.byteLength(curveText)};
const meruhen = {header: {format: 'database-backup', version: 1, source: 'pc-viewer', exported_at: '2026-10-10T23:00:00+09:00',
  curve_parts: [ref]}, records};

const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
try {
  for (const failFirst of [false, true]) {
    const context = await browser.newContext({viewport: {width: 393, height: 852}});
    const page = await context.newPage(), errors = [], curveRequests = [], posts = [];
    page.on('pageerror', e => errors.push(e.message));
    let failing = failFirst;
    await context.route('https://script.google.com/**', route => {
      const url = new URL(route.request().url()), headers = {'access-control-allow-origin': '*'};
      const json = body => route.fulfill({status: 200, contentType: 'application/json', headers, body: JSON.stringify(body)});
      if (route.request().method() === 'POST') { posts.push(JSON.parse(route.request().postData())); return json({ok: true, marks: 1, changed: 1}); }
      if (url.searchParams.has('curves')) {
        curveRequests.push(url.searchParams.get('curves'));
        if (failing) return json({error: '試験の読み込み失敗'});
        return json({format: 'database-viewer-curves', hash: ref.hash, text: curveText});
      }
      const file = url.searchParams.get('file');
      if (file) return json({format: file === 'rainbow' ? 'database-rainbow' : 'database-events', version: 1, events: [], marks: []});
      return json({error: 'この試験では閲覧用ファイルを返しません。'});
    });
    await page.goto(origin + '/setup');
    await page.evaluate(async ({data, script}) => {
      localStorage.setItem('database-viewer-remote', script);
      const db = await new Promise((resolve, reject) => { const q = indexedDB.open('database-viewer', 1); q.onupgradeneeded = () => q.result.createObjectStore('kv'); q.onsuccess = () => resolve(q.result); q.onerror = () => reject(q.error); });
      await new Promise((resolve, reject) => { const tx = db.transaction('kv', 'readwrite'); tx.objectStore('kv').put(JSON.stringify(data), 'data'); tx.oncomplete = resolve; tx.onerror = () => reject(tx.error); }); db.close();
    }, {data: meruhen, script});
    const labels = () => page.locator('flt-semantics').evaluateAll(es => es.map(e => e.getAttribute('aria-label') || e.textContent || '').join('\n'));
    const seen = async (text, message) => {
      for (let i = 0; i < 80; i++) { if ((await labels()).includes(text)) return; await page.waitForTimeout(100); }
      assert.fail(`${message}：${text}`);
    };
    try {
      await page.goto(origin + prefix);
      await page.waitForSelector('flt-glass-pane', {state: 'attached', timeout: 60000});
      const p = page.locator('flt-semantics-placeholder'); if (await p.count()) await p.evaluate(e => e.click());
      await page.getByText('database 閲覧', {exact: true}).waitFor({timeout: 60000});
      assert.deepEqual(curveRequests, [], '起動時は線を読まない');
      await page.getByRole('button', {name: '幸町', exact: true}).click().catch(() => {});
      await page.mouse.move(200, 700); await page.mouse.wheel(0, 2200); await page.waitForTimeout(300);
      const machine = page.getByRole('button', {name: /^線試験機種/}).last();
      await machine.scrollIntoViewIfNeeded(); await machine.click();
      await page.getByText('データ表示', {exact: true}).waitFor();
      // 機種の画面（表）：差枚は添えた値。表だけなら線は読まない。
      for (const text of expectedText) await seen(text, '機種の画面の推定差枚');
      assert.deepEqual(curveRequests, [], '表だけなら線を読まない');
      // グラフ表示：3台の小さなグラフのために、その日の線を1回だけ読む。
      await page.getByText('グラフ表示', {exact: true}).click();
      for (let i = 0; i < 50 && !curveRequests.length; i++) await page.waitForTimeout(100);
      assert.deepEqual(curveRequests.slice(0, 1), [ref.hash]);
      await page.getByText('データ表示', {exact: true}).click();
      await page.getByText(/^1085/).first().click();
      if (failFirst) {
        await seen('グラフの線を読み込めませんでした（もう一度読む）', '読めないときの案内');
        await seen(expectedText[0], '線が読めなくても推定差枚は出る');
        failing = false;
        await page.getByRole('button', {name: 'グラフの線を読み込めませんでした（もう一度読む）'}).click();
      }
      await seen('保存時のグラフの線から描いたグラフです。', '台の画面で線を描く');
      await seen(expectedText[0], '線を読んだあとの推定差枚');
      assert.equal(curveRequests.length, failFirst ? 3 : 1, failFirst ? '失敗した日は覚えず読み直す' : '同じ日の線は読み直さない');
      // 🌈だけの付け外しでは、読んだ線をそのまま使う（付け外しのたびに読み直していた、2026-10-29 Codexのレビュー）。
      const beforeToggle = curveRequests.length;
      await page.getByRole('button', {name: '🌈 付ける', exact: true}).click();
      await page.getByRole('button', {name: '🌈 外す', exact: true}).waitFor();
      await page.getByRole('button', {name: '🌈 外す', exact: true}).click();
      await page.getByRole('button', {name: '🌈 付ける', exact: true}).waitFor();
      const rainbowPosts = () => posts.filter(p => p.file === 'rainbow').length;
      for (let i = 0; i < 40 && rainbowPosts() < 2; i++) await page.waitForTimeout(100);
      await page.waitForTimeout(800);
      assert.equal(rainbowPosts(), 2, '付け外しを2回とも送る');
      await seen('保存時のグラフの線から描いたグラフです。', '🌈のあとも線で描く');
      assert.equal(curveRequests.length, beforeToggle, '🌈の付け外しでは線を読み直さない');
      assert.deepEqual(errors, []);
    } catch (error) {
      console.error(JSON.stringify({failFirst, errors, curveRequests, labels: (await labels()).slice(0, 2000)}));
      throw error;
    } finally { await context.close(); }
  }
  console.log('PASS: 閲覧ページの線は機種・台の画面で読み、推定差枚は線の前後で同じ・読めないときは再読込（合成応答）');
} finally { await browser.close(); server.close(); }
