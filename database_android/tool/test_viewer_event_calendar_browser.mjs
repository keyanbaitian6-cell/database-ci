// Build viewer_main.dart and stage_viewer.py before this browser test.
// イベントカレンダー（EVENT_CALENDAR.md、2026-10-07）と、メルヘンの「日別の差枚（推定）」に
// イベント名が出ること（86eb7f8 で一度消えた不具合の再発確認も兼ねる）。
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
// VIEWER_PUBLIC_ORIGIN を渡すと、公開URL（例 https://keyanbaitian6-cell.github.io）で試す。
const baseUrl=process.env.VIEWER_PUBLIC_ORIGIN || origin;

const records=[];
for(const day of ['2026-10-01','2026-10-02','2026-10-03','2026-10-04','2026-10-05'])
  for(let rack=1;rack<=4;rack++)records.push({store:'nagamachiminami',day,machine:'北斗',rack,
    games:3000,bb:10+rack,rb:5,max_hold:2000+rack*100,
    graph_measurement:{baseline_y:100,peak_y:20,trough_y:100,end_y:40,curve:[[0,100],[10,20],[20,40]]}});
const meruhen={header:{format:'database-backup',version:1,source:'pc',exported_at:'2026-10-05T23:00:00+09:00'},
  records,
  date_events:[
    // 時刻の無い以前のイベント・前日までに入力・当日以降に入力・消した印・先の日。
    {store:'nagamachiminami',day:'2026-10-03',name:'半列'},
    {store:'nagamachiminami',day:'2026-10-04',name:'4台構成',updated_at:'2026-10-03T21:00:00+09:00'},
    {store:'nagamachiminami',day:'2026-10-05',name:'コンパス導入',updated_at:'2026-10-05T12:00:00+09:00'},
    {store:'nagamachiminami',day:'2026-10-02',name:null,updated_at:'2026-10-03T21:00:00+09:00'},
    {store:'nagamachiminami',day:'2026-10-20',name:'超探す楽しみ',updated_at:'2026-10-07T22:00:00+09:00'},
    {store:'saiwaichou',day:'2026-10-04',name:'他店舗のイベント',updated_at:'2026-10-03T21:00:00+09:00'},
  ]};

const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH || undefined,args:['--no-sandbox']});
const context=await browser.newContext({viewport:{width:393,height:852},acceptDownloads:true});
const page=await context.newPage();
const errors=[];
page.on('pageerror',e=>{errors.push(e.message);console.error('pageerror',e.message);});

async function home(){
  await page.goto(baseUrl+prefix);
  await page.waitForSelector('flt-glass-pane',{state:'attached',timeout:60000});
  const placeholder=page.locator('flt-semantics-placeholder');
  if(await placeholder.count())await placeholder.evaluate(e=>e.click());
  await page.getByText('database 閲覧',{exact:true}).waitFor({timeout:60000});
}
// 画面の読み上げ情報（Flutterは日付と名前を1つのまとまりにする）に [pattern] があるか。
async function seen(pattern){
  const labels=await page.evaluate(()=>[...document.querySelectorAll('flt-semantics')]
    .map(e=>e.getAttribute('aria-label')||e.textContent||''));
  return labels.some(label=>pattern.test(label));
}
async function waitSeen(pattern){
  for(let i=0;i<60;i++){if(await seen(pattern))return;await page.waitForTimeout(250);}
  assert.fail(`not shown: ${pattern}`);
}
// 名前を入れて保存する。Flutterの入力欄は、まとめて流し込むより実際のキー入力の方が確実。
async function enterName(name){
  const box=page.getByRole('textbox',{name:/イベント名（自由記入）/});
  await box.waitFor();await box.click();
  // 入力欄に入力の焦点が移ってから打つ（早すぎると最初の文字が落ちる。例：「末尾イベ」→「尾イベ」）。
  for(let i=0;i<40&&!(await page.evaluate(()=>['INPUT','TEXTAREA'].includes(document.activeElement?.tagName)));i++)await page.waitForTimeout(50);
  await page.keyboard.type(name);
  for(let i=0;i<40&&(await box.inputValue().catch(()=>name))!==name;i++)await page.waitForTimeout(50);
  const save=page.getByRole('button',{name:'保存',exact:true});
  for(let i=0;i<20&&await save.isDisabled();i++)await page.waitForTimeout(100);
  await save.click();
}
async function waitFor(check,what){
  for(let i=0;i<80;i++){if(await check())return;await page.waitForTimeout(250);}
  assert.fail('timed out: '+what);
}
async function storedEvents(){
  return JSON.parse(await page.evaluate(()=>window.databaseViewer.load())).date_events;
}
async function dailyNet(){
  await page.getByRole('button',{name:'日別の差枚（推定）',exact:true}).click();
  await page.getByText(/2026年10月のデータ/).first().waitFor();
}
async function calendarOctober(){
  await page.getByRole('button',{name:'イベントカレンダー',exact:true}).click();
  const now=new Date();
  for(let i=(now.getFullYear()*12+now.getMonth())-(2026*12+9);i>0;i--)
    await page.getByRole('button',{name:'前の月',exact:true}).click();
  for(let i=(now.getFullYear()*12+now.getMonth())-(2026*12+9);i<0;i++)
    await page.getByRole('button',{name:'次の月',exact:true}).click();
  await waitSeen(/2026年10月/);
}
async function back(){
  await page.getByRole('button',{name:'Back'}).or(page.getByRole('button',{name:'戻る'})).first().click();
}

