import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(process.env.SHARE_WEB_ROOT||fileURLToPath(new URL('../../share_viewer',import.meta.url)));
const today=new Date(Date.now()+9*3600000).toISOString().slice(0,10);
const prediction={format:'daily-learning',version:1,status:'比較中',updated_at:`${today}T07:30:00+09:00`,days:[{
  target:today,input_day:today,saved_at:`${today}T07:30:00+09:00`,groups:[{store:'saiwaichou',name:'試験機',active:'current',
    status:'改善未確認',selected:[['saiwaichou','','試験機',101]],current:[],learned:[]}]}]};
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
    await page.getByText('101番 試験機',{exact:true}).waitFor();
    assert.ok((await page.locator('dialog').innerText()).includes('従来方式'));
    const size=await page.locator('dialog').boundingBox();assert.ok(size.width<=width);
    await page.locator('dialog').getByRole('button',{name:'閉じる',exact:true}).click();
    fail=true;
    await page.locator('[data-daily-learning]').click();
    await page.getByText(/日次学習を読み込めません/).waitFor();
    assert.deepEqual(errors,[]);
    await context.close();
  }
  console.log('成功：日次学習の共有画面、320・393・1280px、候補・従来方式・失敗表示');
}finally{await browser.close();await new Promise(r=>server.close(r));}
