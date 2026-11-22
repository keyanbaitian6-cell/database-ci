// Googleが日別の部品を作り直す前（?check=1 の返事が目印だけで部品が無い）に、部品で更新してきた端末（日別キャッシュが
// ある）は、ファイル全体を読まずに今回の更新を見送る（2026-11-22、Geminiの点検 M-5②）。閲覧ページのメルヘン版
// （web/index.html、2026-11-19）と同じことを、共有カレンダーが使う fetchViewerDocument と、P’s CUBE版の fetchDrive でも確かめる。
// 日別キャッシュの無い端末は、今までどおりファイル全体を読む。実ブラウザの IndexedDB、Googleは偽物（page.route）。
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const web = fileURLToPath(new URL('../web/', import.meta.url));
const server = http.createServer(async (req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname;
  if (pathname === '/setup') { res.setHeader('content-type', 'text/html'); res.end('<!doctype html><body>hold</body>'); return; }
  const local = path.resolve(web, '.' + pathname);
  if (!local.startsWith(web)) { res.writeHead(403).end(); return; }
  try { res.setHeader('content-type', 'text/javascript'); res.end(await fs.readFile(local)); }
  catch { res.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const origin = 'http://127.0.0.1:' + server.address().port;
const SCRIPT = 'https://script.google.com/macros/s/AKfycb_HOLD/exec';
const PENDING = /日別の部品を作り直しているところです/;
const full = {meruhen: {format: 'database-backup', version: 1, source: 'pc-viewer', exported_at: '2026-11-22T20:00:00+09:00', records: []},
  pscube: {format: 'pscube-viewer', version: 1, kind: 'viewer', source: 'pc', exported_at: '2026-11-22T20:00:00+09:00', machines: [], records: []}};
const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
try {
  // cached：'parts'＝部品で更新してきた端末（見出しに parts_at）、'copied'＝全文から移しただけ（P’s CUBE版は読む前に
  // いつも移す）、null＝日別キャッシュなし。見送るのは 'parts' だけ。
  for (const cached of ['parts', 'copied', null]) {
    const context = await browser.newContext();
    const page = await context.newPage();
    const errors = [], requests = [];
    page.on('pageerror', e => errors.push(e.message));
    await context.route('https://script.google.com/**', route => {
      const url = new URL(route.request().url()), file = url.searchParams.get('file');
      requests.push(url.search);
      const body = url.searchParams.get('check') ? {format: 'drive-check', version: 'v-new', name: 'x.json'} : full[file === 'pscube' ? 'pscube' : 'meruhen'];
      return route.fulfill({status: 200, contentType: 'application/json', headers: {'access-control-allow-origin': '*'}, body: JSON.stringify(body)});
    });
    await page.goto(origin + '/setup');
    // 部品で更新してきた端末：日別キャッシュの見出しがある（メルヘン・P’s CUBE の両方）。
    if (cached) await page.evaluate(async ({script, cached}) => {
      const db = await new Promise((res, rej) => { const q = indexedDB.open('database-viewer-parts-v1', 2);
        q.onupgradeneeded = () => { for (const n of ['snapshots', 'history-heads', 'history-days']) q.result.createObjectStore(n); };
        q.onsuccess = () => res(q.result); q.onerror = () => rej(q.error); });
      await new Promise((res, rej) => { const tx = db.transaction('history-heads', 'readwrite');
        const header = cached === 'parts' ? {format: 'x', parts_at: '2026-11-22T19:00:00+09:00'} : {format: 'x'};
        for (const site of ['meruhen', 'pscube']) tx.objectStore('history-heads').put({header, days: [], revision: 1}, script + '|' + site);
        tx.oncomplete = res; tx.onerror = () => rej(tx.error); });
      db.close();
    }, {script: SCRIPT, cached});
    // 共有カレンダーが使う fetchViewerDocument（メルヘン）。
    const shared = await page.evaluate(async script => {
      const {fetchViewerDocument} = await import('/viewer_parts.mjs');
      const getJson = async url => (await fetch(url)).json();
      try { const doc = await fetchViewerDocument(script, 'meruhen', getJson); return {ok: true, format: doc.format}; }
      catch (error) { return {ok: false, message: error.message}; }
    }, SCRIPT);
    // P’s CUBE版の fetchDrive。
    const pscube = await page.evaluate(async script => {
      const {fetchDrive} = await import('/pscube/sync.mjs');
      try { const r = await fetchDrive(script, null, {retryDelays: [], hedgeMs: 60000}); return {ok: true, records: r.data?.records?.length ?? null}; }
      catch (error) { return {ok: false, message: error.message}; }
    }, SCRIPT);
    if (cached === 'parts') {
      assert.equal(shared.ok, false); assert.match(shared.message, PENDING, '共有カレンダー：見送りの理由をそのまま出す');
      assert.equal(pscube.ok, false); assert.match(pscube.message, PENDING, 'P’s CUBE版：見送りの理由をそのまま出す');
      assert.ok(requests.every(q => q.includes('check=1')), `ファイル全体を読まない：${requests.join(' ')}`);
    } else {
      assert.deepEqual(shared, {ok: true, format: 'database-backup'}, `部品を使っていなければ今までどおり全体を読む（${cached}）`);
      assert.equal(pscube.ok, true, JSON.stringify(pscube));
      assert.ok(requests.some(q => !q.includes('check=1')), '全体を読む');
    }
    assert.deepEqual(errors, []);
    await context.close();
  }
  console.log('PASS: share calendar and P’s CUBE viewer skip the full file while Google rebuilds the day parts, only when they have a day cache');
} finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
