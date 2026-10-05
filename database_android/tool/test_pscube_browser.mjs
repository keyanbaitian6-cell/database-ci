// Build viewer_main.dart and stage_viewer.py before this browser test.
// Tests yesterday's old IndexedDB data with the shared Flutter UI.
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = process.env.VIEWER_WEB_ROOT || fileURLToPath(new URL('../build/web/', import.meta.url));
const prefix = '/database-viewer/';
const server = http.createServer(async (req,res) => {
  let url = new URL(req.url,'http://localhost').pathname;
  if (url === '/setup') { res.setHeader('content-type','text/html');res.end('<!doctype html><body>setup</body>');return; }
  if (!url.startsWith(prefix)) { res.writeHead(404).end();return; }
  url = url.slice(prefix.length);
  const local = path.resolve(root, (!url || url.endsWith('/')) ? url+'index.html' : url);
  if (!local.startsWith(path.resolve(root)+path.sep)) { res.writeHead(403).end();return; }
  try {
    const body=await fs.readFile(local),ext=path.extname(local);
    res.setHeader('content-type',({'.js':'text/javascript','.mjs':'text/javascript','.json':'application/json',
      '.wasm':'application/wasm','.html':'text/html','.css':'text/css','.png':'image/png'})[ext] || 'application/octet-stream');
    res.end(body);
  } catch { res.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
const origin='http://127.0.0.1:'+server.address().port;
const base='https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/cgi-bin/';
const machines=[{store:'c740601',rate:'20',machine:'マイジャグラーV',machine_type:'normal',
  expected_count:8,url:base+'nc-v05-011.php?cd_ps=2&bai=20'}];
const records=[];
for(let ago=0;ago<7;ago++){
  const date=new Date('2026-10-01T00:00:00Z');date.setUTCDate(date.getUTCDate()-ago);
  const day=date.toISOString().slice(0,10);
  for(let rack=1;rack<=8;rack++)records.push({store:'c740601',rate:'20',machine:'マイジャグラーV',rack,day,
    bb:rack*2,rb:rack,games:3000,my:rack*500,at_art:0,
    detail_url:base+'nc-v06-001.php?cd_dai='+rack+'#'+day.replaceAll('-',''),
    graph:{kind:'daily',zero_y:100,points:[[0,100],[10,20],[20,40]]}});
}
const data={format:'pscube-viewer',version:1,machines,records};
const exported='2026-10-01T23:00:00+09:00';
const meruhen={header:{format:'database-backup',version:1,source:'pc',exported_at:exported},
  records:records.map(r=>({store:'nagamachiminami',machine:r.machine,day:r.day,rack:r.rack,games:r.games,
    bb:r.bb,rb:r.rb,max_hold:r.my,graph_measurement:{baseline_y:100,peak_y:20,trough_y:100,end_y:40,
      curve:[[0,100],[10,20],[20,40]]}}))};
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH || undefined,args:['--no-sandbox'],...(process.env.BROWSER_PROXY ? {proxy:{server:process.env.BROWSER_PROXY,bypass:'127.0.0.1,localhost'}} : {})});
const page=await browser.newPage({viewport:{width:393,height:852}});
const errors=[];
page.on('pageerror',e=>{errors.push(e.message);console.error('pageerror',e.message);});

let driveRequests=[];
// Optional local font for network-restricted test environments.
if(process.env.VIEWER_TEST_FONT){
  const font=await fs.readFile(process.env.VIEWER_TEST_FONT);
  await page.route('https://fonts.gstatic.com/**',route=>route.fulfill({status:200,contentType:'font/otf',headers:{'access-control-allow-origin':'*'},body:font}));
}
await page.route('https://script.google.com/**',route=>{
  driveRequests.push(route.request().url());
  return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({...data,exported_at:exported})});
});

