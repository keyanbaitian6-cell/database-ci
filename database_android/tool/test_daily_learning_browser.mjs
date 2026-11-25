import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const engines=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
// 通常のゲートは従来どおりChromium。iPhone系の修正時は同じ試験をWebKitでも流せる。
const engineName=process.env.DAILY_BROWSER||'chromium';
assert.ok(['chromium','webkit'].includes(engineName));
const root=path.resolve(process.env.SHARE_WEB_ROOT||fileURLToPath(new URL('../../share_viewer',import.meta.url)));
const today=new Date(Date.now()+9*3600000).toISOString().slice(0,10);
const now=Date.now(), stamp=new Date(now+9*3600000), hhmm=stamp.getUTCHours()*60+stamp.getUTCMinutes();
// 表示する対象日（23:30以降は翌日）と、その日に有効な保存時刻（対象日の前日23:30〜当日23:30未満。8時締切撤廃後の日中時刻でも表示できる）。
const target=new Date(now+9*3600000+(hhmm>=1410?86400000:0)).toISOString().slice(0,10);
const savedAt=`${target}T12:30:00+09:00`;
const longName='とても長い機種名の表示を確かめるための試験機・スーパーロングネームエディションｻﾝﾌﾞﾚｲｸ';
const prediction={format:'daily-learning',version:1,
  status:'長町南：取り込み待ち：長町南の前日データに閉店前に取った台があります。長町南の前日データに使える台がありません／幸町：処理失敗（原本DBを読めません）。従来方式を使用してください',
  updated_at:`${today}T07:30:00+09:00`,days:[{
  target,input_day:target,saved_at:savedAt,groups:[
    {store:'saiwaichou',name:'試験機',active:'current',status:'改善未確認',selected:[['saiwaichou','','試験機',101]],current:[],learned:[]},
    {store:'saiwaichou',name:longName,active:'learned',status:'改善を確認して採用中',
      selected:[1157,1162,1203,1204,1205,1206,1207].map(n=>['saiwaichou','',longName,n]),current:[],learned:[]},
    {store:'nagamachiminami',name:'別店舗の機種',active:'current',status:'x',selected:[['nagamachiminami','','別店舗の機種',9]],current:[],learned:[]}]}]};
const longPrediction=structuredClone(prediction);
for(let i=0;i<35;i++) longPrediction.days[0].groups.push({store:'saiwaichou',name:`スクロール確認機種${i+1}`,active:'current',
  status:'学習データ不足・従来方式',selected:[['saiwaichou','',`スクロール確認機種${i+1}`,2000+i]]});
