// 実際のFlutter閲覧ページへ合成記録を読み込み、半px補正後の日別合計と正確値の優先を確かめる。
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = process.env.VIEWER_WEB_ROOT || fileURLToPath(new URL('../build/web/', import.meta.url));
const prefix = '/database-viewer/';
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost').pathname;
  if (url === '/setup') { res.end('<!doctype html><body>setup</body>'); return; }
  if (!url.startsWith(prefix)) { res.writeHead(404).end(); return; }
  const name = url.slice(prefix.length) || 'index.html';
  const local = path.resolve(root, name);
  if (!local.startsWith(path.resolve(root)+path.sep)) { res.writeHead(403).end(); return; }
  try {
    const content = await fs.readFile(local);
    res.setHeader('content-type', ({'.js':'text/javascript','.mjs':'text/javascript',
      '.json':'application/json','.html':'text/html','.wasm':'application/wasm'})[path.extname(local)] || 'application/octet-stream');
    res.end(content);
  } catch { res.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const origin = process.env.VIEWER_PUBLIC_ORIGIN || `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({headless:true, executablePath:process.env.CHROMIUM_PATH || undefined,
  args:['--no-sandbox']});
function graph(end) {
  return {baseline_y:200.5,peak_y:140.5,trough_y:Math.max(200.5,200.5-end),end_y:200.5-end,
    curve:[[.5,200.5],[10.5,140.5],[20.5,200.5-end]]};
}
const base = {store:'nagamachiminami',day:'2026-10-10',machine:'合成テスト',games:3000,bb:10,rb:5,max_hold:400};
const input = {header:{format:'database-backup',version:1,source:'pc',exported_at:'2026-10-20T00:00:00+09:00'},
  records:[{...base,rack:1,graph_measurement:graph(30)}, // +164
    {...base,rack:2,graph_measurement:graph(-30)}, // -169
    {...base,rack:3,graph_measurement:graph(-30),jo_net:321}, // 正確値は補正しない
    {...base,rack:4,max_hold:null,graph_measurement:graph(30)}]};
try {
  for (const width of [320,393]) {
    const context = await browser.newContext({viewport:{width,height:852}});
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.clock.setFixedTime(new Date('2026-10-20T03:00:00Z'));
    await page.goto(process.env.VIEWER_PUBLIC_ORIGIN ? origin+prefix+'README.md' : origin+'/setup');
    await page.evaluate(async data => {
      const db = await new Promise((resolve,reject) => {
        const q = indexedDB.open('database-viewer',1);
        q.onupgradeneeded = () => q.result.createObjectStore('kv');
        q.onsuccess = () => resolve(q.result); q.onerror = () => reject(q.error);
      });
      await new Promise((resolve,reject) => {
        const tx = db.transaction('kv','readwrite'), kv = tx.objectStore('kv');
        kv.put(JSON.stringify(data),'data'); kv.put('meruhen','active_source');
        tx.oncomplete = resolve; tx.onerror = () => reject(tx.error);
      });
      db.close();
    }, input);
    await page.goto(origin+prefix);
    await page.waitForSelector('flt-glass-pane',{state:'attached',timeout:60000});
    const placeholder = page.locator('flt-semantics-placeholder');
    if (await placeholder.count()) await placeholder.evaluate(e => e.click());
    // 保存の診断（2026-10-31、web/storage_report.mjs）：件数・大きさ・読み込みが終わった回数を出し、保存先を作らない。
    await page.getByRole('button',{name:'更新・差枚の取得状況',exact:true}).click({timeout:60000});
    await page.getByText(/この端末の保存（診断）/).waitFor();
    const health = (await page.locator('flt-semantics').allTextContents()).join('\n');
    assert.match(health, /表示中の記録：4件・1日分/);
    assert.match(health, /本体（前に読み込んだ内容）：約[\d.]+MB（[\d,]+文字/);
    assert.match(health, /本体の保存先：メルヘンの本体あり・本体と別の🌈の印なし/);
    assert.match(health, /新しい日別保存：まだ使っていません/);
    assert.match(health, /起動時の読み込み：最後まで終わった1回.*途中で終わった0回/);
    assert.equal(await page.evaluate(async () => (await indexedDB.databases()).some(d => d.name === 'database-viewer-days-v1')), false);
    await page.getByRole('button',{name:'閉じる',exact:true}).click();
    await page.getByRole('button',{name:'日別の差枚（推定）',exact:true}).click({timeout:60000});
    await page.getByText('メルヘンワールド長町南店　2026年10月のデータ',{exact:true}).waitFor();
    await page.getByText('+316',{exact:true}).first().waitFor();
    assert.equal(await page.getByText('+316',{exact:true}).count(),2,'当日の合計と期間累計');
    assert.equal(await page.getByText('+105',{exact:true}).count(),2,'計算できた3台の平均');
    assert.equal(await page.getByText('3/4',{exact:true}).count(),1,'最大持玉なしは0で埋めない');
    assert.deepEqual(errors,[]);
    await context.close();
  }
  console.log('成功: 閲覧ページの日別合計+316・平均+105・正確値の優先・欠損、320/393px');
} finally {
  await browser.close();
  await new Promise(resolve => server.close(resolve));
}
