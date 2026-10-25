// 新しい閲覧ビルドと共有ページで、4機種・台別7日間・顔文字の保存を合成応答で確認する。
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import http from 'node:http';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
import {mergeHistoryCells} from '../../share_viewer/event_history.mjs';
import {RECOMMENDATION_DEFAULT,mergeRecommendationResults} from '../../share_viewer/recommendations.mjs';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const roots={share:path.resolve(process.env.SHARE_WEB_ROOT||fileURLToPath(new URL('../../share_viewer/',import.meta.url))),viewer:path.resolve(process.env.VIEWER_WEB_ROOT||fileURLToPath(new URL('../build/web/',import.meta.url)))};
const server=http.createServer(async(req,res)=>{
  const pathname=new URL(req.url,'http://local').pathname;
  if(pathname==='/setup'){res.end('<html></html>');return;}
  const kind=pathname.startsWith('/database-viewer/')?'viewer':'share';
  const relative=pathname.replace(/^\/(?:database-viewer|share)\//,'')||'index.html';
  const file=path.resolve(roots[kind],relative);
  if(!file.startsWith(roots[kind]+path.sep)){res.writeHead(403).end();return;}
  try {const bytes=await fs.readFile(file);res.setHeader('Content-Type',/\.m?js$/.test(file)?'text/javascript':file.endsWith('.json')?'application/json':file.endsWith('.wasm')?'application/wasm':file.endsWith('.html')?'text/html; charset=utf-8':'application/octet-stream');res.end(bytes);}catch{res.writeHead(404).end();}
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const origin=`http://127.0.0.1:${server.address().port}`;
const id='AKfycbRECOMMEND'+'x'.repeat(35),script=`https://script.google.com/macros/s/${id}/exec`;
const names=RECOMMENDATION_DEFAULT.machines;
const records=['2026-10-26','2026-10-28'].flatMap(day=>[...names,'候補7台','候補6台'].flatMap((machine,m)=>Array.from({length:machine==='候補6台'?6:7},(_,r)=>({store:'nagamachiminami',day,machine,rack:100+m*100+r,games:1000,bb:4,rb:2,...(r===2?{}:{jo_net:r===0?0:r===1?-100:3000})}))));
const backup={format:'database-backup',version:1,records,date_events:[]};
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||undefined,args:['--no-sandbox']});
try {
  for(const kind of ['share','viewer'])for(const width of [320,393,1280]) {
    test(`${kind}・${width}px：構成はPC限定・台別顔文字の保存・欠測日・再読込`,async()=>{
      const context=await browser.newContext({viewport:{width,height:950},serviceWorkers:'block'}),page=await context.newPage(),errors=[],posts=[];
      page.on('pageerror',e=>errors.push(e.message));
      if(process.env.VIEWER_TEST_FONT){const font=await fs.readFile(process.env.VIEWER_TEST_FONT),emoji=process.env.VIEWER_TEST_EMOJI_FONT?await fs.readFile(process.env.VIEWER_TEST_EMOJI_FONT):font;await context.route('https://fonts.gstatic.com/**',r=>r.fulfill({contentType:'font/otf',headers:{'access-control-allow-origin':'*'},body:r.request().url().includes('notocoloremoji')?emoji:font}));}
      let history={format:'database-event-history',version:1,base:{version:2,store:'nagamachiminami',symbols:['😍','😀','😌','🥶','😇'],weeks:[{type:'4台構成',from:'2026-10-19',to:'2026-10-25',machines:[{name:'旧週の機種',count:1,record_name:'旧週の機種',results:Array(7).fill('')}]}]},cells:[],links:[],weeks:[],recommendations:[],recommendation_results:[],shared_editing:true,recommendations_editing:false,recommendation_results_editing:true};
      let failPosts=false;
      await context.route('https://script.google.com/**',async route=>{
        const request=route.request(),file=new URL(request.url()).searchParams.get('file');
        let body;
        if(request.method()==='POST') {
          const payload=request.postDataJSON();posts.push(payload);
          if(failPosts)return route.fulfill({status:503,body:'送信失敗'});
          assert.equal(payload.file,'event-history');assert.ok(Array.isArray(payload.cells));
          history={...mergeHistoryCells(history,payload.cells),recommendation_results:mergeRecommendationResults(history.recommendation_results,payload.recommendation_results??[])};
          body={ok:true,history};
        }else body=file==='event-history'?history:!file?backup:file==='pscube'?{format:'pscube-viewer',version:1,records:[]}:{format:'database-events',version:1,events:[],marks:[]};
        return route.fulfill({contentType:'application/json',headers:{'access-control-allow-origin':'*'},body:JSON.stringify(body)});
      });
      async function open() {
        await page.goto(origin+'/setup');
        if(kind==='share') {
          await page.goto(origin+'/share/#s='+id);await page.getByRole('button',{name:'イベント履歴',exact:true}).click();
          await page.getByRole('button',{name:'4大オススメ',exact:true}).click();
        }else {
          await page.goto(origin+'/database-viewer/');await page.waitForSelector('flt-glass-pane',{state:'attached',timeout:60000});
          const placeholder=page.locator('flt-semantics-placeholder');if(await placeholder.count())await placeholder.evaluate(e=>e.click());
          await page.getByRole('button',{name:'長町南のイベント履歴',exact:true}).click({timeout:60000});
          await page.getByRole('button',{name:/4台構成/}).click();await page.getByRole('menuitem',{name:'4大オススメ',exact:true}).click();
        }
      }
      try {
        await page.goto(origin+'/setup');
        if(kind==='viewer') await page.evaluate(async({backup,script})=>{
          localStorage.setItem('database-viewer-remote',script);
          const db=await new Promise((resolve,reject)=>{const q=indexedDB.open('database-viewer',1);q.onupgradeneeded=()=>q.result.createObjectStore('kv');q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error);});
          await new Promise((resolve,reject)=>{const tx=db.transaction('kv','readwrite');tx.objectStore('kv').put(JSON.stringify(backup),'data');tx.objectStore('kv').put('meruhen','active_source');tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);});db.close();
        },{backup,script});
        await open();
        if(kind==='share') {
          assert.equal(await page.locator('[data-recommendation-slot]').count(),0);
          assert.equal(await page.locator('[data-recommendation-add]').count(),0);
          assert.equal(await page.locator('.recommendation-table').count(),4);
          assert.equal(await page.locator('.recommendation-card h3:visible').count(),4,'各カードで機種名が見える');
          const row=page.locator('.recommendation-table').first().locator('tbody tr').first();
          assert.match(await row.innerText(),/100番/);assert.match(await row.locator('td').nth(0).innerText(),/0/);
          assert.equal(await row.locator('td').nth(0).locator('select').inputValue(),'auto');
          assert.match(await row.locator('td').nth(1).locator('option:checked').innerText(),/—/);
          assert.match(await row.locator('td').nth(2).innerText(),/0/);
          await page.getByLabel('2026-10-26 100番の顔文字',{exact:true}).selectOption('😇');
        }else {
          assert.equal(await page.getByRole('button',{name:'4機種を保存',exact:true}).count(),0);
          assert.equal(await page.getByRole('button',{name:'4大オススメの週を追加',exact:true}).count(),0);
          await page.getByRole('button',{name:/2026-10-26 .*100番の顔文字/}).click();
          await page.getByRole('menuitem',{name:'😇',exact:true}).click();
        }
        await page.waitForFunction(()=>document.body.textContent.includes('共有へ保存しました。'));
        assert.equal(posts.length,1);assert.equal(posts[0].recommendation_results[0].value,'😇');assert.equal(posts[0].recommendation_results[0].rack,100);
        assert.equal(posts[0].recommendations,undefined,'閲覧・共有からは構成を送信しない');
        await open();
        if(kind==='share')assert.equal(await page.getByLabel('2026-10-26 100番の顔文字',{exact:true}).inputValue(),'😇');
        else assert.match(await page.getByRole('button',{name:/2026-10-26 .*100番の顔文字/}).innerText(),/😇/);
        // 画像は調査時の明示指定だけ。GitHubランナーにクラウド専用の保存先はない。
        if(width===393 && process.env.RECOMMENDATIONS_SCREENSHOTS){
          const directory=path.resolve(process.env.RECOMMENDATIONS_SCREENSHOTS);
          await fs.mkdir(directory,{recursive:true});
          await page.screenshot({path:path.join(directory,`${kind}-393.png`)});
        }
        failPosts=true;
        if(kind==='share')await page.getByLabel('2026-10-26 100番の顔文字',{exact:true}).selectOption('🥶');
        else {await page.getByRole('button',{name:/2026-10-26 .*100番の顔文字/}).click();await page.getByRole('menuitem',{name:'🥶',exact:true}).click();}
        await page.waitForFunction(()=>document.body.textContent.includes('送信待ち')||document.body.textContent.includes('保存できませんでした'));
        await page.waitForTimeout(100);
        const saved=await page.evaluate(()=>Object.entries(localStorage).filter(([k])=>k.includes('recommendation-results')||k.includes('event-history-pending')));
        assert.ok(saved.some(([,v])=>v.includes('🥶')));
        if(kind==='viewer'&&width===393) {
          failPosts=false;
          await page.goto(origin+'/setup');await page.goto(origin+'/database-viewer/');
          await page.waitForSelector('flt-glass-pane',{state:'attached',timeout:60000});
          const placeholder=page.locator('flt-semantics-placeholder');if(await placeholder.count())await placeholder.evaluate(e=>e.click());
          await page.getByRole('button',{name:'長町南のイベント履歴',exact:true}).click({timeout:60000});
          await page.getByRole('button',{name:/2026-10-19 旧週の機種の顔文字/}).click();
          await page.getByRole('menuitem',{name:'😍',exact:true}).click();
          await page.waitForFunction(()=>document.body.textContent.includes('共有へ保存しました。'));
          assert.equal(posts.at(-1).cells[0].value,'😍','既存の週表もiPhoneから編集できる');
        }
        assert.deepEqual(errors,[]);
        if(kind==='share')assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      }catch(e){console.error(JSON.stringify({kind,width,errors,labels:await page.locator('flt-semantics').allTextContents()}));throw e;}finally{await context.close();}
    });
  }
} finally {
  // node:testの実行終了後までブラウザとローカルサーバーを維持する。
  test.after(async()=>{await browser.close();await new Promise(r=>server.close(r));});
}
