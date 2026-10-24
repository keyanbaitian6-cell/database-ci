// 新しくビルド・stageした閲覧ページの実物で、両サイトの競合と保存失敗を確認する。
import assert from 'node:assert/strict';
import test from 'node:test';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(process.env.VIEWER_WEB_ROOT || fileURLToPath(new URL('../build/web/', import.meta.url)));
const prefix = '/database-viewer/';
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://x').pathname;
  if (url === '/setup') { res.setHeader('content-type', 'text/html'); res.end('<!doctype html><body>setup'); return; }
  const file = path.resolve(root, url.slice(prefix.length) || 'index.html');
  if (!url.startsWith(prefix) || !file.startsWith(root + path.sep)) { res.writeHead(403).end(); return; }
  try {
    const body = await fs.readFile(file);
    res.setHeader('content-type', ({'.html':'text/html','.js':'text/javascript','.mjs':'text/javascript','.wasm':'application/wasm','.json':'application/json','.woff2':'font/woff2'})[path.extname(file)] || 'application/octet-stream');
    res.end(body);
  } catch { res.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
const base = 'https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c1/cgi-bin/';
const machine = {store:'c1',rate:'20',machine:'試験機種',expected_count:1,url:base+'nc-v05-011.php?cd_ps=2&bai=20'};
function document(site, games, at) {
  const row = {day:'2026-10-22',machine:'試験機種',rack:537,games,bb:10,rb:5};
  if (site === 'meruhen') return {format:'database-backup',version:1,source:'pc',exported_at:at,
    records:[{...row,store:'saiwaichou',kind_code:21}]};
  return {format:'pscube-viewer',version:1,exported_at:at,machines:[machine],
    records:[{...row,store:'c1',rate:'20',my:100,at_art:0,detail_url:base+'nc-v06-001.php?cd_dai=537#20261022'}]};
}
try {
  for (const site of ['meruhen', 'pscube']) await test(`${site}：自動読込中の競合を止め、失敗時の保存データを保持する`, async () => {
    const context = await browser.newContext({viewport:{width:393,height:852},timezoneId:'Asia/Tokyo'});
    const page = await context.newPage(), errors = [];
    page.on('pageerror', error => errors.push(error.message));
    try {
      await page.goto(origin + '/setup');
      const old = document(site, 3000, '2026-10-22T12:00:00Z');
      await page.evaluate(async ({site, old}) => {
        const dbName = site === 'meruhen' ? 'database-viewer' : 'database-pscube-viewer';
        const store = site === 'meruhen' ? 'kv' : 'state';
        const db = await new Promise((resolve,reject) => {
          const request=indexedDB.open(dbName,1);
          request.onupgradeneeded=()=>request.result.createObjectStore(store);
          request.onsuccess=()=>resolve(request.result); request.onerror=()=>reject(request.error);
        });
        await new Promise((resolve,reject) => {
          const tx=db.transaction(store,'readwrite'), out=tx.objectStore(store);
          const {records,...header}=old;
          out.put(site==='meruhen'?JSON.stringify({header,records}):old,'data');
          if(site==='pscube') out.put({exported_at:old.exported_at},'meta');
          tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);
        });
        db.close();
      }, {site, old});
      await page.addInitScript(site => {
        let bridge;
        Object.defineProperty(window,'databaseViewer',{configurable:true,get:()=>bridge,set(value) {
          bridge=value; window.__loads=0;
          const load=value.load.bind(value);
          const pick=value.pick.bind(value);
          window.__originalLoad=load;
          value.load=async()=>{window.__loads++;return load();};
          value.pick=()=>{window.__picks=(window.__picks||0)+1;window.__loadsBeforePick=window.__loads;return pick();};
          value.getRemote=()=> 'https://script.google.com/macros/s/fixture/exec';
          value.fromRemote=async()=> {window.__remoteStarted=true;return new Promise(resolve=>{window.__releaseRemote=()=>resolve(null);});};
          value.fetchShared=async()=>{throw new Error('合成の共有応答');};
        }});
        const put=IDBObjectStore.prototype.put;
        IDBObjectStore.prototype.put=function(value,key) {
          const request=put.apply(this,arguments);
          if(window.__abortSave && key==='data' && this.name===(site==='meruhen'?'kv':'state')) {
            const tx=this.transaction;queueMicrotask(()=>tx.abort());
          }
          return request;
        };
      }, site);
      await page.goto(origin + prefix + (site==='pscube'?'pscube/':'') + 'index.html');
      await page.waitForSelector('flt-glass-pane',{state:'attached',timeout:60000});
      const placeholder=page.locator('flt-semantics-placeholder');
      if(await placeholder.count()) await placeholder.evaluate(e=>e.click());
      await page.waitForFunction(()=>window.__remoteStarted);
      const pick=page.getByRole('button',{name:'バックアップを読み込む',exact:true}).first();
      await pick.waitFor();
      assert.equal(await pick.isEnabled(),false,'自動読込中に別のファイルを選ばせない');
      await page.evaluate(()=>window.__releaseRemote());
      if(site==='meruhen') await page.evaluate(async()=>{
        // 別タブで入力した状況を作る。Flutterの表示中モデルは読み直さない。
        const doc=JSON.parse(await window.__originalLoad());
        doc.date_events=[{store:'saiwaichou',day:'2026-10-22',name:'別タブの入力',updated_at:'2026-10-23T14:00:00Z'}];
        await window.databaseViewer.save(JSON.stringify(doc));
      });
      const readFile=async text => {
        const deadline=Date.now()+10000;
        while(!await pick.isEnabled()) {
          assert.ok(Date.now()<deadline,'読み込み後にファイルボタンが有効に戻る');
          await page.waitForTimeout(20);
        }
        const chooser=page.waitForEvent('filechooser',{timeout:10000});
        // Flutterの読み上げボタンを押す。ファイル選択後のポインタ・ツールチップの状態に依存させない。
        await pick.evaluate(element=>element.click());
        await (await chooser).setFiles({name:'fixture.json',mimeType:'application/json',buffer:Buffer.from(text)});
      };
      const fresh=document(site,4321,'2026-10-23T12:00:00Z');
      await readFile(JSON.stringify(fresh));
      await page.getByText(/10\/23.*書き出し/).first().waitFor();
      assert.equal(await page.evaluate(()=>window.__loads===window.__loadsBeforePick),true,'手動読込で旧JSON全文を再取得しない');
      const saved=await page.evaluate(()=>window.__originalLoad());
      assert.equal(JSON.parse(saved).records[0].games,4321);
      if(site==='meruhen') assert.equal(JSON.parse(saved).date_events[0].name,'別タブの入力');
      await readFile('{"records":[');
      await page.getByText(/バックアップを読み込めませんでした/).first().waitFor();
      assert.equal(await page.evaluate(()=>window.__originalLoad()),saved,'解析失敗では保存内容を変えない');
      await page.evaluate(()=>{window.__abortSave=true;});
      await readFile(JSON.stringify(document(site,7654,'2026-10-24T12:00:00Z')));
      await page.getByText(/バックアップを読み込めませんでした/).first().waitFor();
      assert.equal(await page.evaluate(()=>window.__originalLoad()),saved,'保存中断でも以前の記録・メタデータを保持する');
      assert.deepEqual(errors,[]);
    } catch (error) {
      console.log(site,await page.evaluate(()=>({picks:window.__picks,loads:window.__loads,
        buttons:[...document.querySelectorAll('[role="button"]')].map(e=>({label:e.getAttribute('aria-label')||e.textContent,disabled:e.getAttribute('aria-disabled')}))})));
      await page.screenshot({path:`/tmp/viewer-import-${site}-failure.png`});
      throw error;
    } finally { await context.close(); }
  });
} finally { await browser.close(); await new Promise(resolve=>server.close(resolve)); }
