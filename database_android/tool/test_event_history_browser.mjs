// 実Googleへ接続せず、共有履歴の取得・同日遷移・機種列固定・キャッシュを確認する。
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const engines=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root=fileURLToPath(new URL('../../share_viewer/',import.meta.url));
const server=http.createServer(async(req,res)=>{
  const name=new URL(req.url,'http://x').pathname.replace(/^\/share\//,'')||'index.html';
  const local=path.resolve(root,name);
  if(!local.startsWith(root)){res.writeHead(403).end();return;}
  try{res.setHeader('content-type',local.endsWith('.mjs')||local.endsWith('.js')?'text/javascript':'text/html; charset=utf-8');res.end(await fs.readFile(local));}
  catch{res.writeHead(404).end();}
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const url=`http://127.0.0.1:${server.address().port}/share/`;
const id='AKfycbTEST'+'x'.repeat(40);
const base={version:2,store:'nagamachiminami',symbols:['😀','😍'],user_blank_days:[],weeks:[
  {type:'4台構成',from:'2026-10-05',to:'2026-10-11',machines:[{name:'Lテスト',record_name:null,count:4,results:['😀','','','','','','']}]},
]};
const history={format:'database-event-history',version:1,base,cells:[{store:base.store,type:'4台構成',week:'2026-10-05',machine:'Lテスト',day:'2026-10-05',value:'',updated_at:'2026-10-19T09:00:00.123456+09:00'}],
  links:[{store:base.store,type:'4台構成',week:'2026-10-05',machine:'Lテスト',record_name:'L ﾃｽﾄ',updated_at:'2026-10-19T00:00:00.123457Z'}],
  weeks:[{store:base.store,type:'バラエティ',week:'2026-10-12',lineup_day:'2026-10-13',machines:[{name:'週の機種',record_name:'週の機種',count:2}],updated_at:'2026-10-19T00:00:00Z',removed:false}]};
const records=[{store:base.store,day:'2026-10-05',machine:'L ﾃｽﾄ',rack:101,games:1000,bb:4,rb:2},
  {store:base.store,day:'2026-10-06',machine:'L ﾃｽﾄ',rack:999,games:2000,bb:8,rb:4},
  {store:base.store,day:'2026-10-07',machine:'L+ﾃｽﾄ',rack:777,games:2000,bb:8,rb:4}];
const responses={'':{format:'database-backup',version:1,records},pscube:{format:'pscube-viewer',version:1,records:[]},'event-history':history};
const engine=process.env.HISTORY_BROWSER||'chromium';
const browser=await engines[engine].launch(engine==='chromium'?{headless:true,executablePath:process.env.CHROMIUM_PATH||undefined,args:['--no-sandbox']}:{headless:true});
try{
 for(const width of [320,393,1280]){
  // 外部通信の置き換えを確実にする。サービスワーカー自体は既存のオフライン試験が担当する。
  const context=await browser.newContext({viewport:{width,height:860},serviceWorkers:'block'});
  const methods=[], localRequests=[], errors=[];
  let failHistory=false;
  await context.route('https://script.google.com/**',route=>{
    const r=route.request();methods.push(r.method());
    const key=new URL(r.url()).searchParams.get('file')??'';
    return route.fulfill({status:200,contentType:'application/json',headers:{'access-control-allow-origin':'*','access-control-allow-methods':'GET, OPTIONS','access-control-allow-headers':'*'},body:JSON.stringify(key==='event-history' && failHistory?{error:'古いスクリプトです。'}:responses[key]??{})});
  });
  const page=await context.newPage();
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>localRequests.push(r.url()));
  await page.goto(`${url}#s=${id}`);await page.waitForSelector('[data-event-history-open]');
  await page.locator('[data-event-history-open]').click();await page.waitForSelector('.history-table');
  assert.equal(await page.locator('#sheet-title').innerText(),'長町南のイベント履歴');
  assert.equal(await page.locator('.history-table td .history-symbol').first().innerText(),'');
  assert.equal(await page.locator('.history-table select').count(),0);
  const fixed=page.locator('.history-table tbody th').first();const left=(await fixed.boundingBox()).x;
  await page.locator('.history-overflow').evaluate(e=>e.scrollLeft=500);
  assert.ok(Math.abs((await fixed.boundingBox()).x-left)<2,'機種名の列を横スクロールで動かさない');
  await page.locator('.history-overflow').evaluate(e=>e.scrollLeft=0);
  await page.locator('[data-history-day="2026-10-05"]').click();
  assert.equal(await page.locator('[data-sheet-day]').inputValue(),'2026-10-05');
  assert.deepEqual(await page.locator('[data-sheet-day] option').evaluateAll(nodes=>nodes.map(n=>n.value)),['2026-10-06','2026-10-05']);
  assert.match(await page.locator('.sheet').innerText(),/101番/);assert.doesNotMatch(await page.locator('.sheet').innerText(),/999番/);
  await page.locator('[data-history-rack="0"]').click();assert.equal(await page.locator('#sheet-title').innerText(),'101番台');
  await page.locator('[data-back]').click();await page.locator('[data-back]').click();
  await page.locator('[data-history-type="バラエティ"]').click();assert.match(await page.locator('.sheet').innerText(),/分類日：2026-10-13/);
  await page.locator('[data-close]').click();
  failHistory=true;
  const failedResponse=page.waitForResponse(r=>r.url().includes('file=event-history') && r.request().method()==='GET');
  const request=page.waitForRequest(r=>r.url().includes('file=event-history'));
  await page.locator('#reload').click();await request;assert.match(await (await failedResponse).text(),/古いスクリプト/);await page.waitForFunction(()=>!document.querySelector('#reload').disabled);
  await page.locator('[data-event-history-open]').click();await page.waitForSelector('.history-table');
  await page.waitForFunction(()=>document.querySelector('.sheet')?.innerText.includes('保存済み'));
  assert.match(await page.locator('.sheet').innerText(),/保存済み/);
  assert.deepEqual(errors,[]);assert.ok(methods.every(m=>m==='GET'||m==='OPTIONS'));
  assert.ok(localRequests.every(r=>!r.includes('event_history.json')),'履歴JSONを公開アセットから取得しない');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await context.close();
 }
 console.log('PASS: 共有履歴・空欄から同日遷移・台データ・分類日・固定列・GETのみ・キャッシュ、320/393/1280px');
}finally{await browser.close();server.close();}
