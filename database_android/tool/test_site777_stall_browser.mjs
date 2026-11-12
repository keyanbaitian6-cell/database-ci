// 外部要求は全て合成応答へ置換。実サイト・本番DBを使わず画像待ちの再発を検出する。
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {readFileSync,existsSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
const venv=new URL('../../database/.venv/Scripts/python.exe',import.meta.url);
const python=process.env.PYTHON||(existsSync(venv)?fileURLToPath(venv):'python');
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const fixture=JSON.parse(execFileSync(python,['-c',
  'import json,sys,base64;sys.path.insert(0,"tests");from smoke_site777_capture import fixture,image_bytes;print(json.dumps({"html":fixture("graphs",1).decode(),"png":base64.b64encode(image_bytes()).decode(),"background":base64.b64encode(image_bytes(True)).decode()}))'],
  {cwd:new URL('../../database/',import.meta.url),encoding:'utf8'}));
const script=name=>readFileSync(new URL('../../database/assets/'+name,import.meta.url),'utf8');
const source='https://m.site777.jp/f/D4300.do?pmc=04034001&urt=2000&mdc=123&dtdd=0&pan=1';
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||undefined});
const errors=[];
async function setup(){
  const page=await browser.newPage({viewport:{width:560,height:800}}),requests=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',async route=>{
    const u=new URL(route.request().url());requests.push(u.pathname+u.search);
    if(u.pathname.startsWith('/chart/'))await route.fulfill({contentType:'image/png',body:Buffer.from(fixture.png,'base64')});
    else if(u.pathname.endsWith('.png'))await route.fulfill({contentType:'image/png',body:Buffer.from(fixture.background,'base64')});
    else if(route.request().isNavigationRequest())await route.fulfill({contentType:'text/html; charset=utf-8',
      body:fixture.html.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'')});
    else await route.abort();
  });
  await page.goto(source);await page.evaluate(script('site777_capture.js'));
  await page.evaluate(()=>{window.__site777GraphWaitMs=300;window.__site777RetryMs=1200;
    window.setChart=(rack,replace=false)=>{
      const box=[...document.querySelectorAll('.graph-box')].find(b=>b.querySelector('span')?.textContent===`[${rack}]`);
      let img=box.querySelector('img');
      if(replace){const fresh=img.cloneNode();img.replaceWith(fresh);img=fresh;}
      img.src=`/chart/RequestSPDedamaTransitionChartForPortal.do?rack=${rack}`;
    };});
  return {page,requests};
}
async function overlay(page,mode){
  await page.evaluate(mode=>{
    window.__mode=mode;window.__calls=[];window.__staged=[];window.__paused=[];window.__wait=false;
    window.__s={enabled:true,epoch:1,ready:true,day:'2026-11-06',days:['2026-11-06'],status:'開始'};
    if(mode==='recover_more'){
      const box=[...document.querySelectorAll('.graph-box')].find(b=>b.querySelector('span')?.textContent==='[103]');
      const scroll=box.scrollIntoView.bind(box);
      box.scrollIntoView=options=>{scroll(options);window.setChart(103);};
    }
    sessionStorage.setItem('database-site777-retries',JSON.stringify({[location.href]:2}));
    window.pywebview={api:{state:async()=>structuredClone(window.__s),save_overlay_layout:async()=>{},
      capture:async(raw,epoch)=>{
        const p=JSON.parse(raw);window.__calls.push({partial:!!p.partial_graphs,meta:!!p.deferred_images,racks:p.graphs?.map(g=>g.rack),epoch});
        if(p.deferred_images)return {prepare_graphs:true,wanted_racks:(mode==='recover_more'?[101,102,103]:[101,102]).filter(r=>!window.__staged.includes(r))};
        if(p.partial_graphs){
          if(window.__mode==='save_error'){Object.assign(window.__s,{enabled:false,ready:false,status:'保存の失敗'});
            return {error:'保存の失敗',state:structuredClone(window.__s)};}
          window.__staged.push(...p.graphs.map(g=>g.rack));return {partial_saved:true,state:structuredClone(window.__s)};
        }
        Object.assign(window.__s,{enabled:false,ready:false,status:'完了'});return {state:structuredClone(window.__s)};
      },
      note:async()=>{window.__wait=true;if(window.__mode.startsWith('recover'))setTimeout(()=>window.setChart(102,true),650);},
      pause:async(message,reason)=>{window.__paused.push(reason);Object.assign(window.__s,{enabled:false,epoch:2,status:message||'停止'});
        return structuredClone(window.__s);}}};
  },mode);
  await page.evaluate(script('capture_card.js'));await page.evaluate(script('site777_overlay.js'));
}
try{
  // 画像・親boxが丸ごと置き換わっても、同じ台の現在の要素を待つ。
  for(const replaceBox of [false,true]){
    const {page,requests}=await setup();
    await page.evaluate(()=>{window.__site777GraphWaitMs=1500;});
    await page.evaluate(async replaceBox=>{
      setTimeout(()=>{
        if(replaceBox){const box=document.querySelector('.graph-box');box.replaceWith(box.cloneNode(true));}
        window.setChart(101,true);
      },150);
      await databaseSite777.prepare(()=>false,[101]);
    },replaceBox);
    assert.deepEqual(await page.evaluate(()=>databaseSite777.read(false,[101]).graphs.map(g=>g.rack)),[101]);
    assert.equal(requests.filter(r=>r.startsWith('/chart/')).length,1);
    await page.close();
  }
  // 先に読めた101だけ途中保存、102は待機中に回復。再読込回数を消費せず、既読画像を再送しない。
  for(const mode of ['recover','recover_more']){
    const {page,requests}=await setup();await page.evaluate(()=>window.setChart(101));
    await page.waitForFunction(()=>document.querySelector('.graph-box img').complete);
    await overlay(page,mode);
    await page.waitForFunction(()=>window.__s.status==='完了',{},{timeout:10000});
    const got=await page.evaluate(()=>({calls:__calls,staged:__staged,paused:__paused,retries:JSON.parse(sessionStorage.getItem('database-site777-retries'))[location.href]}));
    assert.deepEqual(got.staged,[101]);assert.deepEqual(got.paused,[]);assert.equal(got.retries,2);
    assert.deepEqual(got.calls.filter(c=>!c.meta).map(c=>[c.partial,c.racks]),[[true,[101]],[false,mode==='recover_more'?[102,103]:[102]]]);
    assert.equal(requests.filter(r=>r.startsWith('/f/D4300.do?')).length,1,'回復したページを読み込み直さない');
    assert.equal(requests.filter(r=>r.startsWith('/chart/')).length,mode==='recover_more'?3:2,'画像ごとにサイト自身の1回だけ');
    await page.close();
  }
  // 待機中の停止では回復確認やreloadを続けず、再試行回数も変更しない。
  {
    const {page,requests}=await setup();await overlay(page,'stop');
    await page.waitForFunction(()=>window.__wait);
    await page.click('#database-site777-auto');await page.waitForTimeout(1800);
    assert.deepEqual(await page.evaluate(()=>__paused),['user_stop']);
    assert.equal(requests.filter(r=>r.startsWith('/f/D4300.do?')).length,1);
    assert.equal(await page.evaluate(()=>JSON.parse(sessionStorage.getItem('database-site777-retries'))[location.href]),2);
    assert.equal(await page.evaluate(()=>__calls.filter(c=>!c.meta).length),0);
    await page.close();
  }
  // 途中保存そのものが失敗したら、その停止理由をグラフ待ちで上書きしない。
  {
    const {page,requests}=await setup();await page.evaluate(()=>window.setChart(101));
    await page.waitForFunction(()=>document.querySelector('.graph-box img').complete);
    await overlay(page,'save_error');await page.waitForFunction(()=>__s.status==='保存の失敗');
    await page.waitForTimeout(1600);
    assert.deepEqual(await page.evaluate(()=>__paused),[]);
    assert.equal(requests.filter(r=>r.startsWith('/f/D4300.do?')).length,1);
    await page.close();
  }
  assert.deepEqual(errors,[]);
  console.log('サイトセブン：画像と親要素の置換、成功分の途中保存、待機中の回復、余計な再取得なし、停止と保存失敗の保護：成功');
}finally{await browser.close();}
