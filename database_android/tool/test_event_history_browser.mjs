// 実Googleへ接続せず、共有履歴の取得・同日遷移・機種列固定・キャッシュを確認する。
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {mergeHistoryCells} from '../../share_viewer/event_history.mjs';
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
const url=process.env.SHARE_PUBLIC_URL || `http://127.0.0.1:${server.address().port}/share/`;
const id='AKfycbTEST'+'x'.repeat(40);
const base={version:2,store:'nagamachiminami',symbols:['😀','😍'],user_blank_days:[],weeks:[
  {type:'4台構成',from:'2026-10-05',to:'2026-10-11',machines:[{name:'Lテスト',record_name:null,count:4,results:['😀','','','','','','']}]},
  {type:'バラエティ',from:'2026-09-28',to:'2026-10-04',machines:[{name:'週の機種',record_name:null,count:2,results:['','','','','','','😍']}]},
]};
const history={format:'database-event-history',version:1,base,shared_editing:true,cells:[{store:base.store,type:'4台構成',week:'2026-10-05',machine:'Lテスト',day:'2026-10-05',value:'',updated_at:'2026-10-19T09:00:00.123456+09:00'}],
  links:[{store:base.store,type:'4台構成',week:'2026-10-05',machine:'Lテスト',record_name:'L ﾃｽﾄ',updated_at:'2026-10-19T00:00:00.123457Z'}],
  weeks:[{store:base.store,type:'バラエティ',week:'2026-10-12',lineup_day:'2026-10-13',machines:[{name:'週の機種',record_name:'週の機種',count:2}],updated_at:'2026-10-19T00:00:00Z',removed:false}]};
history.saiwaichou_variety=JSON.parse(await fs.readFile(new URL('../test/fixtures/saiwaichou_history_cases.json',import.meta.url),'utf8')).saiwaichou_variety;
const records=[{store:base.store,day:'2026-10-05',machine:'L ﾃｽﾄ',rack:101,games:1000,bb:4,rb:2},
  {store:base.store,day:'2026-10-06',machine:'L ﾃｽﾄ',rack:999,games:2000,bb:8,rb:4},
  {store:base.store,day:'2026-10-07',machine:'L+ﾃｽﾄ',rack:777,games:2000,bb:8,rb:4},
  {store:base.store,day:'2026-10-19',machine:'同名機種',rack:90,games:1000,bb:4,rb:2},
  {store:'saiwaichou',day:'2026-10-19',machine:'同名機種',rack:610,games:1000,bb:4,rb:2,jo_net:2500}];
