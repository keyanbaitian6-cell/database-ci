// Build viewer_main.dart and stage_viewer.py before this browser test.
// 共有カレンダー（EVENT_CALENDAR.md、2026-10-08）：閲覧ページがApps Scriptの共有ファイルを読んで取り込み、
// 保存したイベントをPOSTで送る（合言葉なし）。スクリプトへの通信は試験の中で偽の返事に差し替える。
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
const script='https://script.google.com/macros/s/TEST_SHARED/exec';

const meruhenRecords=[];
for(const day of ['2026-10-04','2026-10-05'])
  for(let rack=1;rack<=4;rack++)meruhenRecords.push({store:'nagamachiminami',day,machine:'北斗',rack,games:3000,bb:10,rb:5,max_hold:2000});
const meruhen={header:{format:'database-backup',version:1,source:'pc',exported_at:'2026-10-05T23:00:00+09:00'},
  records:meruhenRecords,date_events:[]};
const base='https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/cgi-bin/';
const pscubeRecords=[];
for(const day of ['2026-10-04','2026-10-05'])
  for(let rack=1;rack<=4;rack++)pscubeRecords.push({store:'c740601',rate:'20',machine:'マイジャグラーV',rack,day,
    bb:rack*2,rb:rack,games:3000,my:rack*500,at_art:0,net_medals:rack*100-150,observed_at:'2026-10-05T23:00:00+09:00',
    detail_url:base+'nc-v06-001.php?cd_dai='+rack+'#'+day.replaceAll('-',''),
    graph:{kind:'daily',zero_y:100,points:[[0,100],[10,20],[20,40]]}});
const pscube={format:'pscube-viewer',version:1,machines:[{store:'c740601',rate:'20',machine:'マイジャグラーV',
  machine_type:'normal',expected_count:4,url:base+'nc-v05-011.php?cd_ps=2&bai=20'}],records:pscubeRecords};

const shared={
  events:{format:'database-events',version:1,kind:'meruhen',events:[
    {store:'nagamachiminami',day:'2026-10-24',name:'ほかの端末で入力',updated_at:'2026-10-08T03:00:00.000Z'}]},
  'pscube-events':{format:'database-events',version:1,kind:'pscube',events:[
    {store:'c740601',rate:'20',day:'2026-10-26',name:'共有のP’s CUBE',updated_at:'2026-10-08T03:00:00.000Z'}]},
};
const posts=[];

const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH || undefined,args:['--no-sandbox']});
const context=await browser.newContext({viewport:{width:393,height:852}});
const page=await context.newPage();
const errors=[];
const scriptRequests=[];
page.on('pageerror',e=>{errors.push(e.message);console.error('pageerror',e.message);});
await context.route('https://script.google.com/**',route=>{
  const request=route.request(), url=new URL(request.url());
  scriptRequests.push({method:request.method(),file:url.searchParams.get('file')});
  const headers={'access-control-allow-origin':'*'};
  if(request.method()==='POST'){
    posts.push(JSON.parse(request.postData()));
    return route.fulfill({status:200,contentType:'application/json',headers,body:JSON.stringify({ok:true,events:1,changed:1})});
  }
  const file=url.searchParams.get('file');
  if(file && shared[file]) return route.fulfill({status:200,contentType:'application/json',headers,body:JSON.stringify(shared[file])});
  // 閲覧用ファイルの読み込みは、この試験では使わない（見つからない返事）。
  return route.fulfill({status:200,contentType:'application/json',headers,body:JSON.stringify({error:'この試験では閲覧用ファイルを返しません。'})});
});

