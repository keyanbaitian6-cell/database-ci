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
      // 本物の機種一覧と同じ形：台数は「名前 [31]」、1台の機種は角かっこ無しの名前だけ（2026-11-07）。
      const index=`<h2 class=page-title>Ｐ－ＳＴＡＴＩＯＮ＆ＩＩ　スロット館</h2>`+
        [['120141','ゴーゴージャグラー３ [31]'],['120406','L牙狼 闇を照らす者'],['120500','試験機種 [不明]']].map(([m,label])=>
          `<a href="D2300.do?pmc=04034001&amp;clc=03&amp;urt=2000&amp;mdc=${m}&amp;bn=1" class="imageSet"><div class="icon-kisyu"></div><strong>${label}</strong></a>`).join('');
      const body=u.pathname==='/f/D0300.do'?index:u.pathname==='/f/D2300.do'
        ?`<h2 class=page-title>Ｐ－ＳＴＡＴＩＯＮ＆ＩＩ　スロット館</h2><section id=halltop><div class="list-style mod-mt10px"><ul><li><a href="${source('D3300')}">大当り一覧</a></li></ul></div></section>`
        :u.pathname==='/f/D3300.do'?fixture.table:fixture['graph'+(u.searchParams.get('pan')||1)];
      await route.fulfill({contentType:'text/html; charset=utf-8',body});
    }
  });
  await page.goto('https://m.site777.jp/f/D0300.do?pmc=04034001&clc=03&urt=2000&pan=1');
  await page.evaluate(reader);
  assert.deepEqual(await page.evaluate(()=>databaseSite777.read().machines.map(m=>[m.name,m.count])),
    [['ゴーゴージャグラー3',31],['L牙狼 闇を照らす者',1],['試験機種 [不明]',null]],'角かっこ無しは1台、読めない角かっこは不明');
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
  // 日付の範囲（2026-11-07）：「まで」を選ぶと始まり・終わりを渡し、開始でも同じ範囲を渡す。進み具合を出す。
  await page.evaluate(()=>{
    window.__configured=[];
    Object.assign(window.__scopeState,{enabled:false,epoch:3,day:'2026-11-06',days:['2026-11-06','2026-11-05','2026-11-04'],status:'停止しました。'});
    window.pywebview.api.configure=async(enabled,day,until)=>{
      window.__configured.push([enabled,day,until]);
      const first=until&&until<day?until:day;
      Object.assign(window.__scopeState,{enabled,day:first,until:until?(until>day?until:day):null,
        queue:until?['2026-11-05','2026-11-06'].filter(d=>d>first):[],finished_days:enabled?['11/04（追加3台・既存0台・グラフ不明0台）']:[]});
      return structuredClone(window.__scopeState);
    };
  });
  await page.waitForFunction(()=>document.querySelector('#database-site777-until')?.options.length===3);
  assert.equal(await page.inputValue('#database-site777-until'),'2026-11-06','初めは1日だけ（始まりと同じ日）');
  await page.selectOption('#database-site777-until','2026-11-04');
  await page.waitForFunction(()=>window.__configured.length===1);
  assert.deepEqual(await page.evaluate(()=>window.__configured[0]),[false,'2026-11-06','2026-11-04']);
  await page.waitForFunction(()=>document.querySelector('#database-site777-day').value==='2026-11-04');
  assert.equal(await page.inputValue('#database-site777-until'),'2026-11-06');
  await page.click('#database-site777-auto');
  await page.waitForFunction(()=>window.__configured.length===2);
  assert.deepEqual(await page.evaluate(()=>window.__configured[1]),[true,'2026-11-04','2026-11-06']);
  await page.waitForFunction(()=>document.querySelector('#database-site777-range')?.textContent.includes('この後：2026-11-05、2026-11-06'));
  assert.equal(await page.locator('#database-site777-until').isDisabled(),true,'取り込み中は日付を変えない');
  assert.deepEqual(errors,[]);
  // グラフが出ないとき（2026-11-07）：自動取り込み中は待ってから同じページを1回だけ読み込み直し、
  // 読み込み直したページでも出なければ止める（3回目は読み込まない）。
  const stalled=await browser.newPage({viewport:{width:560,height:800}}),loads=[];
  stalled.on('pageerror',e=>errors.push(e.message));
  await stalled.route('**/*',async route=>{
    const u=new URL(route.request().url());
    if(u.pathname.startsWith('/chart/'))await route.abort();
    else if(u.pathname.endsWith('.png'))await route.fulfill({contentType:'image/png',body:Buffer.from(fixture.background,'base64')});
    else {loads.push(u.pathname);await route.fulfill({contentType:'text/html; charset=utf-8',body:fixture.graph1});}
  });
  await stalled.addInitScript(()=>{
    window.__site777GraphWaitMs=300;window.__site777ReloadMs=1500;
    const paused=sessionStorage.getItem('test-paused');
    window.__state={enabled:!paused,epoch:1,ready:true,day:'2026-11-06',days:['2026-11-06'],status:paused||'取り込み中'};
    window.pywebview={api:{state:async()=>structuredClone(window.__state),
      capture:async()=>({prepare_graphs:true}),
      pause:async message=>{sessionStorage.setItem('test-paused',message||'停止');
        Object.assign(window.__state,{enabled:false,status:message});return structuredClone(window.__state);}}};
  });
  const inject=async()=>{
    for(const file of ['site777_capture.js','capture_card.js','site777_overlay.js'])
      await stalled.evaluate(readFileSync(new URL('../../database/assets/'+file,import.meta.url),'utf8'));
  };
  await stalled.goto(source('D4300',1));
  await inject();
  await stalled.waitForFunction(()=>/秒後にこのページを1回だけ読み込み直します/.test(document.querySelector('#database-site777-status')?.textContent||''));
  await stalled.waitForFunction(()=>!document.getElementById('database-site777'),{},{timeout:10000});
  await stalled.waitForLoadState('load');
  assert.equal(loads.length,2,'待ってから1回だけ読み込み直す');
  await inject();
  await stalled.waitForFunction(()=>sessionStorage.getItem('test-paused'),{},{timeout:10000});
  assert.match(await stalled.evaluate(()=>sessionStorage.getItem('test-paused')),/読み込み直してもグラフが表示されない/);
  await stalled.waitForTimeout(2500);
  assert.equal(loads.length,2,'読み込み直したページでは、もう読み込み直さない');
  // 手動の「この画面を取り込む」では読み込み直さず、止めるだけ。
  await stalled.evaluate(()=>{sessionStorage.clear();});
  await stalled.reload();
  await stalled.evaluate(()=>{window.__state.enabled=false;});
  await inject();
  await stalled.click('#database-site777-capture');
  await stalled.waitForFunction(()=>sessionStorage.getItem('test-paused'),{},{timeout:10000});
  assert.match(await stalled.evaluate(()=>sessionStorage.getItem('test-paused')),/グラフが読み込まれないため停止しました/);
  await stalled.waitForTimeout(2500);
  assert.equal(loads.length,3,'手動では読み込み直さない');
  assert.deepEqual(errors,[]);
  console.log('サイトセブン：表31台・遅延グラフ20+11台・停止・番号リンク・追加取得なし・グラフが出ないときの1回だけの読み込み直し：成功');
} finally {await browser.close();}
