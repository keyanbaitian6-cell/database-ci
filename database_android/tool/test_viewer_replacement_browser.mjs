// Build viewer_main.dart and stage_viewer.py before this browser test.
// Tests replacement and renumbering against saved synthetic records in both viewers.
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

const browser = await chromium.launch({headless:true, executablePath:process.env.CHROMIUM_PATH || undefined,args:['--no-sandbox']});
const records=[];
for(const [day,machine,start] of [
  ['2026-10-05','化物語',1085],['2026-10-04','北斗',1085],
  ['2026-10-05','マイジャグラーV',1100],['2026-10-04','マイジャグラーV',1200],
]) for(let rack=start;rack<start+4;rack++)records.push({store:'c740601',rate:'20',machine,rack,day,
  games:3000,bb:10,rb:5,my:1000,at_art:0,
  detail_url:`https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/cgi-bin/nc-v06-001.php?cd_dai=${rack}#${day.replaceAll('-','')}`,
  graph:{kind:'daily',zero_y:100,points:[[0,100],[10,20],[20,40]]}});
const pscube={format:'pscube-viewer',version:1,records,machines: [...new Set(records.map(r=>r.machine))].map(machine=>({
  store:'c740601',rate:'20',machine,machine_type:'normal',expected_count:4,
  url:'https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/cgi-bin/nc-v05-011.php?cd_ps=2&bai=20'}))};
const meruhen={header:{format:'database-backup',version:1,source:'pc',exported_at:'2026-10-05T20:00:00+09:00'},
  records:records.map(r=>({store:'nagamachiminami',day:r.day,machine:r.machine,rack:r.rack,
    games:r.games,bb:r.bb,rb:r.rb,max_hold:r.my,
    graph_measurement:{baseline_y:100,peak_y:20,trough_y:100,end_y:40,curve:[[0,100],[10,20],[20,40]]}}))};
try {
for(const source of ['meruhen','pscube']) {
  const context=await browser.newContext({viewport:{width:393,height:852}});
  const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const baseUrl=process.env.VIEWER_PUBLIC_ORIGIN || origin;
  await page.goto(process.env.VIEWER_PUBLIC_ORIGIN ? baseUrl+prefix+'README.md' : origin+'/setup');
  await page.evaluate(async ({source,data})=>{
    const name=source==='pscube'?'database-pscube-viewer':'database-viewer',store=source==='pscube'?'state':'kv';
    const db=await new Promise((resolve,reject)=>{const q=indexedDB.open(name,1);q.onupgradeneeded=()=>q.result.createObjectStore(store);q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error)});
    await new Promise((resolve,reject)=>{const tx=db.transaction(store,'readwrite');tx.objectStore(store).put(source==='pscube'?data:JSON.stringify(data),'data');tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error)});db.close();
  },{source,data:source==='pscube'?pscube:meruhen});
  const url=baseUrl+prefix+(source==='pscube'?'pscube/':'');
  async function home(){await page.goto(url);await page.waitForSelector('flt-glass-pane',{state:'attached',timeout:60000});const p=page.locator('flt-semantics-placeholder');if(await p.count())await p.evaluate(e=>e.click());await page.getByText('database 閲覧',{exact:true}).waitFor({timeout:60000});}
  async function machine(name){await page.mouse.move(200,700);await page.mouse.wheel(0,2200);await page.waitForTimeout(300);const button=page.getByRole('button',{name:new RegExp('^'+name)}).last();await button.scrollIntoViewIfNeeded();await button.click();await page.getByText('データ表示',{exact:true}).waitFor();}
  await home();
  await page.mouse.move(200,700);await page.mouse.wheel(0,2200);await page.waitForTimeout(300);
  await page.getByText('この日の機種一覧　2機種・8台',{exact:true}).scrollIntoViewIfNeeded();
  await machine('化物語');
  await page.getByText('1085',{exact:true}).first().click();
  await page.waitForTimeout(500);
  await page.getByRole('button',{name:'前の記録日',exact:true}).click();
  await page.waitForTimeout(500);
  await page.getByRole('button',{name:'この日の「北斗」を見る',exact:true}).waitFor();
  for(const width of [320,393,768]){
    await page.setViewportSize({width,height:852});await page.waitForTimeout(250);
    await page.screenshot({path:`/tmp/viewer-replacement-${source}-${width}.png`});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'no page overflow');
  }
  await page.setViewportSize({width:393,height:852});
  await page.getByRole('button',{name:'この日の「北斗」を見る',exact:true}).click();
  await page.getByRole('button',{name:'この日の「北斗」を見る',exact:true}).waitFor({state:'hidden'});
  await page.getByRole('button',{name:/表示する日付.*2026-10-04/s}).waitFor();
  await home();await machine('マイジャグラーV');
  await page.getByRole('button',{name:'前の記録日',exact:true}).click();
  await page.getByText('1200',{exact:true}).first().click();
  await page.getByRole('button',{name:'次の記録日',exact:true}).click();
  await page.getByRole('button',{name:'この日の機種一覧を見る',exact:true}).click();
  await page.getByText('1100',{exact:true}).first().waitFor();
  assert.deepEqual(errors,[]);
  console.log(`PASS: ${source}, replacement history, relocated rack, 320/393/768px`);
  await context.close();
}
}finally {await browser.close();await new Promise(resolve=>server.close(resolve));}