const server=http.createServer(async(req,res)=>{
  try {
    const name=new URL(req.url,'http://x').pathname;
    const local=path.resolve(root,'.'+(name==='/'?'/index.html':name));
    if(!local.startsWith(root+path.sep)){res.writeHead(403).end();return;}
    res.setHeader('content-type',local.endsWith('.mjs')?'text/javascript':'text/html;charset=utf-8');
    res.end(await fs.readFile(local));
  }catch{res.writeHead(404).end();}
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const browser=await engines[engineName].launch({headless:true,...(engineName==='chromium'?{executablePath:process.env.CHROMIUM_PATH||undefined}:{})});
try{
  for(const width of [320,393,1280]){
    const context=await browser.newContext({viewport:{width,height:852},hasTouch:width<800,isMobile:width<800,serviceWorkers:'block'});
    let fail=false,many=false;
    await context.route('https://script.google.com/**',async route=>{
      const file=new URL(route.request().url()).searchParams.get('file');
      if(file==='daily-learning'){await route.fulfill({json:fail?{error:'失敗'}:many?longPrediction:prediction});return;}
      const json=!file?{format:'database-backup',version:1,records:[{store:'saiwaichou',day:today,machine:'試験',rack:1,games:3000,bb:20,rb:10,jo_net:100}]}:
        file==='pscube'?{format:'pscube-viewer',version:1,machines:[],records:[]}:{events:[],marks:[]};
      await route.fulfill({json});
    });
    await context.route('**/character_birthdays.json*',r=>r.fulfill({json:{entries:[]}}));
    const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/#s=AKfycbTEST${'x'.repeat(40)}`);
    await page.locator('[data-daily-learning]').click();
    const dialog=page.locator('dialog');
    await dialog.getByText('採用中 日次学習版',{exact:true}).waitFor();
    const text=await dialog.innerText();
    // 保存した台を、保存した順のまま出す。候補数は表示中の候補から数える。
    const racks=await dialog.locator('.daily-rack').allInnerTexts();
    assert.deepEqual(racks.map(s=>s.replace(/\s/g,'')),['101番','1157番','1162番','1203番','1204番','1205番','1206番','1207番']);
    assert.ok(text.includes('8台')&&text.includes('採用中 従来方式'),text);
    assert.ok(text.includes('処理失敗（原本DBを読めません）'),'重要な注意は折りたたまない');
    assert.ok(!text.includes('ｻﾝﾌﾞﾚｲｸ')&&text.includes('サンブレイク'),'半角カナは全角にそろえる');
    assert.ok(!text.includes('別店舗の機種'),'共有ページで見られない店舗の候補は出さない');
    assert.ok(!(await dialog.textContent()).includes('長町南の前日データ'),'別店舗の取り込み待ち理由は出さない');
    assert.equal(await dialog.locator('select[data-learning-store] option').count(),1);
    // 横にはみ出さない（長い機種名・7台の候補）。
    const over=await dialog.evaluate(d=>d.scrollWidth-d.clientWidth);
    assert.ok(over<=1,`横にはみ出し ${over}px`);
    const size=await dialog.boundingBox();assert.ok(size.width<=width);
    // 説明は閉じた状態で、押すと開く。
    const more=dialog.locator('details').first();
    assert.equal(await more.evaluate(d=>d.open),false);
    await more.locator('summary').click();
    assert.equal(await more.evaluate(d=>d.open),true);
    if(process.env.DAILY_SHOTS) await page.screenshot({path:path.join(process.env.DAILY_SHOTS,`share-${width}.png`),fullPage:false});
    // 過去日は記録として出し、注意を出す。
    const options=await dialog.locator('select[data-learning-day] option').allInnerTexts();
    assert.ok(options[0].includes('（'),options.join());
    await dialog.getByRole('button',{name:'閉じる',exact:true}).click();
    // 実運用のように機種が多い日。末尾からも「閉じる」を自動スクロールなしで押せること。
    many=true;
    await page.locator('[data-daily-learning]').click();
    await page.waitForFunction(()=>document.querySelectorAll('dialog .daily-group').length===37);
    const list=dialog.locator('.daily-content'),close=dialog.getByRole('button',{name:'閉じる',exact:true});
    // スクロール位置が250ms変わらなくなるまで待つ（最大5秒）。慣性スクロールの途中で比べない。
    async function settle(){
      let last=await list.evaluate(e=>e.scrollTop);
      for(let i=0;i<20;i++){
        await page.waitForTimeout(250);
        const now=await list.evaluate(e=>e.scrollTop);
        if(now===last) return;
        last=now;
      }
    }
    assert.ok(await list.evaluate(e=>e.scrollHeight>e.clientHeight+1000),'候補一覧が長く、縦にスクロールできる');
    async function closeStaysVisible(){
      const visible=await close.evaluate(b=>{
        const r=b.getBoundingClientRect(),viewport=window.visualViewport;
        const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
        return r.top>=0&&r.bottom<=(viewport?.height??innerHeight)&&r.height>=44&&(hit===b||b.contains(hit));
      });
      assert.ok(visible,'末尾でも閉じるボタンが画面内に残り、指で押せる');
    }
    await list.evaluate(e=>{e.scrollTop=e.scrollHeight;});
    await closeStaysVisible();
    assert.ok(await dialog.locator('.daily-footer').isVisible());
    if(engineName==='chromium'&&width<800){
      // 末尾から上へ・先頭から下へ、両方向へ指で動かせること。scrollTopの代入だけで済ませない。
      const cdp=await context.newCDPSession(page);
      for(const bottom of [true,false]){
        await list.evaluate((e,bottom)=>{e.scrollTop=bottom?e.scrollHeight:0;},bottom);
        const before=await list.evaluate(e=>e.scrollTop),r=await list.boundingBox();
        const x=r.x+r.width/2,y=r.y+r.height*(bottom?0.3:0.7),direction=bottom?1:-1;
        await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y}]});
        for(let step=1;step<=8;step++) await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x,y:y+direction*r.height*.4*step/8}]});
        await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
        await page.waitForFunction(({before,bottom})=>{
          const after=document.querySelector('.daily-content').scrollTop;
          return bottom?after<before-30:after>before+30;
        },{before,bottom});
        await settle();
      }
      await cdp.detach();
    }
    // 指を離したあとの慣性スクロールが止まってから先頭へ戻す（2026-11-12 CIで、戻した後も慣性で47px進んで落ちた）。
    await settle();
    await list.evaluate(e=>{e.scrollTop=0;});
    await settle();
    await closeStaysVisible();
    assert.equal(await list.evaluate(e=>e.scrollTop),0);
    // 横向き相当の低い画面でも閉じる帯を隠さない。
    await page.setViewportSize({width,height:360});
    await list.evaluate(e=>{e.scrollTop=e.scrollHeight;});
    await closeStaysVisible();
    if(process.env.DAILY_SHOTS) await page.screenshot({path:path.join(process.env.DAILY_SHOTS,`share-bottom-${engineName}-${width}.png`)});
    await close.click();
    await dialog.waitFor({state:'detached'});
    assert.equal(await page.locator('dialog').count(),0);
    assert.ok(await page.locator('[data-daily-learning]').isEnabled(),'閉じた後もカレンダーを操作できる');
    await page.setViewportSize({width,height:852});
    fail=true;
    await page.locator('[data-daily-learning]').click();
    await page.getByText(/日次学習を読み込めません/).waitFor();
    await page.locator('dialog').getByRole('button',{name:'閉じる',exact:true}).click();
    assert.deepEqual(errors,[]);
    await context.close();
  }
  console.log(`成功：日次学習の共有画面（${engineName}）、320・393・1280px、台と順番・候補数・採用方式・注意・開閉・はみ出し・失敗表示・37機種の末尾から閉じる・縦スクロール・高さ360px`);
}finally{await browser.close();await new Promise(r=>server.close(r));}
