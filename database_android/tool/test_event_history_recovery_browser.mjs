// 一時ブラウザと模擬Googleで、時計の修正・保存領域の失敗・古い週表からの復帰を確認する。
import assert from 'node:assert/strict';
import {before,after,test} from 'node:test';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
import {mergeHistoryCells} from '../../share_viewer/event_history.mjs';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=fileURLToPath(new URL('../../share_viewer/',import.meta.url));
const id='AKfycbRECOVERY'+'x'.repeat(40), key='database-share-history-edits:'+id;
const cell=(extra={})=>({store:'nagamachiminami',type:'4台構成',week:'2026-10-19',machine:'試験機種',day:'2026-10-19',
  value:'😀',updated_at:new Date().toISOString(),device:'shared',...extra});
const document=()=>({format:'database-event-history',version:1,shared_editing:true,cells:[],weeks:[],links:[],base:{
  version:2,store:'nagamachiminami',symbols:['😀','😍'],weeks:[{type:'4台構成',from:'2026-10-19',to:'2026-10-25',
    machines:[{name:'試験機種',count:4,results:Array(7).fill('')}]}]}});
let browser,server,url;
before(async()=>{
  server=http.createServer(async(req,res)=>{
    const local=path.resolve(root,new URL(req.url,'http://fixture').pathname.replace(/^\//,'')||'index.html');
    if(!local.startsWith(root)){res.writeHead(403).end();return;}
    try{res.setHeader('content-type',local.endsWith('.mjs')?'text/javascript':'text/html; charset=utf-8');res.end(await fs.readFile(local));}
    catch{res.writeHead(404).end();}
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  url=`http://127.0.0.1:${server.address().port}/`;
  browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||undefined});
});
after(async()=>{await browser?.close();await new Promise(r=>server.close(r));});

async function open(t,width,{pending=[],serverCells=[],rejectPost=false,blockAcknowledgement=false,blockInitial=false,holdFirstPost=false}={}) {
  const context=await browser.newContext({viewport:{width,height:860},serviceWorkers:'block'});
  t.after(()=>context.close());
  const page=await context.newPage(), errors=[],posts=[];
  let history={...document(),cells:serverCells}, acknowledgementBlocked=false, releaseFirstPost;
  const firstPost=new Promise(resolve=>{releaseFirstPost=resolve;});
  t.after(()=>releaseFirstPost());
  page.on('pageerror',error=>errors.push(error.message));
  t.after(()=>assert.deepEqual(errors,[]));
  await page.addInitScript(({key,pending,blockInitial})=>{
    if(pending.length && localStorage.getItem(key)==null) localStorage.setItem(key,JSON.stringify(pending));
    const set=Storage.prototype.setItem;
    Storage.prototype.setItem=function(k,v){
      if(k===key && window.__blockHistoryStorage) throw new DOMException('試験用の保存失敗','QuotaExceededError');
      return set.call(this,k,v);
    };
    window.__blockHistoryStorage=blockInitial;
  },{key,pending,blockInitial});
  await context.route('https://script.google.com/**',async route=>{
    const request=route.request();
    let body;
    if(request.method()==='POST') {
      const incoming=request.postDataJSON().cells;posts.push(incoming);
      if(holdFirstPost && posts.length===1) await firstPost;
      if(rejectPost) body={error:'対象の週・機種・日付が履歴にありません。'};
      else {
        assert.ok(incoming.every(c=>Date.parse(c.updated_at)<=Date.now()+300000));
        history=mergeHistoryCells(history,incoming);
        if(blockAcknowledgement && !acknowledgementBlocked) {
          acknowledgementBlocked=true;
          await page.evaluate(()=>window.__blockHistoryStorage=true);
        }
        body={ok:true,history};
      }
    } else {
      const file=new URL(request.url()).searchParams.get('file');
      body=file==='event-history'?history:file==='pscube'?{format:'pscube-viewer',version:1,records:[]}:
        {format:'database-backup',version:1,records:[{store:'nagamachiminami',day:'2026-10-19',machine:'試験機種',rack:101,games:1000,bb:4,rb:2}]};
    }
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
  });
  await page.goto(`${url}#s=${id}`);
  await page.locator('[data-event-history-open]').click();
  await page.waitForSelector('.history-table select');
  return {page,posts,releaseFirstPost,history:()=>history,symbol:page.locator('.history-table select').first(),
    journal:()=>page.evaluate(key=>JSON.parse(localStorage.getItem(key)),key)};
}

for(const width of [320,393,1280]) {
  test(`${width}px：未来時刻の未送信を同じセルで選び直すと共有へ保存できる`,async t=>{
    const future=cell({updated_at:new Date(Date.now()+86400000).toISOString(),pending:true});
    const a=await open(t,width,{pending:[future]});
    await a.page.waitForFunction(()=>document.querySelector('[data-history-save-status]')?.textContent.includes('送信できない編集'));
    await a.symbol.selectOption('😍');
    await a.page.waitForFunction(()=>document.querySelector('[data-history-save-status]')?.textContent.includes('共有に保存しました'),null,{timeout:2500});
    assert.equal(a.posts.length,1);
    assert.equal(a.posts[0][0].value,'😍');
    assert.equal(a.history().cells[0].value,'😍');
    assert.equal((await a.journal()).length,1);
    assert.equal((await a.journal())[0].pending,false);
    assert.equal(await a.symbol.inputValue(),'😍');
  });
  test(`${width}px：共有保存後の端末保存失敗は共有の成功と再送の可能性を知らせる`,async t=>{
    const a=await open(t,width,{blockAcknowledgement:true});
    await a.symbol.selectOption('😍');
    await a.page.waitForFunction(()=>document.querySelector('[data-history-save-status]')?.textContent.includes('端末の送信済み状態を更新できませんでした'),null,{timeout:2500});
    assert.match(await a.page.locator('[data-history-save-status]').innerText(),/共有に保存しました/);
    assert.equal(a.posts.length,1,'送信済み状態を保存できないときに無限再送しない');
    assert.equal(a.history().cells[0].value,'😍');
    assert.equal((await a.journal())[0].pending,true,'保存済みの原文を消さない');
    await a.page.evaluate(()=>window.__blockHistoryStorage=false);
    await a.page.locator('[data-history-retry]').click();
    await a.page.waitForFunction(()=>!document.querySelector('[data-history-retry]'));
    assert.equal(a.posts.length,2);
    assert.equal(a.history().cells.length,1);
    assert.equal((await a.journal())[0].pending,false);
  });
  test(`${width}px：送信前の端末保存が失敗したら保存失敗を知らせて送信しない`,async t=>{
    const a=await open(t,width,{blockInitial:true});
    await a.symbol.selectOption('😍');
    await a.page.waitForFunction(()=>document.body.innerText.includes('記号を保存できません'));
    assert.equal(a.posts.length,0);
    assert.equal(a.history().cells.length,0);
    assert.equal(await a.symbol.inputValue(),'');
  });
  test(`${width}px：週表が食い違ったPOSTの拒否時に最新の読み直しを案内する`,async t=>{
    const a=await open(t,width,{rejectPost:true});
    await a.symbol.selectOption('😍');
    await a.page.waitForFunction(()=>document.querySelector('[data-history-save-status]')?.textContent.includes('送信待ち'));
    assert.match(await a.page.locator('[data-history-save-status]').innerText(),/最新を読む/);
    assert.equal((await a.journal())[0].pending,true);
    assert.equal(a.history().cells.length,0);
  });
  test(`${width}px：共有済みの未来時刻は黙って送信待ちにせず理由を表示する`,async t=>{
    const future=cell({updated_at:new Date(Date.now()+86400000).toISOString()});
    const a=await open(t,width,{serverCells:[future]});
    await a.symbol.selectOption('😍');
    await a.page.waitForFunction(()=>document.body.innerText.includes('共有済みの編集時刻が未来'));
    assert.equal(a.posts.length,0);
    assert.equal(await a.journal(),null,'送れない編集を新たに端末へ保存しない');
    assert.equal(await a.symbol.inputValue(),'😀');
    assert.equal(a.history().cells[0].updated_at,future.updated_at);
  });
}

test('送信中に同じセルを選び直しても、先の応答で新しい未送信を消さない',async t=>{
  const a=await open(t,393,{holdFirstPost:true});
  await a.page.evaluate(now=>Date.now=()=>now,Date.now());
  const request=a.page.waitForRequest(r=>r.method()==='POST');
  await a.symbol.selectOption('😀');
  await request;
  await a.symbol.selectOption('😍');
  a.releaseFirstPost();
  await a.page.waitForFunction(()=>document.querySelector('[data-history-save-status]')?.textContent.includes('共有に保存しました') && !document.querySelector('[data-history-retry]'));
  assert.equal(a.posts.length,2);
  assert.ok(Date.parse(a.posts[1][0].updated_at)>Date.parse(a.posts[0][0].updated_at));
  assert.equal(a.history().cells[0].value,'😍');
  assert.equal((await a.journal())[0].value,'😍');
  assert.equal((await a.journal())[0].pending,false);
});

test('PCの表だけ取り込みの札は完了ではなく保存台数を表示する',async()=>{
  // WindowsのPythonは標準出力がcp932のことがあり、絵文字（🌈）をそのまま出せない。既存試験と同じくJSONで受け取る。
  const script=JSON.parse(execFileSync(process.env.PYTHON||'python',['-c','import json,browser_import; print(json.dumps(browser_import.OVERLAY_JS))'],
    {cwd:new URL('../../database/',import.meta.url),encoding:'utf8'}));
  const page=await browser.newPage();
  try {
    await page.route('**/*',route=>route.fulfill({status:200,contentType:'text/html',body:
      '<a href="/nagamachiminami/standlist_slot/?machine_name=fixture">試験機種</a>'}));
    await page.goto('https://meruhenworld.pt.teramoba2.com/nagamachiminami/rack_info_kt?kind_code=21');
    await page.evaluate(()=>window.pywebview={api:{progress:async()=>JSON.stringify({text:''}),
      machine_status:async()=>JSON.stringify({day:'2026-10-19',status:[{done:3,total:3,tables_only:true}]}),
      get_auto_capture:async()=>({enabled:false,seconds:3.5,revision:1,message:'停止中',tables_only:true}),save_overlay_layout:async()=>true}});
    await page.evaluate(script);
    await page.waitForSelector('.database-badge');
    assert.equal(await page.locator('.database-badge').innerText(),'10/19 表 3台保存');
  } finally { await page.close(); }
});