async function accessibility(){
  await page.waitForSelector('flt-glass-pane',{state:'attached',timeout:60000});
  const placeholder=page.locator('flt-semantics-placeholder');
  if(await placeholder.count())await placeholder.evaluate(e=>e.click());
  await page.getByText('database 閲覧',{exact:true}).waitFor({timeout:60000}).catch(async e=>{await page.screenshot({path:'/tmp/pscube-failure.png'});console.log(await page.locator('body').innerHTML());throw e;});
}
async function readStored(dbName,store,key){
  return page.evaluate(async ({dbName,store,key})=>{
    const db=await new Promise((resolve,reject)=>{const q=indexedDB.open(dbName,1);q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error);});
    const value=await new Promise((resolve,reject)=>{const q=db.transaction(store).objectStore(store).get(key);q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error);});
    db.close();return value;
  },{dbName,store,key});
}
try {
  await page.goto(origin+'/setup');
  await page.evaluate(async ({data,meruhen,exported})=>{
    for(const [name,store,entries] of [
      ['database-pscube-viewer','state',[['data',data],['meta',{exported_at:exported}]]],
      ['database-viewer','kv',[['data',JSON.stringify(meruhen)]]],
    ]){
      const db=await new Promise((resolve,reject)=>{const q=indexedDB.open(name,1);q.onupgradeneeded=()=>q.result.createObjectStore(store);q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error);});
      await new Promise((resolve,reject)=>{const tx=db.transaction(store,'readwrite');for(const [key,value]of entries)tx.objectStore(store).put(value,key);tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);});db.close();
    }
  },{data,meruhen,exported});
  await page.goto(origin+prefix+'pscube/');
  await accessibility();
  assert.equal(JSON.parse(await page.evaluate(()=>window.databaseViewer.load())).records.length,56);
  await page.getByRole('button',{name:'末尾別データまとめ',exact:true}).click();
  await page.getByRole('switch',{name:/末尾イベの印/}).click();
  await page.getByRole('switch',{checked:true}).waitFor();
  const marksBefore=(await readStored('database-pscube-viewer','state','data')).suffix_events;
  assert.equal(marksBefore[0].enabled,true);
  assert.equal((await readStored('database-pscube-viewer','state','data')).records.length,56);
  await page.reload();await accessibility();
  await page.getByRole('button',{name:'末尾別データまとめ',exact:true}).click();
  await page.getByRole('switch',{checked:true}).waitFor();
  const headline = page.getByRole('group',{name:/平均点の首位：/});
  await headline.waitFor();
  assert.ok((await headline.boundingBox()).y < 852, 'day winner is immediately visible');
  await page.screenshot({path:process.env.PSCUBE_SUFFIX_SCREENSHOT || '/tmp/pscube-suffix-summary.png'});
  await page.mouse.move(200,700); await page.mouse.wheel(0,600); await page.waitForTimeout(300);
  await page.getByRole('group',{name:/^日別の首位/}).waitFor();
  assert.ok((await page.getByRole('button',{name:/2026-10-01.*末尾イベ/s}).count())>0);
  await page.screenshot({path:'/tmp/pscube-suffix-history.png'});
  await page.mouse.wheel(0,-400); await page.waitForTimeout(300);
  await page.getByRole('button',{name:'8末尾すべての順位・内訳を見る',exact:true}).click();
  await page.mouse.move(200,700); await page.mouse.wheel(0,900); await page.waitForTimeout(300);
  await page.getByRole('button',{name:'末尾1',exact:true}).click();
  await page.getByText('末尾1の内訳',{exact:true}).waitFor();
  await page.getByText('グラフ表示',{exact:true}).click();
  await page.screenshot({path:'/tmp/pscube-suffix-details.png'});
  await page.goto(origin+prefix+'pscube/');await accessibility();

  assert.equal(await page.getByText('準備版',{exact:true}).count(),0);
  await page.screenshot({path:process.env.PSCUBE_SCREENSHOT || '/tmp/pscube-shared-home.png'});
  await page.mouse.move(200,700);
  await page.mouse.wheel(0,1800);
  await page.waitForTimeout(500);
  await page.screenshot({path:'/tmp/pscube-scrolled.png'});

  await page.getByRole('button',{name:/^マイジャグラーV/}).last().scrollIntoViewIfNeeded();
  await page.getByRole('button',{name:/^マイジャグラーV/}).last().click();
  await page.getByText('データ表示',{exact:true}).waitFor();
  assert.ok((await page.locator('flt-semantics-host').innerHTML()).includes('MY'));
  await page.getByText('グラフ表示',{exact:true}).click();
  await page.screenshot({path:'/tmp/pscube-shared-graphs.png'});
  await page.getByRole('button',{name:'前の記録日',exact:true}).click();
  await page.getByRole('button',{name:/表示する日付.*2026-09-30/s}).waitFor();
  assert.ok((await page.getByText('グラフ表示',{exact:true}).count())>0);
  await page.goto(origin+prefix);
  await accessibility();
  assert.deepEqual(JSON.parse(await readStored('database-viewer','kv','data')),meruhen);
  await page.screenshot({path:'/tmp/meruhen-shared-home.png'});
  const chooserPromise=page.waitForEvent('filechooser');
  await page.getByRole('button',{name:'バックアップを読み込む',exact:true}).click();
  await(await chooserPromise).setFiles({name:'pscube-viewer.json',mimeType:'application/json',
    buffer:Buffer.from(JSON.stringify(data))});
  await page.getByRole('button',{name:'バックアップを書き出す',exact:true}).waitFor();
  assert.deepEqual(JSON.parse(await readStored('database-viewer','kv','data')),meruhen);
  assert.equal(await readStored('database-viewer','kv','active_source'),'pscube');
  const downloadPromise=page.waitForEvent('download');
  await page.getByRole('button',{name:'バックアップを書き出す',exact:true}).click();
  const download=await downloadPromise;
  const backup=JSON.parse(await fs.readFile(await download.path(),'utf8'));
  assert.equal(backup.records.length,56);assert.equal(backup.records[0].max_hold,undefined);
  assert.ok(backup.records[0].my>0);
  assert.deepEqual(backup.suffix_events,marksBefore,'mark survives a PC-style import and is included in browser backup');
  await page.evaluate(async oldBackup=>{
    await window.databaseViewer.setSuffixEvent('pscube:c740601:20','2026-10-01',false);
    await window.databaseViewer.save(JSON.stringify(oldBackup));
  },backup);
  assert.equal((await readStored('database-pscube-viewer','state','data')).suffix_events[0].enabled,false,'old marked backup does not undo a removal');
  const recordsBefore=JSON.stringify((await readStored('database-pscube-viewer','state','data')).records);
  const refused=await page.evaluate(async()=>{
    try {await window.databaseViewer.setSuffixEvent('pscube:c740601:5','2026-10-01',true);return false;} catch{return true;}
  });
  assert.equal(refused,true);
  assert.equal(JSON.stringify((await readStored('database-pscube-viewer','state','data')).records),recordsBefore);

  await page.evaluate(()=>window.databaseViewer.setPscubeType('pscube:c740601:20','マイジャグラーV','other'));
  assert.equal((await readStored('database-pscube-viewer','state','data')).machines[0].machine_type,'other');
  const badChooser=page.waitForEvent('filechooser');
  await page.getByRole('button',{name:'バックアップを読み込む',exact:true}).click();
  await(await badChooser).setFiles({name:'bad.json',mimeType:'application/json',buffer:Buffer.from('{broken')});
  await page.getByText(/バックアップを読み込めませんでした/).waitFor();
  assert.equal((await readStored('database-pscube-viewer','state','data')).records.length,56);
  await page.evaluate(()=>window.databaseViewer.setRemote('https://script.google.com/macros/s/test/exec'));
  const driveResponse=page.waitForResponse(response=>response.url().includes('script.google.com'));
  await page.reload();await accessibility();
  await driveResponse;
  await page.waitForFunction(()=>document.querySelector('flt-semantics')!=null);
  await page.getByText(/Googleドライブ/).first().waitFor();
  await page.getByText('Googleドライブの最新（56台）を読み込みました。').last().waitFor();
  assert.ok(driveRequests.some(url=>url.includes('file=pscube')));
  assert.equal((await readStored('database-pscube-viewer','state','data')).suffix_events[0].enabled,false,'Drive update preserves removal');
  await page.evaluate(async incoming=>{
    await Promise.all([
      window.databaseViewer.setSuffixEvent('pscube:c740601:20','2026-09-30',true),
      window.databaseViewer.save(JSON.stringify(incoming)),
      window.databaseViewer.setSuffixEvent('pscube:c740601:20','2026-09-29',true),
    ]);
  },data);
  const afterConcurrent=await readStored('database-pscube-viewer','state','data');
  assert.equal(afterConcurrent.records.length,56);
  assert.ok(afterConcurrent.suffix_events.some(e=>e.day==='2026-09-30'&&e.enabled));
  assert.ok(afterConcurrent.suffix_events.some(e=>e.day==='2026-09-29'&&e.enabled));
  assert.equal(afterConcurrent.suffix_events.find(e=>e.day==='2026-10-01').enabled,false);
  const probe={rack:1,day:'20261001',graph:{datas:{
    g:[{YMD_biz:20261001,xField:'out-1',yField:'value-1'}],
    p:[{'out-1':0,'value-1':7092},{'out-1':25,'value-1':21210}],
  }}};
  await page.getByRole('button',{name:'差枚の元データを貼り付け',exact:true}).click();
  await page.getByRole('textbox',{name:'グラフJSONを貼り付け'}).fill(JSON.stringify(probe));
  await page.getByRole('button',{name:'取り込む',exact:true}).click();
  await page.waitForFunction(async()=>{
    const db=await new Promise((resolve,reject)=>{const q=indexedDB.open('database-pscube-viewer',1);q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error);});
    const value=await new Promise((resolve,reject)=>{const q=db.transaction('state').objectStore('state').get('data');q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error);});
    db.close();return value?.records?.some(r=>r.rack===1&&r.day==='2026-10-01'&&r.net_medals===14118);
  });
  await page.mouse.move(200,700); await page.mouse.wheel(0,350);
  await page.getByRole('button',{name:'日別の差枚',exact:true}).scrollIntoViewIfNeeded();
  await page.getByRole('button',{name:'日別の差枚',exact:true}).click();
  await page.getByText('+14,118',{exact:true}).first().waitFor();
  await page.getByText('1/8',{exact:true}).waitFor();
  const withNet=await readStored('database-pscube-viewer','state','data');
  assert.equal(withNet.records.find(r=>r.rack===1&&r.day==='2026-10-01').net_medals,14118);
  assert.equal(withNet.records.find(r=>r.rack===1&&r.day==='2026-10-01').my,500);
  assert.deepEqual(errors,[]);
  console.log('PASS: old IndexedDB migration, shared UI, data/graph tabs, day navigation, original Meruhen preservation, root P’s CUBE import, export, category, failed import, Drive source and signed graph import');
} finally {await browser.close();await new Promise(resolve=>server.close(resolve));}
