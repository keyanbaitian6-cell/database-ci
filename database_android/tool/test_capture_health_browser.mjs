// 新しいFlutterビルドと共有stageを使い、両画面で欠測・0枚・更新工程を確認する。
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const roots={viewer:process.env.VIEWER_WEB_ROOT || fileURLToPath(new URL('../build/web/',import.meta.url)),
  share:process.env.SHARE_WEB_ROOT || fileURLToPath(new URL('../../share_viewer/',import.meta.url))};
const server=http.createServer(async(req,res)=>{
  const [area,...pieces]=new URL(req.url,'http://test').pathname.slice(1).split('/');
  if(pieces[0]==='_setup'){res.setHeader('content-type','text/html');res.end('<body>初期化</body>');return;}
  const root=roots[area];if(!root){res.writeHead(404).end();return;}
  const requested=pieces.join('/');
  const file=path.resolve(root,!requested || requested.endsWith('/') ? requested+'index.html' : requested);
  if(!file.startsWith(path.resolve(root)+path.sep)){res.writeHead(403).end();return;}
  try{res.setHeader('content-type',({'.html':'text/html; charset=utf-8','.mjs':'text/javascript','.js':'text/javascript','.wasm':'application/wasm','.json':'application/json'})[path.extname(file)] || 'application/octet-stream');res.end(await fs.readFile(file));}
  catch{res.writeHead(404).end();}
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const origin=`http://127.0.0.1:${server.address().port}`;
const data=JSON.parse(await fs.readFile(new URL('../../database/tests/fixtures/pscube_net_capture.json',import.meta.url),'utf8'));
const at=new Date().toISOString(),day=new Date(Date.now()+9*3600000).toISOString().slice(0,10),older=new Date(Date.parse(day)-86400000).toISOString().slice(0,10);
const base=data.records[0];data.records=[];data.machines[0].expected_count=2;
for(const d of [older,day]) for(const rack of [1,2]) data.records.push({...base,day:d,rack,
  detail_url:base.detail_url.replace('cd_dai=1','cd_dai='+rack).replace('20261001',d.replaceAll('-','')),
  net_medals:rack===2 ? 0 : null,net_capture:{version:1,status:rack===2 ? 'ok':'network',reason:rack===2 ? 'ok':'network',checked_at:at}});
data.source='cloud';data.exported_at=at;data.sync_status={version:1,writes:[{source:'pc',at,drive_at:at,
  stores:[{store:'c740601',rate:'20',day,count:2}]}],processed_at:at,supplement_supported:true,
  supplement:{at,applied:1,known:1,mismatched:0,unmatched:0}};
const id='AKfycbTEST'+'x'.repeat(40),methods=[];
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH || undefined,args:['--no-sandbox']});
try{
  for(const width of [320,393,1280]) for(const area of ['viewer','share']){
    const context=await browser.newContext({viewport:{width,height:852}}),page=await context.newPage(),errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    if(process.env.VIEWER_TEST_FONT){const font=await fs.readFile(process.env.VIEWER_TEST_FONT);await page.route('https://fonts.gstatic.com/**',r=>r.fulfill({contentType:'font/otf',headers:{'access-control-allow-origin':'*'},body:font}));}
    await context.route('https://script.google.com/**',route=>{
      const req=route.request(),q=new URL(req.url()).searchParams;methods.push(req.method());
      const body=q.get('file')==='pscube' ? data : !q.get('file') ? {format:'database-backup',version:1,records:[]} : {format:'database-events',version:1,events:[],marks:[]};
      return route.fulfill({contentType:'application/json',headers:{'access-control-allow-origin':'*'},body:JSON.stringify(body)});
    });
    if(area==='viewer'){
      await page.goto(`${origin}/viewer/_setup`);
      await page.evaluate(async({data,at})=>{
        const db=await new Promise((resolve,reject)=>{const q=indexedDB.open('database-pscube-viewer',1);q.onupgradeneeded=()=>q.result.createObjectStore('state');q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error);});
        await new Promise((resolve,reject)=>{const tx=db.transaction('state','readwrite'),s=tx.objectStore('state');s.put(data,'data');s.put({exported_at:at,loaded_at:at},'meta');tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);});db.close();
      },{data,at});
      await page.goto(`${origin}/viewer/pscube/`);
      await page.waitForSelector('flt-glass-pane',{state:'attached',timeout:60000});
      const placeholder=page.locator('flt-semantics-placeholder');if(await placeholder.count())await placeholder.evaluate(e=>e.click());
      await page.getByRole('button',{name:'更新・差枚の取得状況',exact:true}).click({timeout:60000});
      await page.getByText(/差枚：2台中1台取得済み（0枚1台）・未取得1台/).waitFor();
      const text=await page.locator('flt-semantics').allTextContents();
      assert.ok(text.join('\n').includes('1番 診断試験機種：差枚の通信失敗'));
      assert.ok(text.join('\n').includes('スマホ補完：反映 1件'));
      if(width===393)await page.screenshot({path:'/tmp/acb-viewer-health.png'});
    }else{
      await page.goto(`${origin}/share/index.html#s=${id}`);await page.locator('.grid').waitFor();
      await page.locator('[data-health] summary').click();
      const health=page.locator('[data-health]');await health.getByText(/差枚：2台中1台取得済み（0枚1台）・未取得1台/).waitFor();
      assert.match(await health.innerText(),/1番 診断試験機種：差枚の通信失敗/);
      assert.match(await health.innerText(),/スマホ補完：反映 1件/);
      await page.locator('[data-health-day]').selectOption(older);
      assert.equal(await page.locator('[data-health]').evaluate(e=>e.open),true);
      await page.reload();await page.locator('.grid').waitFor();await page.locator('[data-health] summary').click();
      assert.match(await page.locator('[data-health]').innerText(),/スマホ補完：反映 1件/,'オフライン用の保存でも工程を保持する');
      if(width===393)await page.screenshot({path:'/tmp/acb-share-health.png',fullPage:true});
    }
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    assert.deepEqual(errors,[]);await context.close();
  }
  assert.ok(methods.every(m=>m==='GET'),'取得状況を開いても更新や再取得を送らない');
  console.log('確認成功：閲覧・共有の3幅で欠測・0枚・工程・保存後の再表示を区別し、通信は読取のみ。');
}finally{await browser.close();await new Promise(r=>server.close(r));}
