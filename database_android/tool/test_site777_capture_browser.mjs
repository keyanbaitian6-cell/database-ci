// 合成ページを全要求へ返す。実サイト・会員情報・実DBは使わない。
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const fixture=JSON.parse(execFileSync(process.env.PYTHON||'python',['-c',
  'import json,sys,base64;sys.path.insert(0,"tests");from smoke_site777_capture import fixture,image_bytes;print(json.dumps({"table":fixture("table",1).decode(),"graph1":fixture("graphs",1).decode(),"graph2":fixture("graphs",2).decode(),"png":base64.b64encode(image_bytes()).decode(),"background":base64.b64encode(image_bytes(True)).decode()}))'],
  {cwd:new URL('../../database/',import.meta.url),encoding:'utf8'}));
const reader=readFileSync(new URL('../../database/assets/site777_capture.js',import.meta.url),'utf8');
const source=(kind,page=1)=>`https://m.site777.jp/f/${kind}.do?pmc=04034001&urt=2000&mdc=123&dtdd=0&pan=${page}`;
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||undefined});
try {
  const page=await browser.newPage({viewport:{width:560,height:800}}),charts=[],errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',async route=>{
    const u=new URL(route.request().url());
    if(u.pathname.startsWith('/chart/')) {
      charts.push(u.searchParams.get('rack'));
      await route.fulfill({contentType:'image/png',body:Buffer.from(fixture.png,'base64')});
    } else if(u.pathname.endsWith('.png')) {
      await route.fulfill({contentType:'image/png',body:Buffer.from(fixture.background,'base64')});
    } else {
      const body=u.pathname==='/f/D2300.do'
        ?`<h2 class=page-title>Ｐ－ＳＴＡＴＩＯＮ＆ＩＩ　スロット館</h2><section id=halltop><div class="list-style mod-mt10px"><ul><li><a href="${source('D3300')}">大当り一覧</a></li></ul></div></section>`
        :u.pathname==='/f/D3300.do'?fixture.table:fixture['graph'+(u.searchParams.get('pan')||1)];
      await route.fulfill({contentType:'text/html; charset=utf-8',body});
    }
  });
  await page.goto(source('D2300'));
  await page.evaluate(reader);
  assert.ok(await page.evaluate(()=>databaseSite777.read().table_url),'機種ページのlist-style内の大当り一覧を読む');
  await page.goto(source('D3300'));
  await page.evaluate(reader);
  const table=await page.evaluate(()=>databaseSite777.read());
  assert.equal(table.rows.length,31,'非表示の重複表・平均行を含めない');
  assert.equal(table.rows[0][6],'--','ART不明を文字のまま変換側へ渡す');
  assert.equal(await page.evaluate(url=>databaseSite777.samePage(location.href,url),source('D3300')+'#scroll'),true);
  assert.equal(await page.evaluate(url=>databaseSite777.samePage(location.href,url),source('D3300',2)),false);
  for(const [number,count] of [[1,20],[2,11]]) {
    await page.goto(source('D4300',number));
    await page.evaluate(reader);
    assert.equal(await page.evaluate(()=>databaseSite777.read(true).deferred_images),true);
    await assert.rejects(page.evaluate(()=>databaseSite777.prepare(()=>true)),/停止しました/);
    await page.evaluate(()=>databaseSite777.prepare(()=>false));
    const graphs=await page.evaluate(()=>databaseSite777.read());
    assert.equal(graphs.graphs.length,count);
    assert.ok(graphs.graphs.every(g=>g.png.startsWith('data:image/png;base64,')&&g.width===260));
    if(number===1){
      await page.evaluate(()=>databaseSite777.go({type:'page',number:2}));
      assert.equal(await page.evaluate(()=>window.chosenPage),'2');
    }
  }
  assert.equal(charts.length,31);
  assert.equal(new Set(charts).size,31,'遅延画像を再取得しない');
  // 転送をネイティブ側でキャンセルしたとき、beforeunload後も停止理由を表示する。
  await page.goto(source('D3300'));
  await page.evaluate(()=>{
    window.__scopeState={enabled:true,epoch:1,day:'2026-11-06',days:['2026-11-06'],status:'準備中',ready:false};
    window.pywebview={api:{state:async()=>structuredClone(window.__scopeState)}};
  });
  await page.evaluate(readFileSync(new URL('../../database/assets/capture_card.js',import.meta.url),'utf8'));
  await page.evaluate(readFileSync(new URL('../../database/assets/site777_overlay.js',import.meta.url),'utf8'));
  await page.waitForFunction(()=>document.querySelector('#database-site777-auto')?.textContent.includes('ON'));
  await page.evaluate(()=>{
    window.dispatchEvent(new Event('beforeunload'));
    Object.assign(window.__scopeState,{enabled:false,epoch:2,status:'別店舗への移動を止めました'});
  });
  await page.waitForFunction(()=>document.querySelector('#database-site777-status')?.textContent==='別店舗への移動を止めました',{},{timeout:5000});
  assert.match(await page.locator('#database-site777-auto').innerText(),/OFF/);
  assert.deepEqual(errors,[]);
  console.log('サイトセブン：表31台・遅延グラフ20+11台・停止・番号リンク・追加取得なし：成功');
} finally {await browser.close();}
