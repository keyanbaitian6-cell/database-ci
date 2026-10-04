// Drive bridge integration in a real browser; the Apps Script reply is mocked.
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const web=fileURLToPath(new URL('../web/',import.meta.url));
const server=http.createServer(async(req,res)=>{
  const pathname=new URL(req.url,'http://localhost').pathname;
  if(pathname==='/setup'){res.setHeader('content-type','text/html');res.end('<!doctype html><body>bridge test</body>');return;}
  const local=path.resolve(web,'.'+pathname);
  if(!local.startsWith(web)){res.writeHead(403).end();return;}
  try{res.setHeader('content-type','text/javascript');res.end(await fs.readFile(local));}
  catch{res.writeHead(404).end();}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const origin='http://127.0.0.1:'+server.address().port;
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||undefined,args:['--no-sandbox']});
const page=await browser.newPage();
const errors=[];page.on('pageerror',e=>errors.push(e.message));
const base='https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/cgi-bin/';
const machine={store:'c740601',rate:'20',machine:'テスト機種',expected_count:2,machine_type:null,url:base+'nc-v05-011.php?cd_ps=2&bai=20'};
const rec=(rack,day,games)=>({store:'c740601',rate:'20',machine:machine.machine,rack,day,bb:5,rb:3,at_art:0,games,my:900,
  observed_at:day+'T12:00:00+09:00',detail_url:base+'nc-v06-001.php?cd_dai='+rack+'#'+day.replaceAll('-',''),graph:null});
const doc=(exported_at,games)=>({format:'pscube-viewer',version:1,kind:'viewer',source:'pc',exported_at,
  machines:[machine],records:[rec(1,'2026-10-01',games),rec(2,'2026-10-01',3100)]});
const SCRIPT='https://script.google.com/macros/s/AKfycb_TEST/exec';
let reply=doc('2026-10-01T20:00:00+09:00',3000),requests=[],scriptVersion=null;   // scriptVersion: 新しいApps Scriptの更新の目印（nullは古いスクリプト＝全文を返す）
await page.route('https://script.google.com/**',route=>{const url=route.request().url();requests.push(url);
  const body=scriptVersion&&url.includes('check=1')?{format:'drive-check',version:scriptVersion,name:'pscube-viewer-drive.json'}:reply;
  return route.fulfill({status:200,contentType:'application/json',headers:{'access-control-allow-origin':'*'},body:JSON.stringify(body)});});
try{
  await page.goto(origin+'/setup');
  await page.evaluate(async()=>{const {createPscubeBridge}=await import('/pscube/viewer_bridge.mjs');window.databaseViewer=createPscubeBridge();});
  const sync=known=>page.evaluate(async({url,known})=>{const text=await window.databaseViewer.fromRemote(url,known);if(text)await window.databaseViewer.save(text);return text;},{url:SCRIPT,known});
  assert.equal(await page.evaluate(()=>window.databaseViewer.load()),null);
  await assert.rejects(page.evaluate(()=>window.databaseViewer.fromRemote('https://evil.example/x',null)),/Googleのスクリプト/);
  assert.equal(requests.length,0);
  await page.evaluate(url=>window.databaseViewer.setRemote(url),SCRIPT);
  assert.equal(await page.evaluate(()=>window.databaseViewer.getRemote()),SCRIPT);
  await sync(null);assert.deepEqual(requests,[SCRIPT+'?file=pscube&check=1'],'古いスクリプトは全文を返す：そのまま使う');
  assert.equal(JSON.parse(await page.evaluate(()=>window.databaseViewer.load())).records[0].games,3000);
  assert.equal(await sync(reply.exported_at),null);
  reply=doc('2026-10-02T08:00:00+09:00',3600);await sync(null);
  const stored=await page.evaluate(()=>window.databaseViewer.load());
  assert.equal(JSON.parse(stored).records[0].games,3600);
  reply={format:'database-backup',exported_at:'x'};
  await assert.rejects(sync(null),/Apps Scriptを更新/);
  assert.equal(await page.evaluate(()=>window.databaseViewer.load()),stored);
  reply={error:'pscube-viewer-drive.json がGoogleドライブに見つかりません。'};
  await assert.rejects(sync(null),/見つかりません/);
  assert.equal(await page.evaluate(()=>window.databaseViewer.load()),stored);
  const downloadPromise=page.waitForEvent('download');
  await page.evaluate(()=>window.databaseViewer.exportBackup());
  const download=await downloadPromise;
  assert.match(download.suggestedFilename(),/^pscube-backup-browser-\d{8}-\d{6}\.json$/);
  const saved=JSON.parse(await fs.readFile(await download.path(),'utf8'));
  assert.equal(saved.kind,'backup');assert.equal(saved.source,'browser');assert.equal(saved.records.length,2);
  assert.match(saved.exported_at,/[+-]\d\d:\d\d$/);
  await page.evaluate(()=>window.databaseViewer.setRemote(null));
  assert.equal(await page.evaluate(()=>window.databaseViewer.getRemote()),null);
  // 新しいApps Script：目印が同じなら、ファイルは読まない（実ブラウザのlocalStorageに目印を覚える）。
  await page.evaluate(url=>window.databaseViewer.setRemote(url),SCRIPT);
  scriptVersion='v1';reply=doc('2026-10-03T08:00:00+09:00',3700);requests=[];
  await sync(null);assert.deepEqual(requests,[SCRIPT+'?file=pscube&check=1',SCRIPT+'?file=pscube']);
  requests=[];assert.equal(await sync('2026-10-03T08:00:00+09:00'),null);
  assert.deepEqual(requests,[SCRIPT+'?file=pscube&check=1'],'目印も書き出し時刻も同じ：確認だけ');
  scriptVersion='v2';reply=doc('2026-10-03T21:00:00+09:00',3800);requests=[];
  await sync('2026-10-03T08:00:00+09:00');assert.equal(requests.length,2,'目印が変わったら読む');
  assert.equal(JSON.parse(await page.evaluate(()=>window.databaseViewer.load())).records[0].games,3800);
  assert.deepEqual(errors,[]);
  console.log('PASS: shared Drive bridge URL validation, source, unchanged/new data, version check (old and new script), failed sync preservation, export and settings');
}finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