async function open(pathname){
  await page.goto(origin+prefix+pathname);
  await page.waitForSelector('flt-glass-pane',{state:'attached',timeout:60000});
  const placeholder=page.locator('flt-semantics-placeholder');
  if(await placeholder.count())await placeholder.evaluate(e=>e.click());
  await page.getByText('database 閲覧',{exact:true}).waitFor({timeout:60000});
}
async function labels(){
  return page.evaluate(()=>[...document.querySelectorAll('flt-semantics')].map(e=>e.getAttribute('aria-label')||e.textContent||''));
}
async function waitFor(check,what){
  for(let i=0;i<80;i++){if(await check())return;await page.waitForTimeout(250);}
  console.error('共有カレンダー試験の診断',JSON.stringify({what,scriptRequests,errors,labels:await labels(),
    remote:await page.evaluate(()=>localStorage.getItem('database-viewer-remote'))}));
  assert.fail('timed out: '+what);
}
async function stored(name,store){
  return page.evaluate(async ({name,store})=>{
    const db=await new Promise((resolve,reject)=>{const q=indexedDB.open(name,1);q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error);});
    const value=await new Promise((resolve,reject)=>{const q=db.transaction(store).objectStore(store).get('data');q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error);});
    db.close();return value;
  },{name,store});
}
// マスのキャラ誕生日（「🎂 名前…」の行、EVENT_CALENDAR.md「キャラ誕生日」）。イベント名と差枚の間に入る。
// 10月はほぼ毎日あるので、マスの文字はこの行があっても合うように比べる（2026-10-18、CIで落ちた）。
const BIRTHDAY='(?:\\s*🎂[^\\n]*)?';
// ラベルがちょうど合うマス（日付と差枚がまとまった1つの部品）の真ん中を押す。
async function clickLabel(pattern){
  const box=await page.evaluate(source=>{
    const re=new RegExp(source);
    const el=[...document.querySelectorAll('flt-semantics')].find(e=>re.test(e.getAttribute('aria-label')||e.textContent||''));
    if(!el)return null;const r=el.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};
  },pattern.source);
  assert.ok(box,'no element for '+pattern);
  await page.mouse.click(box.x,box.y);
}
// その日のマスを押す。マスの文字は日付で始まり、イベント名・誕生日・差枚が続くことがあるので、
// 文字の完全一致ではなく「先頭が日付」で探す（誕生日のある日は '21' だけのマスにならない）。
async function clickDay(day){
  await clickLabel(new RegExp(`^${day}(?:\\s|$)`));
}
async function enterName(name){
  const box=page.getByRole('textbox',{name:/イベント名（自由記入）/});
  await box.waitFor();await box.click();
  // 入力欄に入力の焦点が移ってから打つ（早すぎると最初の文字が落ちる。例：「末尾イベ」→「尾イベ」）。
  for(let i=0;i<40&&!(await page.evaluate(()=>['INPUT','TEXTAREA'].includes(document.activeElement?.tagName)));i++)await page.waitForTimeout(50);
  // それでも最初の文字が落ちることがある（2026-10-11、「半列」→「列」）。入力欄の中身が違えば消して打ち直す（3回まで）。
  for(let attempt=0;attempt<3;attempt++){
    await page.keyboard.type(name);
    for(let i=0;i<40&&(await box.inputValue().catch(()=>name))!==name;i++)await page.waitForTimeout(50);
    if((await box.inputValue().catch(()=>name))===name)break;
    await box.click();await page.keyboard.press('Control+A');await page.keyboard.press('Backspace');
    await page.waitForTimeout(200);
  }
  const save=page.getByRole('button',{name:'保存',exact:true});
  for(let i=0;i<20&&await save.isDisabled();i++)await page.waitForTimeout(100);
  await save.click();
}

