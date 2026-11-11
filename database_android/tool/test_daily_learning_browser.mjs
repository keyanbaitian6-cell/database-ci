import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(process.env.SHARE_WEB_ROOT||fileURLToPath(new URL('../../share_viewer',import.meta.url)));
const today=new Date(Date.now()+9*3600000).toISOString().slice(0,10);
const now=Date.now(), stamp=new Date(now+9*3600000), hhmm=stamp.getUTCHours()*60+stamp.getUTCMinutes();
// 表示する対象日（23:30以降は翌日）と、その日に有効な保存時刻（対象日の前日23:30〜当日08:00）。
const target=new Date(now+9*3600000+(hhmm>=1410?86400000:0)).toISOString().slice(0,10);
const savedAt=`${target}T00:30:00+09:00`;
const longName='とても長い機種名の表示を確かめるための試験機・スーパーロングネームエディションｻﾝﾌﾞﾚｲｸ';
const prediction={format:'daily-learning',version:1,status:'幸町：処理失敗（原本DBを読めません）。従来方式を使用してください',updated_at:`${today}T07:30:00+09:00`,days:[{
  target,input_day:target,saved_at:savedAt,groups:[
    {store:'saiwaichou',name:'試験機',active:'current',status:'改善未確認',selected:[['saiwaichou','','試験機',101]],current:[],learned:[]},
    {store:'saiwaichou',name:longName,active:'learned',status:'改善を確認して採用中',
      selected:[1157,1162,1203,1204,1205,1206,1207].map(n=>['saiwaichou','',longName,n]),current:[],learned:[]},
    {store:'nagamachiminami',name:'別店舗の機種',active:'current',status:'x',selected:[['nagamachiminami','','別店舗の機種',9]],current:[],learned:[]}]}]};
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
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||undefined});
try{
  for(const width of [320,393,1280]){
    const context=await browser.newContext({viewport:{width,height:852},serviceWorkers:'block'});
    let fail=false;
    await context.route('https://script.google.com/**',async route=>{
      const file=new URL(route.request().url()).searchParams.get('file');
      if(file==='daily-learning'){await route.fulfill({json:fail?{error:'失敗'}:prediction});return;}
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
    fail=true;
    await page.locator('[data-daily-learning]').click();
    await page.getByText(/日次学習を読み込めません/).waitFor();
    await page.locator('dialog').getByRole('button',{name:'閉じる',exact:true}).click();
    assert.deepEqual(errors,[]);
    await context.close();
  }
  console.log('成功：日次学習の共有画面、320・393・1280px、台と順番・候補数・採用方式・注意・開閉・はみ出し・失敗表示');
}finally{await browser.close();await new Promise(r=>server.close(r));}