try {
  await page.goto(process.env.VIEWER_PUBLIC_ORIGIN ? baseUrl+prefix+'README.md' : origin+'/setup');
  await page.evaluate(async data=>{
    const db=await new Promise((resolve,reject)=>{const q=indexedDB.open('database-viewer',1);q.onupgradeneeded=()=>q.result.createObjectStore('kv');q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error);});
    await new Promise((resolve,reject)=>{const tx=db.transaction('kv','readwrite');tx.objectStore('kv').put(JSON.stringify(data),'data');tx.objectStore('kv').put('meruhen','active_source');tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);});db.close();
  },meruhen);
  await home();

  // 日別の差枚（推定）：時刻の有無にかかわらずイベント名が出る。消した日・他店舗は出ない。
  await dailyNet();
  for(const [day,name] of [['10/3（土）','半列'],['10/4（日）','4台構成'],['10/5（月）','コンパス導入']])
    assert.ok(await seen(new RegExp(`^${day}\\s*${name}$`)),`daily net shows ${name} under ${day}`);
  assert.ok(await seen(/^10\/2（金）$/),'the removed day has no name');
  assert.equal(await seen(/他店舗のイベント/),false);
  await page.screenshot({path:'/tmp/viewer-event-daily-net.png'});
  await back();

  // カレンダー：前日までに入力した日は印なし、当日以降・時刻不明は＊、先の日も出る。
  await calendarOctober();
  for(const [day,label] of [['3','半列＊'],['4','4台構成'],['5','コンパス導入＊'],['20','超探す楽しみ']])
    assert.ok(await seen(new RegExp(`^${day}\\s*${label}$`)),`calendar shows ${label} on ${day}`);
  assert.ok(await seen(/^2$/),'the removed day has no name');
  assert.equal(await seen(/他店舗のイベント/),false);
  for(const width of [320,393,768]){
    await page.setViewportSize({width,height:852});await page.waitForTimeout(250);
    await page.screenshot({path:`/tmp/viewer-event-calendar-${width}.png`});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'no page overflow');
  }
  await page.setViewportSize({width:393,height:852});

  // 先の日に入れる：自由記入で保存すると、その時刻（前日まで）で端末に残る。
  await page.getByText('25',{exact:true}).first().click();
  await enterName('周年');
  await page.waitForTimeout(500);
  assert.ok(await seen(/^25\s*周年$/),'saved name is shown with no late mark');
  const saved=(await storedEvents()).find(e=>e.day==='2026-10-25');
  assert.equal(saved.name,'周年');
  assert.ok(Date.parse(saved.updated_at)<Date.parse('2026-10-25T02:00:00+09:00'));

  // 期間でまとめて入力：10/21〜10/22 に同じ名前。
  await page.getByRole('switch',{name:/期間でまとめて入力/}).or(page.getByRole('checkbox',{name:/期間でまとめて入力/})).first().click();
  await page.getByText('21',{exact:true}).first().click();
  await page.getByText('22',{exact:true}).first().click();
  await enterName('半列');
  await page.waitForTimeout(500);
  const ranged=(await storedEvents()).filter(e=>e.day==='2026-10-21'||e.day==='2026-10-22');
  assert.deepEqual(ranged.map(e=>e.name),['半列','半列']);

  // 消す：10/03 の「半列」をイベントなしにすると、日別の差枚からも消え、消した印が残る。
  // 記録のある日は、押すとその日のまとめ（TOP10・強かった機種5選、2026-10-09）が開き、そこから編集する。
  await page.getByText(/^3\s*半列＊$/).first().click();
  await page.getByRole('button',{name:'イベントを編集',exact:true}).waitFor({timeout:20000});
  await waitFor(async()=>(await page.getByText(/強かった機種5選/).count())>0,'day summary');
  await page.getByRole('button',{name:'イベントを編集',exact:true}).click();
  await page.getByRole('button',{name:'イベントなしにする',exact:true}).click();
  await page.getByRole('button',{name:'Back'}).or(page.getByRole('button',{name:'戻る'})).first().click();
  await page.waitForTimeout(500);
  const removed=(await storedEvents()).find(e=>e.day==='2026-10-03');
  assert.equal(removed.name,null);
  assert.ok(removed.updated_at);

  // 書き出し：イベントだけのファイル（台の記録は空）。
  const [download]=await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button',{name:'イベントを書き出す',exact:true}).click(),
  ]);
  assert.match(download.suggestedFilename(),/^database-backup-browser-events-\d{8}-\d{6}\.json$/);
  const exported=JSON.parse(await fs.readFile(await download.path(),'utf8'));
  assert.equal(exported.format,'database-backup');
  assert.deepEqual(exported.records,[]);
  assert.ok(exported.date_events.some(e=>e.day==='2026-10-25'&&e.name==='周年'));
  assert.ok(exported.date_events.some(e=>e.day==='2026-10-03'&&e.name===null));

  // 読み込み直しても残り、日別の差枚に反映されている。
  await home();
  await dailyNet();
  for(const [day,name] of [['10/4（日）','4台構成'],['10/5（月）','コンパス導入']])
    assert.ok(await seen(new RegExp(`^${day}\\s*${name}$`)),`after reload daily net shows ${name}`);
  assert.ok(await seen(/^10\/3（土）$/),'removed event is gone');
  assert.deepEqual(errors,[]);
  console.log('PASS: meruhen daily net events, event calendar (marks, future day, range, remove, export), 320/393/768px');
} finally {
  await browser.close();
  await new Promise(resolve=>server.close(resolve));
}
