// iPhone閲覧ページで、PCが週単位で入れたバラエティの週（文書の weeks）の顔文字を共有へ送れることを確かめる。
// 2026-10-25：この週の顔文字が送信待ちに残らず「共有用Apps Scriptの更新後に再読み込みしてください」で止まっていた。
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(process.env.VIEWER_WEB_ROOT||fileURLToPath(new URL('../build/web/',import.meta.url)));
const prefix='/database-viewer/';
const server=http.createServer(async(req,res)=>{
  const pathname=new URL(req.url,'http://x').pathname;
  if(pathname==='/setup') return res.end('<!doctype html><body>setup</body>');
  if(!pathname.startsWith(prefix)) return res.writeHead(404).end();
  const local=path.resolve(root,pathname.slice(prefix.length)||'index.html');
  if(!local.startsWith(root+path.sep)) return res.writeHead(403).end();
  try{res.setHeader('content-type',({'.js':'text/javascript','.mjs':'text/javascript','.json':'application/json','.wasm':'application/wasm','.html':'text/html','.png':'image/png'})[path.extname(local)]||'application/octet-stream');res.end(await fs.readFile(local));}
  catch{res.writeHead(404).end();}
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const origin=`http://127.0.0.1:${server.address().port}`;
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||undefined,args:['--no-sandbox']});
const store='nagamachiminami';
const base={version:2,store,symbols:['😍','😀'],user_blank_days:[],weeks:[{type:'バラエティ',from:'2026-10-12',to:'2026-10-18',
  machines:[{name:'機種A',record_name:'機種A',count:1,results:Array(7).fill('')}]}]};
// 実データと同じく、最新週はPCの週単位の入力（文書の weeks）にだけある。
const history={format:'database-event-history',version:1,base,cells:[],links:[],
  weeks:[{store,type:'バラエティ',week:'2026-10-19',lineup_day:'2026-10-20',machines:[{name:'機種A',record_name:'機種A',count:1}],
    updated_at:'2026-10-20T09:00:00.000000+09:00',removed:false}],
  shared_editing:true,recommendations_editing:false,recommendation_results_editing:true};
try{
  for(const width of [320,393]){
    const context=await browser.newContext({viewport:{width,height:900},serviceWorkers:'block'});
    const page=await context.newPage(), errors=[], posts=[];
    page.on('pageerror',e=>errors.push(e.message));
    const records=[{store,day:'2026-10-20',machine:'機種A',rack:1,games:1000,bb:4,rb:2}];
    let shared=structuredClone(history);
    await context.route('https://script.google.com/**',route=>{
      const request=route.request();
      const json=body=>route.fulfill({contentType:'application/json',headers:{'access-control-allow-origin':'*'},body:JSON.stringify(body)});
      if(request.method()==='POST'){
        const body=JSON.parse(request.postData());posts.push(body);
        shared={...shared,cells:[...shared.cells,...body.cells]};
        return json({ok:true,history:shared});
      }
      const file=new URL(request.url()).searchParams.get('file');
      return json(file==='event-history'?shared:!file?{format:'database-backup',version:1,records,date_events:[]}:{format:'database-events',version:1,events:[],marks:[]});
    });
    try{
      await page.goto(origin+'/setup');
      await page.evaluate(async backup=>{
        localStorage.setItem('database-viewer-remote','https://script.google.com/macros/s/TEST_HISTORY_EDIT/exec');
        const db=await new Promise((resolve,reject)=>{const q=indexedDB.open('database-viewer',1);q.onupgradeneeded=()=>q.result.createObjectStore('kv');q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error);});
        await new Promise((resolve,reject)=>{const tx=db.transaction('kv','readwrite');tx.objectStore('kv').put(JSON.stringify(backup),'data');tx.objectStore('kv').put('meruhen','active_source');tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);});db.close();
      },{format:'database-backup',version:1,records,date_events:[]});
      await page.goto(origin+prefix);
      await page.waitForSelector('flt-glass-pane',{state:'attached',timeout:60000});
      const placeholder=page.locator('flt-semantics-placeholder');if(await placeholder.count())await placeholder.evaluate(e=>e.click());
      await page.getByRole('button',{name:'長町南のイベント履歴',exact:true}).click({timeout:60000});
      await page.getByRole('button',{name:/4台構成/}).click();
      await page.getByRole('menuitem',{name:'バラエティ',exact:true}).click();
      await page.getByText(/^対象週\s*2026-10-19〜2026-10-25$/).waitFor();
      // 読み上げ名は「日付 機種の顔文字」のあとに、いまの値（—）が続く。
      await page.getByRole('button',{name:/^2026-10-21 機種Aの顔文字/}).click();
      await page.getByRole('menuitem',{name:'😍',exact:true}).click();
      for(let i=0;i<80&&!posts.length;i++) await page.waitForTimeout(100);
      assert.equal(posts.length,1,'PCの週単位の週の顔文字を共有へ送る');
      assert.deepEqual(posts[0].cells.map(c=>[c.type,c.week,c.machine,c.day,c.value,c.device]),
        [['バラエティ','2026-10-19','機種A','2026-10-21','😍','shared']]);
      // 送信待ちは共有の返事を確かめてから消える。返事の処理を待って確かめる。
      const pendingLists=()=>page.evaluate(()=>Object.entries(localStorage).filter(([k])=>k.includes('event-history-pending')).map(([,v])=>JSON.parse(v)));
      let pending=await pendingLists();
      for(let i=0;i<80&&pending.some(p=>p.cells.length);i++){await page.waitForTimeout(100);pending=await pendingLists();}
      assert.equal(pending.length,1);
      assert.ok(pending.every(p=>!p.cells.length && !p.weeks.length),'送信後は送信待ちを残さず、週の定義も保存しない');
      assert.deepEqual(errors,[]);
    }catch(error){console.error(JSON.stringify({width,errors,posts,labels:await page.locator('flt-semantics').allTextContents()}));throw error;}
    finally{await context.close();}
  }
  console.log('PASS: 閲覧ページでPCの週単位の週の顔文字を共有へ送る・320/393px（合成応答）');
}finally{await browser.close();server.close();}