const responses={'':{format:'database-backup',version:1,records},pscube:{format:'pscube-viewer',version:1,records:[]},'event-history':history};
const engine=process.env.HISTORY_BROWSER||'chromium';
const browser=await engines[engine].launch(engine==='chromium'?{headless:true,executablePath:process.env.CHROMIUM_PATH||undefined,args:['--no-sandbox']}:{headless:true});
try{
 for(const width of [320,393,1280]){
  // 外部通信の置き換えを確実にする。サービスワーカー自体は既存のオフライン試験が担当する。
  const context=await browser.newContext({viewport:{width,height:860},serviceWorkers:'block'});
  const methods=[], localRequests=[], errors=[];
  let failHistory=false, failPosts=false, sharedHistory=structuredClone(history);
  const posts=[];
  await context.route('https://script.google.com/**',route=>{
    const r=route.request();methods.push(r.method());
    if(r.method()==='POST') {
      const body=r.postDataJSON();posts.push({url:r.url(),body});
      assert.equal(body.file,'event-history');assert.ok(body.cells.every(c=>c.device==='shared'));
      if(failPosts) return route.fulfill({status:503,body:'送信できません'});
      if(body.cells.some(c=>Date.parse(c.updated_at)>Date.now()+5*60*1000))
        return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({error:'端末の日時が先に進んでいます。'})});
      sharedHistory=mergeHistoryCells(sharedHistory,body.cells);
      return route.fulfill({status:200,contentType:'application/json',headers:{'access-control-allow-origin':'*'},body:JSON.stringify({ok:true,history:sharedHistory})});
    }
    const key=new URL(r.url()).searchParams.get('file')??'';
    return route.fulfill({status:200,contentType:'application/json',headers:{'access-control-allow-origin':'*','access-control-allow-methods':'GET, POST, OPTIONS','access-control-allow-headers':'*'},body:JSON.stringify(key==='event-history'?(failHistory?{error:'古いスクリプトです。'}:sharedHistory):responses[key]??{})});
  });
  const page=await context.newPage();
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>localRequests.push(r.url()));
  await page.goto(`${url}#s=${id}`);await page.waitForSelector('[data-event-history-open]');
  await page.locator('[data-event-history-open]').click();await page.waitForSelector('.history-table');
  assert.equal(await page.locator('#sheet-title').innerText(),'長町南のイベント履歴');
  assert.equal(await page.locator('.history-table td .history-symbol').first().inputValue(),'');
  assert.equal(await page.locator('.history-table select').count(),7);
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
  const symbol=page.locator('.history-table select').first();
  await symbol.selectOption('😍');
  await page.waitForFunction(()=>document.querySelector('[data-history-save-status]')?.textContent.includes('共有に保存しました'));
  assert.equal(await symbol.inputValue(),'😍');
  assert.equal(posts.at(-1).body.cells[0].machine,'Lテスト');
  assert.equal(posts.at(-1).body.cells[0].day,'2026-10-05');
  failPosts=true;failHistory=false;
  await symbol.selectOption('😀');
  await page.waitForFunction(()=>document.querySelector('[data-history-save-status]')?.textContent.includes('送信待ち'));
  await page.reload();await page.locator('[data-event-history-open]').click();
  await page.waitForSelector('.history-table select');
  assert.equal(await symbol.inputValue(),'😀','未送信の編集は再読込でも残る');
  try { await page.waitForFunction(()=>document.querySelector('[data-history-save-status]')?.textContent.includes('送信待ち'),{},{timeout:5000}); }
  catch(error) {
    console.log('再読込後の診断',await page.evaluate(()=>({status:document.querySelector('[data-history-save-status]')?.textContent,reloadDisabled:document.querySelector('#reload')?.disabled,local:Object.fromEntries(Object.entries(localStorage).filter(([k])=>k.startsWith('database-share-history-edits:')))})),posts.length);
    throw error;
  }
  failPosts=false;
  await page.locator('[data-history-retry]').click();
  await page.waitForFunction(()=>document.querySelector('[data-history-save-status]')?.textContent.includes('共有に保存しました'));
  await symbol.selectOption('');
  await page.waitForFunction(()=>document.querySelector('[data-history-save-status]')?.textContent.includes('共有に保存しました') && !document.querySelector('[data-history-retry]'));
  await page.evaluate(()=>{for(const k of Object.keys(localStorage)) if(k.startsWith('database-share-history-edits:')) localStorage.removeItem(k);});
  await page.reload();await page.waitForSelector('[data-event-history-open]');
  await page.locator('#reload').click();await page.waitForFunction(()=>!document.querySelector('#reload').disabled);
  await page.locator('[data-event-history-open]').click();
  assert.equal(await symbol.inputValue(),'','端末の編集を除いてもサーバーに空欄が保存されている');
  sharedHistory.shared_editing=false;
  await page.reload();await page.waitForSelector('[data-event-history-open]');
  await page.locator('#reload').click();
  await page.waitForFunction(()=>!document.querySelector('#reload').disabled);
  await page.locator('[data-event-history-open]').click();
  assert.equal(await symbol.isDisabled(),true);
  assert.match(await page.locator('[data-history-save-status]').innerText(),/Apps Scriptを更新/);
  await page.locator('[data-close]').click();
  sharedHistory.shared_editing=true;
  await page.locator('#reload').click();await page.waitForFunction(()=>!document.querySelector('#reload').disabled);
  await page.locator('[data-event-history-open]').click();
  failPosts=true;await symbol.selectOption('😍');
  await page.waitForFunction(()=>document.querySelector('[data-history-save-status]')?.textContent.includes('送信待ち'));
  const oldPosts=posts.length, otherId=id+'y';
  await page.goto(`${url}#s=${otherId}`);await page.locator('[data-event-history-open]').click();
  assert.equal(await symbol.inputValue(),'','接続先を替えたときは別の接続先の編集を混ぜない');
  assert.equal(posts.length,oldPosts,'別の接続先へ未送信の編集を送らない');
  assert.equal(await page.evaluate(id=>JSON.parse(localStorage.getItem('database-share-history-edits:'+id))[0].pending,id),true);
  const reviewFailures=[];
  failPosts=false;
  const scroll=await page.locator('.history-overflow').evaluate(e=>{
    e.scrollLeft=e.scrollWidth;
    const before=e.scrollLeft, select=e.querySelector('tbody td:last-child select');
    select.value='😍';select.dispatchEvent(new Event('change',{bubbles:true}));
    return {before,after:document.querySelector('.history-overflow').scrollLeft};
  });
  if(Math.abs(scroll.before-scroll.after)>2) reviewFailures.push('顔文字変更で横スクロールが先頭へ戻る');
  await page.waitForFunction(()=>document.querySelector('[data-history-save-status]')?.textContent.includes('共有に保存しました'));
  const reviewId=id+'z';
  const valid={store:base.store,type:'4台構成',week:'2026-10-05',machine:'Lテスト',day:'2026-10-06',value:'😀',updated_at:new Date().toISOString(),device:'shared',pending:true};
  const obsolete={...valid,machine:'現在の週表にない機種'};
  const future={...valid,day:'2026-10-07',updated_at:new Date(Date.now()+3600000).toISOString()};
  await page.evaluate(({key,cells})=>localStorage.setItem(key,JSON.stringify(cells)),{key:'database-share-history-edits:'+reviewId,cells:[obsolete,future,valid]});
  const beforeValidPost=posts.length;
  await page.goto(`${url}#s=${reviewId}`);await page.locator('[data-event-history-open]').click();
  try { await page.waitForFunction(n=>{
    const lists=Object.entries(localStorage).filter(([k])=>k.endsWith(n));
    return lists.some(([,v])=>JSON.parse(v).some(c=>c.machine==='Lテスト' && c.pending===false));
  },reviewId,{timeout:5000}); }
  catch { reviewFailures.push('送れない未送信編集があると、有効な編集も送れない'); }
  const journal=await page.evaluate(id=>JSON.parse(localStorage.getItem('database-share-history-edits:'+id)),reviewId);
  assert.equal(journal.find(c=>c.machine===obsolete.machine).pending,true,'対象外の編集も捨てずに端末へ残す');
  assert.equal(journal.find(c=>c.updated_at===future.updated_at).pending,true,'日時が先の編集も捨てずに端末へ残す');
  if(!reviewFailures.length) {
    assert.equal(posts.length,beforeValidPost+1);
    assert.equal(posts.at(-1).body.cells.length,1,'有効な編集だけを送る');
    assert.match(await page.locator('[data-history-save-status]').innerText(),/2件.*端末/);
  }
  assert.deepEqual(reviewFailures,[]);
  // 週ごとに判定し、共有編集で最後の😍を消した直後にも赤字へ戻す。
  await page.evaluate(id=>localStorage.removeItem('database-share-history-edits:'+id),reviewId);
  await page.reload();await page.locator('[data-event-history-open]').click();
  assert.equal(await page.locator('.history-no-heart').count(),0,'4台構成は赤字にしない');
  await page.locator('[data-history-type="バラエティ"]').click();
  const names=page.locator('.history-table tbody th > span');
  assert.equal(await names.nth(0).evaluate(e=>getComputedStyle(e).color),'rgb(185, 28, 28)');
  assert.notEqual(await names.nth(1).evaluate(e=>getComputedStyle(e).color),'rgb(185, 28, 28)','別週の日曜の😍を数える');
  const symbols=page.locator('.history-table').first().locator('select');
  for(const [day,value,red] of [[0,'😍',false],[6,'😍',false],[0,'😀',false],[6,'',true]]) {
    await symbols.nth(day).selectOption(value);
    assert.equal(await names.nth(0).evaluate(e=>e.classList.contains('history-no-heart')),red);
    await page.waitForFunction(()=>document.querySelector('[data-history-save-status]')?.textContent.includes('共有に保存しました'));
    assert.equal(await names.nth(0).evaluate(e=>getComputedStyle(e).color)==='rgb(185, 28, 28)',red);
  }
  await page.locator('[data-close]').click();
  await page.locator('[data-store="saiwaichou"]').click();
  await page.locator('[data-event-history-open]').click();
  assert.equal(await page.locator('#sheet-title').innerText(),'幸町のバラエティ履歴');
  assert.equal(await page.locator('.history-table select').count(),0,'優・良の編集はPCだけ');
  assert.equal(await page.locator('.history-table [data-history-edit]').count(),0);
  assert.equal(await page.locator('.history-no-heart').count(),0,'幸町へ長町南の赤字判定を適用しない');
  assert.equal(await page.locator('.history-symbol').first().innerText(),'優');
  assert.ok((await page.locator('.history-symbol').allInnerTexts()).includes('良'));
  assert.equal(await page.locator('.history-table tbody tr').first().locator('td').nth(1).evaluate(cell=>{
    const grade=cell.querySelector('.history-symbol').getBoundingClientRect();
    const note=cell.querySelector('small').getBoundingClientRect();
    return grade.bottom<=note.top+1;
  }),true,'優・良と記録なしの案内を別の行にする');
  await page.locator('[data-history-day="2026-10-19"]').click();
  assert.match(await page.locator('.sheet').innerText(),/610番/);
  assert.doesNotMatch(await page.locator('.sheet').innerText(),/90番/);
  await page.locator('[data-history-rack="0"]').click();
  assert.equal(await page.locator('#sheet-title').innerText(),'610番台');
  assert.deepEqual(errors,[]);
  assert.ok(localRequests.every(r=>!r.includes('event_history.json')),'履歴JSONを公開アセットから取得しない');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await context.close();
 }
 console.log('PASS: 共有履歴・同日遷移・固定列・顔文字と空欄の共有保存・未送信保持と再送・旧GS、320/393/1280px');
}finally{await browser.close();server.close();}
