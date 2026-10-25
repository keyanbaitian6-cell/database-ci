// 合成データ・模擬Googleだけで本日の未取得台への🌈を両Web版で検証する。
import assert from 'node:assert/strict';
import test from 'node:test';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const roots = {
  share: process.env.SHARE_WEB_ROOT || fileURLToPath(new URL('../../share_viewer/', import.meta.url)),
  viewer: process.env.VIEWER_WEB_ROOT || fileURLToPath(new URL('../build/web/', import.meta.url)),
};
const fixture = JSON.parse(await fs.readFile(new URL('../test/fixtures/variety_week.json', import.meta.url), 'utf8'));
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://x').pathname;
  if (url === '/setup') {res.setHeader('content-type', 'text/html');res.end('<!doctype html><body>setup</body>');return;}
  const share = url.startsWith('/share/'), prefix = share ? '/share/' : '/database-viewer/', root = share ? roots.share : roots.viewer;
  if (!url.startsWith(prefix)) {res.writeHead(404).end();return;}
  const file = path.resolve(root, url.slice(prefix.length) || 'index.html');
  if (!file.startsWith(path.resolve(root) + path.sep)) {res.writeHead(403).end();return;}
  try {
    const body = await fs.readFile(file);
    res.setHeader('content-type', ({'.html':'text/html; charset=utf-8','.mjs':'text/javascript','.js':'text/javascript','.css':'text/css','.wasm':'application/wasm','.json':'application/json','.png':'image/png'})[path.extname(file)] || 'application/octet-stream');
    res.end(body);
  } catch {res.writeHead(404).end();}
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const origin = `http://127.0.0.1:${server.address().port}`;
const script = `https://script.google.com/macros/s/AKfycbTEST${'x'.repeat(40)}/exec`;
const browser = await chromium.launch({headless:true, executablePath:process.env.CHROMIUM_PATH || undefined, args:['--no-sandbox']});
try {
  for (const kind of ['share', 'viewer']) for (const width of [320,393]) await test(`${kind}: 本日の🌈・${width}px`, async t => {
    const context = await browser.newContext({viewport:{width,height:852}});
    t.after(() => context.close());
    const page = await context.newPage(), posts = [], errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.clock.setFixedTime(new Date('2026-10-14T04:00:00Z'));
    let doc = structuredClone(fixture), failPosts = false;
    // 別端末で付けた未取得日の印も最初から見える。
    const marks = [{store:'saiwaichou',day:'2026-10-14',rack:1102,on:true,updated_at:'2026-10-14T03:00:00Z'}];
    // 閲覧ページは最初の🌈を2秒遅らせて返す。本日の一覧を開いたあとに届いても表示に出ること
    // （2026-10-25、CIの混雑でこの順になり、開いたままの画面に反映されず落ちていた）。
    let delayRainbow = kind === 'viewer';
    await context.route('https://script.google.com/**', async route => {
      const request = route.request(), file = new URL(request.url()).searchParams.get('file') || '';
      if (file === 'rainbow' && delayRainbow) {delayRainbow = false;await new Promise(r => setTimeout(r, 2000));}
      const body = request.method() === 'POST' ? (posts.push(JSON.parse(request.postData())), failPosts ? {error:'試験の送信失敗'} : {ok:true})
        : file === 'rainbow' ? {format:'database-rainbow',marks} : file === 'pscube' ? {format:'pscube-viewer',records:[]} : file ? {events:[]}
          : {format:'database-backup',version:1,source:'pc',exported_at:doc.header?.exported_at,records:doc.records};
      return route.fulfill({status:200,contentType:'application/json',headers:{'access-control-allow-origin':'*'},body:JSON.stringify(body)});
    });
    const url = kind === 'share' ? `${process.env.SHARE_PUBLIC_URL || origin+'/share/'}#s=${script.split('/')[5]}`
      : process.env.VIEWER_PUBLIC_URL || origin+'/database-viewer/';
    if (kind === 'viewer') {
      await page.goto(process.env.VIEWER_PUBLIC_URL || origin+'/setup');
      await page.evaluate(async ({doc,script}) => {
        localStorage.setItem('database-viewer-remote', script);
        const db = await new Promise((resolve,reject) => {const q=indexedDB.open('database-viewer',1);q.onupgradeneeded=()=>q.result.createObjectStore('kv');q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error);});
        await new Promise((resolve,reject) => {const tx=db.transaction('kv','readwrite');tx.objectStore('kv').put(JSON.stringify(doc),'data');tx.objectStore('kv').put('meruhen','active_source');tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);});db.close();
      }, {doc,script});
    }
    const openToday = async ({refresh = false} = {}) => {
      await page.goto('about:blank');
      await page.goto(url);
      if (kind === 'share') {
        if (refresh) {
          await page.locator('#reload').waitFor({state:'visible'});
          await page.locator('#reload').click();
          await page.waitForFunction(() => !document.querySelector('#reload').disabled);
        }
        await page.getByRole('button',{name:'バラエティ🌈',exact:true}).click();
      } else {
        await page.waitForSelector('flt-glass-pane',{state:'attached',timeout:60000});
        const p=page.locator('flt-semantics-placeholder');if(await p.count())await p.evaluate(e=>e.click());
        await page.getByText('database 閲覧',{exact:true}).waitFor({timeout:60000});
        const button=page.getByRole('button',{name:'バラエティの候補（7日間🌈なし）',exact:true});
        for(let i=0;i<30&&!await button.count();i++){await page.mouse.wheel(0,200);await page.waitForTimeout(150);}
        await button.click();
      }
      if (kind === 'viewer') {
        const chip = page.getByRole('checkbox', {name:'本日',exact:true});
        await chip.click();
      } else await page.getByText('本日',{exact:true}).click();
      await page.getByText('本日 2026-10-14',{exact:true}).waitFor();
    };
    const toggle = (label) => kind === 'share' ? page.getByRole('button',{name:`1101番台の🌈 ${label}`,exact:true})
      : page.getByRole('button',{name:`🌈 ${label}`,exact:true}).first();
    const seen = async text => {
      for (let i=0;i<80;i++) {
        const found = kind === 'viewer' ? await page.locator('flt-semantics').evaluateAll((es,text)=>es.some(e=>(e.getAttribute('aria-label')||e.textContent||'').includes(text)),text)
          : await page.getByText(text,{exact:true}).count();
        if(found)return;await page.waitForTimeout(100);
      }
      assert.fail(`表示されない: ${text}`);
    };
    await openToday();
    await seen('本日の🌈 1台');
    await seen('本日分 未取得');
    await toggle('付ける').click();
    await seen('本日の🌈 2台');
    for(let i=0;i<60&&!posts.some(p=>p.marks.some(m=>m.rack===1101&&m.day==='2026-10-14'&&m.on));i++)await page.waitForTimeout(100);
    assert.ok(posts.some(p=>p.marks.some(m=>m.rack===1101&&m.day==='2026-10-14'&&m.on)));
    if(process.env.TODAY_SHOTS)await page.screenshot({path:`${process.env.TODAY_SHOTS}/${kind}-today-${width}.png`});
    await openToday();
    await seen('本日の🌈 2台');
    // データ取得後も引き継ぐ（未取得の0行や過去の数値を保存していない）。
    doc.records.push({...fixture.records.find(r=>r.rack===1101),day:'2026-10-14',games:4567,rainbow:false,rainbow_at:null});
    doc.header = {...doc.header,exported_at:'2026-10-14T05:00:00Z'};
    await openToday({refresh:true});
    await seen('本日の🌈 2台');
    await seen('本日分 取り込み済み');
    failPosts = true;
    await toggle('外す').click();
    await seen('本日の🌈 1台');
    await openToday();
    await seen('本日の🌈 1台');
    if(kind==='viewer') {
      const stored=await page.evaluate(async()=>{
        const db=await new Promise(r=>{const q=indexedDB.open('database-viewer',1);q.onsuccess=()=>r(q.result);});
        const result=await new Promise(r=>{const q=db.transaction('kv').objectStore('kv').get('data');q.onsuccess=()=>r(q.result);});db.close();return JSON.parse(result);
      });
      assert.equal(stored.records.filter(r=>r.day==='2026-10-14').length,1);
      assert.equal(stored.records.find(r=>r.day==='2026-10-14').games,4567);
      assert.equal(stored.rainbow_marks.find(m=>m.rack===1101&&m.day==='2026-10-14').on,false);
    }
    if(kind==='share') {
      const beforeFailure=posts.length;
      await page.evaluate(()=>{
        window.restoreStorageSet=Storage.prototype.setItem;
        Storage.prototype.setItem=function(key,value){if(key==='database-share-rainbow')throw new Error('quota');return window.restoreStorageSet.call(this,key,value);};
      });
      await toggle('付ける').click();
      await seen('本日の🌈 1台');
      assert.equal(posts.length,beforeFailure,'端末保存失敗を成功として送らない');
      assert.match(await page.locator('.toast').innerText(),/この端末に保存できませんでした/);
      await page.evaluate(()=>Storage.prototype.setItem=window.restoreStorageSet);
    }
    const before=posts.length;
    await page.clock.setFixedTime(new Date('2026-10-14T15:00:01Z'));
    await toggle('付ける').click();
    await seen('本日 2026-10-15');
    assert.equal(posts.length,before,'日付跨ぎの最初のクリックは保存しない');
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    assert.deepEqual(errors,[]);
  });
} finally {await browser.close();await new Promise(r=>server.close(r));}
