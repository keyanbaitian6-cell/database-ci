// 合成データだけで共有・iPhone用Flutter閲覧ページを確認する。実Googleには接続しない。
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const shareRoot = process.env.SHARE_WEB_ROOT || fileURLToPath(new URL('../../share_viewer/', import.meta.url));
const viewerRoot = process.env.VIEWER_WEB_ROOT || fileURLToPath(new URL('../build/web/', import.meta.url));
const fixture = JSON.parse(await fs.readFile(new URL('../test/fixtures/variety_week.json',import.meta.url),'utf8'));
const server=http.createServer(async(req,res)=>{
  const url=new URL(req.url,'http://x').pathname;
  if(url==='/setup') { res.setHeader('content-type','text/html'); res.end('<!doctype html><body>setup</body>'); return; }
  const share=url.startsWith('/share/'),prefix=share?'/share/':'/database-viewer/',root=share?shareRoot:viewerRoot;
  if(!url.startsWith(prefix)) {res.writeHead(404).end();return;}
  const file=path.resolve(root,url.slice(prefix.length)||'index.html');
  if(!file.startsWith(path.resolve(root)+path.sep)) {res.writeHead(403).end();return;}
  try { const body=await fs.readFile(file); res.setHeader('content-type',({'.html':'text/html; charset=utf-8','.mjs':'text/javascript','.js':'text/javascript','.wasm':'application/wasm','.json':'application/json','.png':'image/png'})[path.extname(file)]||'application/octet-stream'); res.end(body); }
  catch {res.writeHead(404).end();}
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const origin=`http://127.0.0.1:${server.address().port}`;
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||undefined,args:['--no-sandbox']});
try {
  for(const width of [320,393]) {
    const context=await browser.newContext({viewport:{width,height:852}});
    const posts=[],errors=[];
    await context.route('https://script.google.com/**',route=>{
      const request=route.request(),file=new URL(request.url()).searchParams.get('file')||'';
      const doc=request.method()==='POST'?(posts.push(JSON.parse(request.postData())),{ok:true}):file==='rainbow'?{marks:[]}:file==='pscube'?{format:'pscube-viewer',records:[]}:file?{events:[]}:fixture;
      return route.fulfill({status:200,contentType:'application/json',headers:{'access-control-allow-origin':'*'},body:JSON.stringify(doc)});
    });
    const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
    await context.addInitScript(()=>localStorage.setItem('database-share-variety-mode','gap')); // 旧設定でも候補を先頭に出す
    await page.goto(`${process.env.SHARE_PUBLIC_URL || origin+'/share/'}#s=AKfycbTEST${'x'.repeat(40)}`);
    await page.getByRole('button',{name:'バラエティ🌈',exact:true}).click();
    const sheet=page.locator('.sheet');
    const none=sheet.locator('[data-week-group="none"]');
    await none.waitFor();
    assert.match(await sheet.innerText(),/2026-10-07〜2026-10-13/);
    assert.match(await sheet.innerText(),/選んだ日を含む7日間/);
    assert.match(await sheet.innerText(),/候補 5台/);
    assert.deepEqual(await none.locator('.rack').allInnerTexts(),['1101番','1102番','1104番','1105番','1106番'],'選んだ日（10/13）の🌈は入り、10/6の🌈は入らない');
    assert.match(await none.getByRole('button',{name:/1102番/}).innerText(),/70点以上あり[\s\S]*最高 70.0点/);
    assert.match(await none.innerText(),/記録5\/7日・未取得2日/);
    assert.match(await none.innerText(),/記録1\/7日・未取得6日/);
    assert.equal(await sheet.locator('.week-marked').getAttribute('open'),null);
    assert.equal(await sheet.locator('[data-week-group="marked"] button').isVisible(),false);
    assert.doesNotMatch(await sheet.innerText(),/記録がない台：/);
    assert.equal(await sheet.evaluate(e=>e.scrollWidth>e.clientWidth),false);
    assert.equal(await sheet.getByRole('button',{name:'空き順',exact:true}).count(),0);
    if(process.env.WEEK_SHOTS) await page.screenshot({path:`${process.env.WEEK_SHOTS}/share-week-${width}.png`});
    await none.getByRole('button',{name:/1102番/}).click();
    await sheet.getByRole('button',{name:'1102番台の🌈 付ける'}).click();
    await page.getByRole('button',{name:'‹ 戻る'}).click();
    assert.deepEqual(await none.locator('.rack').allInnerTexts(),['1101番','1104番','1105番','1106番'],'選んだ日の🌈付け外し後に戻ると分類を更新');
    assert.ok(posts.some(p=>p.marks?.some(m=>m.rack===1102&&m.day==='2026-10-13'&&m.on)));
    await page.getByRole('button',{name:'前の日',exact:true}).click();
    assert.match(await sheet.innerText(),/2026-10-06〜2026-10-12/);
    assert.deepEqual(await none.locator('.rack').allInnerTexts(),['1102番','1103番','1104番','1105番'],'選択日を戻すと10/13の🌈は期間外、10/6の🌈を含む');
    assert.match(await sheet.innerText(),/記録がない台：1台/);
    assert.deepEqual(errors,[]);
    await context.close();
  }

  for(const width of [320,393]) {
    const context=await browser.newContext({viewport:{width,height:852}});
    const page=await context.newPage(),errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    // 公開版を確認するときも、その公開先の隔離したブラウザ領域に合成データを用意する。
    await page.goto(process.env.VIEWER_PUBLIC_URL || origin+'/setup');
    await page.evaluate(async doc=>{
      const db=await new Promise((resolve,reject)=>{const q=indexedDB.open('database-viewer',1);q.onupgradeneeded=()=>q.result.createObjectStore('kv');q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error);});
      await new Promise((resolve,reject)=>{const tx=db.transaction('kv','readwrite');tx.objectStore('kv').put(JSON.stringify(doc),'data');tx.objectStore('kv').put('meruhen','active_source');tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);});db.close();
    },fixture);
    await page.goto((process.env.VIEWER_PUBLIC_URL || origin+'/database-viewer/'));
    await page.waitForSelector('flt-glass-pane',{state:'attached',timeout:60000});
    const placeholder=page.locator('flt-semantics-placeholder');if(await placeholder.count())await placeholder.evaluate(e=>e.click());
    await page.getByText('database 閲覧',{exact:true}).waitFor({timeout:60000});
    const button=page.getByRole('button',{name:'バラエティの候補（7日間🌈なし）',exact:true});
    for(let i=0;i<30&&!await button.count();i++){await page.mouse.wheel(0,200);await page.waitForTimeout(150);}
    await button.click();
    const labels=()=>page.evaluate(()=>[...document.querySelectorAll('flt-semantics')].map(e=>e.getAttribute('aria-label')||e.textContent||''));
    const seen=async pattern=>{for(let i=0;i<60;i++){if((await labels()).some(l=>pattern.test(l)))return;await page.waitForTimeout(150);}assert.fail(`not seen: ${pattern}\n${(await labels()).join('\n')}`);};
    await seen(/2026-10-07〜2026-10-13/);
    await seen(/候補 5台/);
    await seen(/70点以上あり/);
    await seen(/最高 70.0点.*10\/13/);
    if(process.env.WEEK_SHOTS)await page.screenshot({path:`${process.env.WEEK_SHOTS}/iphone-week-${width}.png`});
    // 高得点の日の台を開き、🌈を付けて戻ったときの一覧を確認する。
    await page.getByText(/^1102番　/).first().click();
    await page.getByRole('button',{name:'🌈 付ける',exact:true}).click();
    await page.getByRole('button',{name:'🌈 外す',exact:true}).waitFor();
    await page.getByRole('button',{name:'Back',exact:true}).click();
    await page.mouse.move(width/2,700);
    await page.mouse.wheel(0,-1500);await page.waitForTimeout(300);
    await seen(/候補 4台/);
    await page.getByRole('button',{name:'前の記録日',exact:true}).click();
    await page.mouse.wheel(0,-2500);await page.waitForTimeout(300);
    await seen(/2026-10-06〜2026-10-12/);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    assert.deepEqual(errors,[]);
    await context.close();
  }
  console.log('PASS: 共有・iPhone閲覧ページの🌈なし候補が先頭、70点以上は候補のカード内、🌈あり折りたたみ、選んだ日を含む7日間、欠損、日付送り、🌈変更後の再分類、320/393px');
} finally {await browser.close();await new Promise(r=>server.close(r));}
