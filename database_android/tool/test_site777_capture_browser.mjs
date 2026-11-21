// 合成ページを全要求へ返す。実サイト・会員情報・実DBは使わない。
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {existsSync,readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
// PYTHON の指定が無いときは database の .venv を使う（2026-11-08。Windows の 'python' はストアの見せかけで、単独で流すと失敗していた）。
const venvPython=new URL('../../database/.venv/Scripts/python.exe',import.meta.url);
const python=process.env.PYTHON||(existsSync(venvPython)?fileURLToPath(venvPython):'python');
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const fixture=JSON.parse(execFileSync(python,['-c',
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
  // 同じページの対象外・保存済みの台や、非表示の複製が未読でも、必要な台だけを読む。
  await page.goto(source('D4300'));
  await page.evaluate(reader);
  await page.evaluate(()=>{
    window.__site777GraphWaitMs=300;
    const boxes=[...document.querySelectorAll('.graph-box')];
    const hidden=boxes[0].cloneNode(true);hidden.style.display='none';
    hidden.querySelector('img').removeAttribute('src');boxes[0].parentElement.prepend(hidden);
    const img=boxes[1].querySelector('img');
    observer.unobserve(img);img.removeAttribute('src');delete img.dataset.graph;
    window.__scrolledRacks=[];
    const scroll=Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView=function(...args){window.__scrolledRacks.push(this.querySelector('span')?.textContent);return scroll.apply(this,args);};
  });
  await page.evaluate(()=>databaseSite777.prepare(()=>false,[101]));
  const filtered=await page.evaluate(()=>databaseSite777.read(false,[101]));
  assert.deepEqual(filtered.graphs.map(g=>g.rack),[101]);
  assert.equal(filtered.graph_racks.length,20,'非表示の複製を含めない');
  assert.ok(!(await page.evaluate(()=>window.__scrolledRacks)).includes('[102]'),'不要な台へスクロールしない');
  await page.evaluate(()=>databaseSite777.prepare(()=>false,[]));
  assert.deepEqual(await page.evaluate(()=>databaseSite777.read(false,[]).graphs),[],'対象がないページでは画像を読まない');
  const failure=await page.evaluate(async()=>{
    try{await databaseSite777.prepare(()=>false,[102]);}catch(e){return {stalled:e.stalled,detail:e.graph_wait};}
  });
  assert.equal(failure.stalled,true,'必要な台の画像不足は停止する');
  assert.equal(failure.detail.rack,102);
  // 画面が本当に動いたときだけ読み込むページで、1ページ目の上端の台が出ずに止まっていた（2026-11-12〜18、
  // ゴーゴージャグラー3の1286・1287番、1台だけの機種など。手動では人が画面を動かすので取れる）。
  // P’s CUBEの一覧と同じく、一度離れてから台へ戻すと、サイトの読み込みが進む。上端の台へ飛ぶだけでは、台は
  // 画面に入ったままで、サイトに新しいきっかけが届かない。ここでは「最初に画面に入った知らせを取りこぼし、
  // 次に画面へ入り直したときに読み込む」ページで試す（実サイトの仕組みは確かめていない。止まり方を写した模型）。
  await page.goto(source('D4300'));
  await page.evaluate(reader);
  const topRack=await page.evaluate(()=>{
    window.__site777GraphWaitMs=4000;window.__site777NudgeMs=300;scrollTo(0,0);
    const img=document.querySelectorAll('.graph-box img')[0], rack=img.closest('.graph-box').querySelector('span').textContent.replace(/\D/g,'');
    const lazy=img.dataset.graph||`/chart/RequestSPDedamaTransitionChartForPortal.do?rack=${rack}&again=1`;
    observer.unobserve(img);delete img.dataset.graph;img.src='/f/contents/images/sp/graph-back.png';
    let first=true;
    const late=new IntersectionObserver(entries=>entries.forEach(e=>{
      if(first){first=false;return;}
      if(e.isIntersecting){img.src=lazy;late.disconnect();}
    }));
    late.observe(img);
    return Number(img.closest('.graph-box').querySelector('span').textContent.replace(/\D/g,''));
  });
  await page.waitForTimeout(300);
  assert.equal(await page.evaluate(()=>document.querySelector('.graph-box img').src.includes('graph-back')),true,
    '取りこぼした台は、そのままでは仮の画像のまま');
  await page.evaluate(rack=>databaseSite777.prepare(()=>false,[rack]),topRack);
  assert.deepEqual((await page.evaluate(rack=>databaseSite777.read(false,[rack]),topRack)).graphs.map(g=>g.rack),[topRack],
    '一度離れてから戻すと、取りこぼした上端の台も読める');
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
    window.pywebview.api.configure=async(enabled,day,until,direction)=>{
      window.__configured.push(direction?[enabled,day,until,direction]:[enabled,day,until]);
      if(direction)window.__scopeState.direction=direction;
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
  // 上から／下から（2026-11-07、メルヘンと同じ）：OFFのとき押すと、その向きで自動取り込みを始める。間隔は5〜7秒。
  assert.equal(await page.locator('#database-site777-bottom').isDisabled(),true,'取り込み中は向きを変えない');
  await page.evaluate(()=>{Object.assign(window.__scopeState,{enabled:false,epoch:4,direction:'top'});});
  await page.waitForFunction(()=>!document.querySelector('#database-site777-bottom').disabled);
  assert.equal(await page.getAttribute('#database-site777-top','aria-pressed'),'true');
  await page.click('#database-site777-bottom');
  await page.waitForFunction(()=>window.__configured.length===3);
  assert.deepEqual(await page.evaluate(()=>window.__configured[2]),[true,'2026-11-04','2026-11-06','bottom']);
  await page.waitForFunction(()=>document.querySelector('#database-site777-bottom').getAttribute('aria-pressed')==='true');
  assert.match(await page.locator('#database-site777').innerText(),/間隔：3〜5秒ランダム/);
  // まだ確定していない日（その日の23:30より前、2026-11-10）を取り込むときは確かめる（2026-11-08）：やめたら何も変えず、OKなら確認済みを渡す。
  // 確定した日だけなら確かめない。手動の「この画面を取り込む」でも同じ。
  const dialogs=[];
  await page.evaluate(()=>{
    window.__configured=[];
    Object.assign(window.__scopeState,{enabled:false,epoch:5,day:'2026-11-06',until:null,queue:[],finished_days:[],
      unfinished_from:'2026-11-06',today_ok:false,status:'停止しました。'});
    window.pywebview.api.configure=async(...args)=>{window.__configured.push(args);
      Object.assign(window.__scopeState,{today_ok:args[4]===true});return structuredClone(window.__scopeState);};
  });
  await page.waitForFunction(()=>!document.querySelector('#database-site777-auto').disabled&&
    document.querySelector('#database-site777-day').value==='2026-11-06');
  page.once('dialog',d=>{dialogs.push(d.message());d.dismiss();});
  await page.click('#database-site777-auto');
  await page.waitForTimeout(300);
  assert.equal(dialogs.length,1);assert.match(dialogs[0],/11\/06の分はまだ確定していません（閉店23:30・23:45ごろ最終更新）/);
  assert.match(dialogs[0],/その日の23:30以降に取り込み直すと置き換わります/);
  assert.deepEqual(await page.evaluate(()=>window.__configured),[],'やめたら開始しない');
  page.once('dialog',d=>{dialogs.push(d.message());d.accept();});
  await page.click('#database-site777-auto');
  await page.waitForFunction(()=>window.__configured.length===1);
  assert.deepEqual(await page.evaluate(()=>window.__configured[0]),[true,'2026-11-06',null,null,true]);
  await page.evaluate(()=>{window.__configured=[];Object.assign(window.__scopeState,{enabled:false,epoch:6,day:'2026-11-05',today_ok:false});});
  await page.waitForFunction(()=>document.querySelector('#database-site777-day').value==='2026-11-05');
  await page.click('#database-site777-auto');
  await page.waitForFunction(()=>window.__configured.length===1);
  assert.deepEqual(await page.evaluate(()=>window.__configured[0]),[true,'2026-11-05',null,null,false],'終わった日は確かめない');
  assert.equal(dialogs.length,2);
  await page.evaluate(()=>{window.__configured=[];Object.assign(window.__scopeState,{enabled:false,epoch:7,day:'2026-11-06',today_ok:false});});
  await page.waitForFunction(()=>document.querySelector('#database-site777-day').value==='2026-11-06'&&
    !document.querySelector('#database-site777-capture').disabled);
  page.once('dialog',d=>{dialogs.push(d.message());d.dismiss();});
  await page.click('#database-site777-capture');
  await page.waitForTimeout(300);
  assert.equal(dialogs.length,3);
  assert.deepEqual(await page.evaluate(()=>window.__configured),[],'手動でも、やめたら取り込まない');
  assert.deepEqual(errors,[]);
  // グラフが出ないとき（2026-11-07 利用者「グラフが出なかったら1分後に再読みするんじゃなかったの？」）：自動取り込み中は
  // 待ってからページを読み込み直し、ONのまま続ける。同じページで3回まで、それでも出なければ止める。
  const stalled=await browser.newPage({viewport:{width:560,height:800}}),loads=[];
  stalled.on('pageerror',e=>errors.push(e.message));
  await stalled.route('**/*',async route=>{
    const u=new URL(route.request().url());
    if(u.pathname.startsWith('/chart/'))await route.abort();
    else if(u.pathname.endsWith('.png'))await route.fulfill({contentType:'image/png',body:Buffer.from(fixture.background,'base64')});
    else {loads.push(u.pathname);await route.fulfill({contentType:'text/html; charset=utf-8',body:fixture.graph1});}
  });
  await stalled.addInitScript(()=>{
    window.__site777GraphWaitMs=300;window.__site777RetryMs=1200;
    const paused=sessionStorage.getItem('test-paused');
    window.__state={enabled:!paused&&!sessionStorage.getItem('test-manual'),epoch:1,ready:true,day:'2026-11-06',days:['2026-11-06'],status:paused||'取り込み中'};
    window.pywebview={api:{state:async()=>structuredClone(window.__state),
      capture:async()=>({prepare_graphs:true}),
      note:async payload=>{sessionStorage.setItem('test-graph-wait',payload);},
      pause:async message=>{sessionStorage.setItem('test-paused',message||'停止');
        Object.assign(window.__state,{enabled:false,status:message});return structuredClone(window.__state);}}};
  });
  // PC版と同じく、ページを読み込むたびにカードを入れる。
  const inject=async()=>{
    try{for(const file of ['site777_capture.js','capture_card.js','site777_overlay.js'])
      await stalled.evaluate(readFileSync(new URL('../../database/assets/'+file,import.meta.url),'utf8'));}catch(_){}
  };
  stalled.on('domcontentloaded',()=>{inject();});
  await stalled.goto(source('D4300',1));
  await stalled.waitForFunction(()=>/秒後にこのページを読み込み直して続けます（1\/3回目）/.test(document.querySelector('#database-site777-status')?.textContent||''));
  await stalled.waitForFunction(()=>sessionStorage.getItem('test-paused'),{},{timeout:30000});
  assert.match(await stalled.evaluate(()=>sessionStorage.getItem('test-paused')),/3回読み込み直してもグラフが表示されない/);
  assert.equal(loads.length,4,'最初の1回と、1分後（試験では1.2秒後）の読み込み直し3回');
  const graphWait=JSON.parse(await stalled.evaluate(()=>sessionStorage.getItem('test-graph-wait')));
  assert.deepEqual(Object.keys(graphWait).sort(),['kind','rack','complete','width','image_kind','visible','day','page',
    'images','canvases','backgrounds','visibility','focused'].sort());
  // 止まったときにページが見えていたか（2026-11-21。見えないページではサイトの遅延読み込みが動かない）。
  assert.equal(graphWait.visibility,'visible');assert.equal(typeof graphWait.focused,'boolean');
  // 画像はパスと大きさだけ（?以降・会員情報は残さない。2026-11-19 グラフが出ているのに仮の画像と判定する疑いの調査用）。
  assert.ok(graphWait.images.length>0&&graphWait.images.every(i=>Object.keys(i).sort().join()==='h,path,shown,w'&&!/[?#]/.test(i.path)),JSON.stringify(graphWait.images));
  assert.ok(graphWait.backgrounds.every(b=>!/[?#]/.test(b)));
  assert.equal(graphWait.kind,'graph_wait');assert.equal(graphWait.rack,101);
  assert.equal(graphWait.image_kind,'chart');assert.equal(graphWait.width,0);
  await stalled.waitForTimeout(2500);
  assert.equal(loads.length,4,'止めた後は読み込み直さない');
  // 手動の「この画面を取り込む」では読み込み直さず、止めるだけ。
  await stalled.evaluate(()=>{sessionStorage.clear();sessionStorage.setItem('test-manual','1');});
  await stalled.reload();
  await stalled.waitForSelector('#database-site777-capture');
  await stalled.click('#database-site777-capture');
  await stalled.waitForFunction(()=>sessionStorage.getItem('test-paused'),{},{timeout:10000});
  assert.match(await stalled.evaluate(()=>sessionStorage.getItem('test-paused')),/グラフが読み込まれないため停止しました/);
  await stalled.waitForTimeout(2500);
  assert.equal(loads.length,5,'手動では読み込み直さない');
  assert.deepEqual(errors,[]);
  // 2026-11-08 Codexのレビュー：(1) 移動中（PCが読み込みの完了を待つ間）は旧画面を取り込み直さない。
  // (2) 同じ窓で止めて開始し直したら、画像の読み込み直しの回数を0に戻す。(3) 止めるときは理由コードをPCへ渡す。
  const card=readFileSync(new URL('../../database/assets/capture_card.js',import.meta.url),'utf8');
  const overlay=readFileSync(new URL('../../database/assets/site777_overlay.js',import.meta.url),'utf8');
  const review=await browser.newPage({viewport:{width:560,height:800}});
  review.on('pageerror',e=>errors.push(e.message));
  await review.route('**/*',route=>route.fulfill({contentType:'text/html; charset=utf-8',body:'<!doctype html><body>手元の試験</body>'}));
  await review.goto(source('D4300',1));
  await review.evaluate(()=>{
    window.__site777RetryMs=600000;
    window.__calls=[];
    window.__s={enabled:false,epoch:1,ready:true,navigating:false,day:'2026-11-06',days:['2026-11-06'],status:'停止'};
    window.pywebview={api:{state:async()=>structuredClone(window.__s),
      configure:async enabled=>{window.__calls.push(['configure',enabled]);
        Object.assign(window.__s,{enabled,epoch:window.__s.epoch+1,status:'開始'});return structuredClone(window.__s);},
      capture:async()=>{window.__calls.push(['capture']);
        // PCと同じく、移動を指示したら読み込みが終わるまで ready にしない（この試験では読み込みは来ない）。
        Object.assign(window.__s,{ready:false,navigating:true});
        return {action:{type:'listed',url:location.href},state:structuredClone(window.__s)};},
      pause:async(message,reason,retries)=>{window.__calls.push(['pause',message,reason,retries]);
        Object.assign(window.__s,{enabled:false,status:message||'停止しました。'});return structuredClone(window.__s);},
      save_overlay_layout:async()=>{}}};
    window.databaseSite777={read:()=>({url:location.href}),samePage:(a,b)=>a===b,go:()=>{}};
  });
  await review.evaluate(card);await review.evaluate(overlay);
  await review.click('#database-site777-auto');
  await review.waitForFunction(()=>window.__calls.some(c=>c[0]==='capture'));
  await review.waitForTimeout(3000);
  assert.equal(await review.evaluate(()=>window.__calls.filter(c=>c[0]==='capture').length),1,'移動中は旧画面を読み直さない');
  await review.evaluate(()=>{window.__s.enabled=false;});
  await review.waitForFunction(()=>document.querySelector('#database-site777-auto').textContent.includes('OFF'));
  assert.equal(await review.locator('#database-site777-capture').isDisabled(),true,'移動中は手動の取り込みも押せない');
  // 前の試行で3回使い切った窓で、開始し直す。読み込み直しの回数が0に戻り、すぐにはOFFにならない。
  await review.evaluate(()=>{
    sessionStorage.setItem('database-site777-retries',JSON.stringify({[location.href]:3}));
    Object.assign(window.__s,{ready:true,navigating:false});window.__calls.length=0;
    window.pywebview.api.capture=async()=>{window.__calls.push(['capture']);return {prepare_graphs:true};};
    window.databaseSite777.prepare=async()=>{throw Object.assign(new Error('試験'),{stalled:true});};
  });
  await review.click('#database-site777-auto');
  await review.waitForFunction(()=>/（1\/3回目）/.test(document.querySelector('#database-site777-status')?.textContent||''));
  assert.equal(await review.evaluate(()=>window.__calls.some(c=>c[0]==='pause')),false,'開始し直したら前の3回を数えない');
  // 停止ボタンは理由コード user_stop を渡す。
  await review.click('#database-site777-auto');
  await review.waitForFunction(()=>window.__calls.some(c=>c[0]==='pause'));
  assert.deepEqual(await review.evaluate(()=>window.__calls.find(c=>c[0]==='pause')),['pause',null,'user_stop',null]);
  // 3回読み込み直しても出ない台は、PCが認めればグラフなしで進める（止めない）。PCが断ったら（2台目など）今までどおり止める
  // （2026-11-13 利用者「グラフなしで進めるようにお願いね」）。開始ボタンは回数を0に戻すので、ONは状態で与える。
  await review.evaluate(()=>{
    sessionStorage.setItem('database-site777-retries',JSON.stringify({[location.href]:3}));
    window.__calls.length=0;window.__allow=true;
    window.databaseSite777.prepare=async()=>{throw Object.assign(new Error('試験'),{stalled:true,
      graph_wait:{rack:101,complete:true,width:260,image_kind:'placeholder',visible:true}});};
    window.pywebview.api.note=async()=>{};
    window.pywebview.api.skip_graph=async(rack,epoch)=>{window.__calls.push(['skip_graph',rack,epoch]);
      const ok=window.__allow;window.__allow=false;return {ok,state:structuredClone(window.__s)};};
    Object.assign(window.__s,{enabled:true,ready:true,navigating:false});
  });
  await review.waitForFunction(()=>window.__calls.some(c=>c[0]==='pause'));
  const skipping=await review.evaluate(()=>window.__calls.filter(c=>c[0]!=='capture'));
  assert.deepEqual(skipping.map(c=>c[0]),['skip_graph','skip_graph','pause'],'1回目は進み、断られた2回目で止まる');
  assert.equal(skipping[0][1],101);
  assert.equal(skipping[0][2],await review.evaluate(()=>window.__s.epoch),'今の実行番号を渡す');
  assert.equal(skipping[2][2],'graph_retry_limit');
  // 回数を残せない（sessionStorage が使えない）ときは、読み込み直さずに止め、「3回読み込み直しても」とは書かない。
  await review.evaluate(()=>{
    Storage.prototype.getItem=()=>{throw new Error('blocked');};
    Object.assign(window.__s,{enabled:false});window.__calls.length=0;
  });
  await review.waitForFunction(()=>document.querySelector('#database-site777-auto').textContent.includes('OFF'));
  await review.click('#database-site777-auto');
  await review.waitForFunction(()=>window.__calls.some(c=>c[0]==='pause'));
  const stopped=await review.evaluate(()=>window.__calls.find(c=>c[0]==='pause'));
  assert.equal(stopped[2],'graph_retry_storage');
  assert.match(stopped[1],/回数を残せないため、読み込み直していません/);
  assert.deepEqual(errors,[]);
  // 2026-11-08 利用者「3分後には自動復帰」：再開を待つ間はボタンに時刻を出し、押すと取り消す（停止ボタン扱い）。
  // 自動で再開しても（resume_serial が変わっても）、グラフの読み込み直しの回数は戻さない（2026-11-08 利用者「256やって」：
  // 再開のたびに0に戻すと、出ないページを再開1回につき4回読み込んでいた）。
  const waiting=await browser.newPage({viewport:{width:560,height:800}});
  waiting.on('pageerror',e=>errors.push(e.message));
  await waiting.route('**/*',route=>route.fulfill({contentType:'text/html; charset=utf-8',body:'<!doctype html><body>手元の試験</body>'}));
  await waiting.goto(source('D4300',1));
  await waiting.evaluate(()=>{
    sessionStorage.setItem('database-site777-retries',JSON.stringify({[location.href]:3}));
    window.__calls=[];
    window.__s={enabled:false,epoch:5,ready:false,day:'2026-11-06',days:['2026-11-06'],status:'止まりました。',resume_at:'02:03',resume_serial:0,
      previous:'前回（11/07 23:50）：11/04〜11/06を取り込む途中で止まりました【画像待ちの上限】。'};
    window.pywebview={api:{state:async()=>structuredClone(window.__s),
      pause:async(message,reason,retries)=>{window.__calls.push(['pause',message,reason,retries]);
        Object.assign(window.__s,{resume_at:null});return structuredClone(window.__s);},
      configure:async()=>{window.__calls.push(['configure']);return structuredClone(window.__s);},save_overlay_layout:async()=>{}}};
    window.databaseSite777={read:()=>({url:location.href}),samePage:(a,b)=>a===b,go:()=>{}};
  });
  await waiting.evaluate(card);await waiting.evaluate(overlay);
  await waiting.waitForFunction(()=>document.querySelector('#database-site777-auto')?.textContent==='自動取り込み：02:03に再開予定（押すと取り消し）');
  assert.ok(await waiting.evaluate(()=>sessionStorage.getItem('database-site777-retries')),'再開する前は回数を残す');
  // 窓を開き直したときの前回の案内（2026-11-08）。PCが消したら（開始したら）隠す。
  assert.match(await waiting.locator('#database-site777-previous').innerText(),/前回（11\/07 23:50）.*【画像待ちの上限】/);
  await waiting.evaluate(()=>{window.__s.previous=null;});
  await waiting.waitForFunction(()=>getComputedStyle(document.querySelector('#database-site777-previous')).display==='none');
  await waiting.evaluate(()=>{window.__s.resume_serial=1;});
  await waiting.waitForTimeout(1500);
  assert.equal(await waiting.evaluate(()=>JSON.parse(sessionStorage.getItem('database-site777-retries'))[location.href]),3,'再開しても回数は残す');
  await waiting.click('#database-site777-auto');
  await waiting.waitForFunction(()=>window.__calls.length>0);
  assert.deepEqual(await waiting.evaluate(()=>window.__calls),[['pause',null,'user_stop',null]],'待っている間に押すと取り消す（開始しない）');
  await waiting.waitForFunction(()=>document.querySelector('#database-site777-auto')?.textContent.includes('OFF（押すと開始）'));
  // 機種一覧の各機種の横に取り込み状況を出す（2026-11-10 利用者「なぜメルヘンと同じ仕様になってないんだ。機種のよこに
  // 未取り込みとかもでてないし」）。メルヘンと同じ文言：済 n/m・途中 n/m・未取込・対象外。
  const listing=await browser.newPage({viewport:{width:560,height:800}});
  listing.on('pageerror',e=>errors.push(e.message));
  await listing.route('**/*',route=>route.fulfill({contentType:'text/html; charset=utf-8',body:`<h2 class=page-title>Ｐ－ＳＴＡＴＩＯＮ＆ＩＩ　スロット館</h2>`+
    [['120141','ゴーゴージャグラー３ [31]'],['120406','L牙狼 闇を照らす者'],['120500','試験機種 [2]'],['120600','沖ドキ！GOLD-30 [3]']].map(([m,label])=>
      `<a href="D2300.do?pmc=04034001&amp;clc=03&amp;urt=2000&amp;mdc=${m}&amp;bn=1" class="imageSet"><div class="icon-kisyu"></div><strong>${label}</strong></a>`).join('')}));
  await listing.goto('https://m.site777.jp/f/D0300.do?pmc=04034001&clc=03&urt=2000&pan=1');
  await listing.evaluate(()=>{
    window.__asked=[];
    window.__s={enabled:false,epoch:1,ready:false,day:'2026-11-09',days:['2026-11-09'],status:'停止',added:0,kept:0};
    window.pywebview={api:{state:async()=>structuredClone(window.__s),save_overlay_layout:async()=>{},
      machine_status:async raw=>{const machines=JSON.parse(raw).machines;window.__asked.push(machines.map(m=>[m.model_id,m.count]));
        return {day:'2026-11-09',status:[{done:31,total:31,excluded:false},{done:0,total:1,excluded:false},
          {done:1,total:2,excluded:false},{done:0,total:3,excluded:true}]};}}};
  });
  await listing.evaluate(reader);await listing.evaluate(card);await listing.evaluate(overlay);
  await listing.waitForFunction(()=>document.querySelectorAll('.database-site777-badge').length===4);
  assert.deepEqual(await listing.evaluate(()=>[...document.querySelectorAll('a.imageSet')].map(a=>a.querySelector('.database-site777-badge')?.textContent)),
    ['11/9 済 31/31','11/9 未取込','11/9 1/2','対象外']);
  assert.deepEqual(await listing.evaluate(()=>window.__asked[0]),[['120141',31],['120406',1],['120500',2],['120600',3]]);
  await listing.waitForTimeout(1500);
  assert.equal(await listing.evaluate(()=>window.__asked.length),1,'状況が変わらないうちは聞き直さない');
  await listing.evaluate(()=>{window.__s.added=1;});
  await listing.waitForFunction(()=>window.__asked.length===2);
  assert.equal(await listing.evaluate(()=>document.querySelectorAll('.database-site777-badge').length),4,'付け直しても重ならない');
  assert.deepEqual(errors,[]);
  console.log('サイトセブン：表31台・遅延グラフ20+11台・必要な台だけの画像待ち・非表示の複製除外・不足画像の診断記録・停止・番号リンク・追加取得なし・グラフが出ないときの1分後の読み込み直し（3回まで）・それでも出ない1台はグラフなしで進む（2台目は停止）・移動中の読み直しなし・開始し直しで回数を戻す（自動の再開では戻さない）・停止の理由コード・自動の再開待ちの表示と取り消し・前回の案内・機種一覧の取り込み状況：成功');
} finally {await browser.close();}