try {
  await page.goto(origin+'/setup');
  await page.evaluate(async ({meruhen,pscube,script})=>{
    localStorage.setItem('database-viewer-remote',script);
    for(const [name,store,entries] of [
      ['database-viewer','kv',[['data',JSON.stringify(meruhen)],['active_source','meruhen']]],
      ['database-pscube-viewer','state',[['data',pscube],['meta',{exported_at:'2026-10-05T23:00:00+09:00'}]]],
    ]){
      const db=await new Promise((resolve,reject)=>{const q=indexedDB.open(name,1);q.onupgradeneeded=()=>q.result.createObjectStore(store);q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error);});
      await new Promise((resolve,reject)=>{const tx=db.transaction(store,'readwrite');for(const [key,value] of entries)tx.objectStore(store).put(value,key);tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);});db.close();
    }
  },{meruhen,pscube,script});

  // メルヘン：開くと共有ファイルのイベントを取り込み、端末に保存する。
  await open('');
  await waitFor(async()=>JSON.parse(await stored('database-viewer','kv')).date_events.some(e=>e.day==='2026-10-24'),'shared meruhen event stored');
  await page.getByRole('button',{name:'イベントカレンダー',exact:true}).click();
  const now=new Date();
  for(let i=(now.getFullYear()*12+now.getMonth())-(2026*12+9);i>0;i--)await page.getByRole('button',{name:'前の月',exact:true}).click();
  await waitFor(async()=>(await labels()).some(l=>/^24\s*ほかの端末で入力＊?$/.test(l)),'shared event in calendar');
  // 入力画面は開いたときの誕生日を出すので、誕生日を読み終わってから押す（CIで先に押して時間切れになった）。
  await waitFor(async()=>(await labels()).some(l=>/^7\s[\s\S]*🎂 キリト/.test(l)),'character birthdays in meruhen calendar');

  // 保存すると、端末の入力時刻つきイベントを合言葉なしでPOSTする。
  await clickDay(27);
  // 記録の無い日は誕生日の画面を挟まずにすぐ入力。その日のキャラ誕生日は入力画面に「名前（作品）」で出る。
  await waitFor(async()=>(await labels()).some(l=>/🎂 半間修二（東京リベンジャーズ）/.test(l)),'birthday in the event name dialog');
  await enterName('iPhoneで入力');
  await waitFor(async()=>posts.length>0,'meruhen POST');
  assert.equal(posts[0].file,'events');
  assert.equal('key' in posts[0],false,'no passphrase');
  const days=posts[0].events.map(e=>e.day);
  assert.ok(days.includes('2026-10-27') && days.includes('2026-10-24'));
  assert.ok(posts[0].events.every(e=>typeof e.updated_at==='string'));
  await waitFor(async()=>(await labels()).some(l=>/共有カレンダーに送りました/.test(l)),'sent notice');

  // P’s CUBE：その日のイベントを保存すると pscube-events で送り、共有ファイルの分も取り込む。
  await open('pscube/');
  await waitFor(async()=>((await stored('database-pscube-viewer','state')).date_events||[]).some(e=>e.day==='2026-10-26'),'shared pscube event stored');
  await page.getByRole('button',{name:/イベント：なし（編集）/}).click();
  await enterName('末尾イベ');
  // 送信が届く順は決まっていないので、最初の1件ではなく「末尾イベ」を含む送信を探す（2026-10-11、たまに失敗した）。
  const isSuffix=p=>p.file==='pscube-events' && p.events.some(e=>e.name==='末尾イベ' && e.rate==='20');
  await waitFor(async()=>posts.some(isSuffix),'pscube POST');
  const pscubePost=posts.find(isSuffix);
  assert.ok(pscubePost.events.some(e=>e.day==='2026-10-26'));

  // P’s CUBEのイベントカレンダー（2026-10-08）：各日に総差枚（4台で -50+50+150+250 = +400）、先の日にも入れて送る。
  await page.getByRole('button',{name:'イベントカレンダー',exact:true}).click();
  for(let i=(now.getFullYear()*12+now.getMonth())-(2026*12+9);i>0;i--)await page.getByRole('button',{name:'前の月',exact:true}).click();
  // 誕生日はアセットから後で読む。読み終わってから押す（読み終わる前のマスを押す前に文字が変わり、押せなかった）。
  await waitFor(async()=>(await labels()).some(l=>/^7\s[\s\S]*🎂 キリト/.test(l)),'character birthdays in calendar');
  const day4=new RegExp(`^4${BIRTHDAY}\\s*\\+400$`);
  await waitFor(async()=>(await labels()).some(l=>day4.test(l)),'pscube daily net in calendar');
  await waitFor(async()=>(await labels()).some(l=>new RegExp(`^5\\s*末尾イベ＊${BIRTHDAY}\\s*\\+400$`).test(l)),'event and net in one day');
  await waitFor(async()=>(await labels()).some(l=>/^26\s*共有のP’s CUBE/.test(l)),'shared pscube event in calendar');
  await waitFor(async()=>(await labels()).some(l=>/元グラフの差枚がわかった台の合計/.test(l)),'net note');
  // 記録のある日を押すと、その日のTOP10（差枚の多い順）と強かった機種5選（2026-10-09）。
  await clickLabel(day4);
  await waitFor(async()=>(await labels()).some(l=>/TOP10（差枚の多い順）/.test(l)),'day summary');
  await waitFor(async()=>(await labels()).some(l=>/🎂 シリカ（ソードアート・オンライン）/.test(l)),'birthday in the day summary');
  await waitFor(async()=>(await labels()).some(l=>/^1\s*4番\s*マイジャグラーV/.test(l)),'top rack');
  await waitFor(async()=>(await labels()).some(l=>/強かった機種5選/.test(l)),'strong machines');
  await page.getByRole('button',{name:/^(Back|戻る)$/}).click();
  await waitFor(async()=>(await labels()).some(l=>day4.test(l)),'back to calendar');
  const before=posts.length;
  await clickDay(28);
  await enterName('先の日イベ');
  // 前の操作の送信が後から届くことがあるので、最後の1件ではなく、保存後に届いた送信から探す（2026-10-11、たまに失敗した）。
  const isFuture=p=>p.file==='pscube-events' && p.events.some(e=>e.day==='2026-10-28' && e.name==='先の日イベ' && e.rate==='20');
  await waitFor(async()=>posts.slice(before).some(isFuture),'pscube calendar POST');
  assert.ok(posts.slice(before).some(isFuture),'記録の無い先の日にも入る');
  const saved=(await stored('database-pscube-viewer','state')).date_events;
  assert.ok(saved.some(e=>e.day==='2026-10-28' && e.name==='先の日イベ'));
  assert.deepEqual(errors,[]);
  console.log('PASS: shared calendar pull (meruhen, pscube), POST without passphrase on save, pscube calendar with daily net');
} finally {
  await browser.close();
  await new Promise(resolve=>server.close(resolve));
}
