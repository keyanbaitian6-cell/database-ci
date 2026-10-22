// 新しくビルド・stageしたiPhone閲覧ページを合成Google応答で確認する。
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
const title={saiwaichou:'幸町のバラエティ履歴',nagamachiminami:'長町南のイベント履歴'};
const longName='L スマスロ 長い機種名の折り返しを確認するテスト機種';
function historyBase(store){return {version:2,store,symbols:store==='saiwaichou'?['優','良']:['😍','😀'],weeks:
  ['2026-10-05','2026-10-12','2026-10-19'].map(from=>({type:'バラエティ',from,to:new Date(Date.parse(from+'T00:00:00Z')+6*86400000).toISOString().slice(0,10),
    machines:['機種A',longName].map((name,i)=>({name,record_name:name,count:1,results:[...(i?['']: [store==='saiwaichou'?'優':'😍']),...Array(6).fill('')]}))}))};}
try{
  for(const width of [320,393,1280]) for(const store of ['saiwaichou','nagamachiminami']){
    const context=await browser.newContext({viewport:{width,height:900},serviceWorkers:'block'});
    const page=await context.newPage(), errors=[], requests=[];
    page.on('pageerror',e=>errors.push(e.message));
    const records=['機種A',longName].map((machine,i)=>({store,day:'2026-10-23',machine,rack:i+1,games:1000,bb:4,rb:2}));
    const backup={format:'database-backup',version:1,records,date_events:[]};
    const empty={format:'database-event-history',version:1,weeks:[],cells:[],links:[]};
    const history={...empty,base:historyBase('nagamachiminami'),saiwaichou_variety:{...empty,base:historyBase('saiwaichou')}};
    await context.route('https://script.google.com/**',route=>{
      const request=route.request();requests.push(request.method());
      const file=new URL(request.url()).searchParams.get('file');
      return route.fulfill({contentType:'application/json',headers:{'access-control-allow-origin':'*'},body:JSON.stringify(file==='event-history'?history:!file?backup:{format:'database-events',version:1,events:[],marks:[]})});
    });
    try{
      await page.goto(origin+'/setup');
      await page.evaluate(async backup=>{
        localStorage.setItem('database-viewer-remote','https://script.google.com/macros/s/TEST_HISTORY/exec');
        const db=await new Promise((resolve,reject)=>{const q=indexedDB.open('database-viewer',1);q.onupgradeneeded=()=>q.result.createObjectStore('kv');q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error);});
        await new Promise((resolve,reject)=>{const tx=db.transaction('kv','readwrite');tx.objectStore('kv').put(JSON.stringify(backup),'data');tx.objectStore('kv').put('meruhen','active_source');tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);});db.close();
      },backup);
      await page.goto(origin+prefix);
      await page.waitForSelector('flt-glass-pane',{state:'attached',timeout:60000});
      const placeholder=page.locator('flt-semantics-placeholder');if(await placeholder.count())await placeholder.evaluate(e=>e.click());
      await page.getByRole('button',{name:title[store],exact:true}).click({timeout:60000});
      if(store==='nagamachiminami'){
        await page.getByRole('button',{name:/4台構成/}).click();
        await page.getByRole('menuitem',{name:'バラエティ',exact:true}).click();
      }
      // Flutterは選択欄の見出しと選択中の値を1つの読み上げ要素にまとめるため、組で完全一致を確かめる。
      const week=(from,to)=>page.getByText(new RegExp(`^対象週\\s*${from}〜${to}$`)).waitFor();
      await week('2026-10-19','2026-10-25');
      await page.getByRole('button',{name:'前の週',exact:true}).click();
      await week('2026-10-12','2026-10-18');
      await page.getByRole('button',{name:'最新の週',exact:true}).click();
      await week('2026-10-19','2026-10-25');
      if(process.env.HISTORY_SCREENSHOTS){await fs.mkdir(process.env.HISTORY_SCREENSHOTS,{recursive:true});await page.screenshot({path:path.join(process.env.HISTORY_SCREENSHOTS,`viewer-history-${store}-${width}.png`)});}
      assert.deepEqual(errors,[]);
      assert.equal(requests.includes('POST'),false,'閲覧と週移動で実データへ書き込まない');
    }catch(error){console.error(JSON.stringify({width,store,errors,labels:await page.locator('flt-semantics').allTextContents()}));throw error;}
    finally{await context.close();}
  }
  console.log('PASS: iPhone閲覧の履歴・週切り替え・両店舗・320/393/1280px（合成応答）');
}finally{await browser.close();server.close();}
