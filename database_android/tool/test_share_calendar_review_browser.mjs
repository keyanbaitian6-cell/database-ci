// 閲覧専用の共有ページ（share_viewer/、お試し 2026-10-09）を隔離ブラウザで開く。スクリプトへの通信は偽の返事。
// カレンダーの差枚・イベント、日付を押したTOP50（11位からは折りたたみ）・10選、台を押す→その機種の台一覧→台のデータ、店の切り替え、リンクの # を消すこと、何も送らないこと、
// 利用者自身の閲覧ページの保存（database-viewer の名前）に触れないこと、狭い画面ではみ出さないこと。
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
// SHARE_WEB_ROOT（check_before_build.sh が渡す）があれば、公開するステージ（版 ?v= 付き）を試す。
const root = process.env.SHARE_WEB_ROOT || fileURLToPath(new URL('../../share_viewer/', import.meta.url));
const server = http.createServer(async (req, res) => {
  const name = new URL(req.url, 'http://x').pathname.replace(/^\/share\//, '') || 'index.html';
  const local = path.resolve(root, name);
  if (!local.startsWith(path.resolve(root))) { res.writeHead(403).end(); return; }
  try {
    const body = await fs.readFile(local);
    res.setHeader('content-type', local.endsWith('.mjs') ? 'text/javascript' : 'text/html; charset=utf-8');
    res.end(body);
  } catch { res.writeHead(404).end(); }
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const origin = `http://127.0.0.1:${server.address().port}`;
// SHARE_PUBLIC_URL（例 https://keyanbaitian6-cell.github.io/database-share/index.html）を渡すと、公開したページで試す。
const pageUrl = process.env.SHARE_PUBLIC_URL || `${origin}/share/index.html`;

// 今月（日本時間）の1日・2日に台を置く（ページは今月から開く）。
const now = new Date(Date.now() + 9 * 3600000);
const ym = now.toISOString().slice(0, 7);
const d1 = `${ym}-01`, d2 = `${ym}-02`, d3 = `${ym}-03`;
// 先月の15日（保存したHTMLからの集計だけがある日。2026-10-18 day_summaries）。
const prev = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - 1, 15)).toISOString().slice(0, 10);
const curve = (heights) => {
  const c = heights.map((h, i) => [i * 10 + 0.5, 200.5 - h]);
  const ys = c.map(p => p[1]);
  return {baseline_y: 200.5, peak_y: Math.min(...ys), trough_y: Math.max(...ys), end_y: c.at(-1)[1], curve: c};
};
const meruhen = {format: 'database-backup', version: 1, exported_at: '2026-10-09T06:48:00+09:00', records: [
  {store: 'nagamachiminami', day: d1, machine: 'ｺﾞｰｺﾞｰｼﾞｬｸﾞﾗｰ3', rack: 101, games: 6000, bb: 30, rb: 20, max_hold: 2376, graph_measurement: curve([0, -63, 40, 147, 128])},
  {store: 'nagamachiminami', day: d1, machine: 'ｺﾞｰｺﾞｰｼﾞｬｸﾞﾗｰ3', rack: 102, games: 4000, bb: 10, rb: 5, max_hold: 2900, graph_measurement: curve([0, 120, 40, -50])},
  {store: 'nagamachiminami', day: d1, machine: '北斗<script>', rack: 103, games: 88888888, bb: 1, rb: 1, max_hold: 1},
  // 3日：ジャグラーオンラインの差枚の台が15台（TOP50の11位からは折りたたみ）。ネオアイム201〜214番は (i-7)*100 枚。
  {store: 'nagamachiminami', day: d3, machine: 'ハナハナ', rack: 301, games: 7000, bb: 30, rb: 20, jo_net: 5000},
  ...Array.from({length: 14}, (_, k) => ({store: 'nagamachiminami', day: d3, machine: 'ネオアイム', rack: 201 + k,
    games: 1000 * (k + 1), bb: 11 + k, rb: k + 6, max_hold: 1500, jo_net: (k - 6) * 100})),
  {store: 'saiwaichou', day: d2, machine: '幸町の機種', rack: 5, games: 3000, bb: 9, rb: 9, max_hold: 2376, graph_measurement: curve([0, -63, 40, 147, 128])},
  // 差枚の取れていない台：0回転と500回転未満（その日のまとめに台数を出す、2026-10-21）。
  {store: 'saiwaichou', day: d2, machine: '幸町の機種B', rack: 6, games: 0, bb: 0, rb: 0},
  {store: 'saiwaichou', day: d2, machine: '幸町の機種C', rack: 7, games: 300, bb: 1, rb: 0},
], date_events: [{store: 'nagamachiminami', day: d1, name: '半列<b>', updated_at: '2026-09-01T00:00:00Z'}],
// 保存したアナスロのHTMLからの日ごとの集計（台の数値は無い）。台データのある日（幸町の2日）には使わない。形のおかしい日は捨てる。
day_summaries: [
  {store: 'saiwaichou', day: d2, racks: 999, judged: 999, won: 0},
  {store: 'saiwaichou', day: d3, racks: 532, judged: 513, won: 190},
  {store: 'saiwaichou', day: prev, racks: 536, judged: 534, won: 201},
  {store: 'saiwaichou', day: `${ym}-04`, racks: 10, judged: 5, won: 6},
]};
const pscube = {format: 'pscube-viewer', version: 1, exported_at: '2026-10-09T06:40:00+09:00', machines: [], records: [
  {store: 'c740601', rate: '20', day: d2, machine: 'ﾏｲｼﾞｬｸﾞﾗｰV', rack: 1, games: 5000, bb: 20, rb: 10, my: 3000, net_medals: 4321},
  {store: 'c740601', rate: '20', day: d2, machine: 'ﾏｲｼﾞｬｸﾞﾗｰV', rack: 2, games: 2000, bb: 5, rb: 3, my: 1000, net_medals: -1200},
]};
const shared = {format: 'database-events', version: 1, kind: 'pscube', events: [
  {store: 'c740601', rate: '20', day: d2, name: '末尾イベ', updated_at: '2026-09-01T00:00:00Z'}]};
// キャラ誕生日：ページと一緒に置くファイルの読み込みを、決まった中身に差し替える（1日：2人、5日：台の無い日に3人）。
const [yy, mm] = ym.split('-').map(Number);
const birthdays = {entries: [
  {month: mm, day: 1, name: 'テスト<i>太郎', work: '作品A'},
  {month: mm, day: 1, name: 'アイウ', work: '作品B'},
  ...['カ', 'キ', 'ク'].map(name => ({month: mm, day: 5, name, work: '作品C'})),
]};
const responses = {'': meruhen, pscube, events: {format: 'database-events', version: 1, kind: 'meruhen', events: []}, 'pscube-events': shared};
const id = 'AKfycbTEST' + 'x'.repeat(40);


responses.rainbow = {marks:[]};
responses['event-history'] = {format:'database-event-history',version:1,base:{version:2,store:'nagamachiminami',symbols:['😀'],weeks:[]}};
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
async function setup(m,p,width=393,initialAux=[]){
 const ctx=await browser.newContext({viewport:{width,height:1100},serviceWorkers:'block'});let fail=false, auxFailed=initialAux;
 await ctx.route('https://script.google.com/**',r=>{const f=new URL(r.request().url()).searchParams.get('file')??'';return r.fulfill({status:200,contentType:'application/json',headers:{'access-control-allow-origin':'*'},body:JSON.stringify(f===''?m:f==='pscube'?(fail?{error:'通信失敗'}:p):auxFailed.includes('bad:'+f)?{marks:'不正',events:'不正',format:'不正'}:auxFailed.includes(f)?{error:'補助通信失敗'}:responses[f]??{error:'no'})});});
 const page=await ctx.newPage();await page.goto(`${pageUrl}#s=${id}`);await page.waitForFunction(()=>!document.querySelector('#reload').disabled && !document.querySelector('#reload').hidden);
 return {ctx,page,setFailure(v){fail=v},setAuxFailures(v){auxFailed=v}};
}
try{
 const m={...meruhen,exported_at:'2026-10-31T12:00:00+09:00'},p={...pscube,exported_at:'2026-10-20T12:00:00+09:00'};
 for(const width of [320,393]){
  const a=await setup(m,p,width);await a.page.waitForSelector('.grid');await a.page.getByRole('button',{name:'P-STATION',exact:true}).click();
  assert.match(await a.page.locator('[data-source-status]').innerText(),/10\/20 12:00/);
  assert.doesNotMatch(await a.page.locator('[data-source-status]').innerText(),/10\/31 12:00/);
  a.setFailure(true);await a.page.locator('#reload').click();await a.page.waitForFunction(()=>!document.querySelector('#reload').disabled);
  assert.match(await a.page.locator('[data-source-status]').innerText(),/更新失敗/);
  assert.ok(await a.page.locator('[role=status]').evaluate(e=>e.getBoundingClientRect().top < document.querySelector('.month-stats').getBoundingClientRect().top));
  a.setFailure(false);await a.page.locator('#reload').click();await a.page.waitForFunction(()=>!document.querySelector('#reload').disabled);
  assert.match(await a.page.locator('[data-source-status]').innerText(),/成功/);
  assert.equal(await a.page.locator('[role=status]').count(),0);
  a.setAuxFailures(['pscube-events','rainbow','event-history']);
  await a.page.locator('#reload').click();await a.page.waitForFunction(()=>!document.querySelector('#reload').disabled);
  assert.match(await a.page.locator('[data-source-status]').innerText(),/成功/);
  const aux=await a.page.locator('[data-aux-warning]').innerText();
  assert.match(aux,/イベント：更新失敗・保存済み/);assert.match(aux,/🌈の印：更新失敗・保存済み/);assert.match(aux,/履歴・顔文字・末尾の印：更新失敗・保存済み/);
  assert.match(await a.page.locator(`[data-open="${d2}"]`).innerText(),/末尾イベ/);
  if(process.env.CALENDAR_PREVIEW_DIR) await a.page.screenshot({path:`${process.env.CALENDAR_PREVIEW_DIR}/aux-failure-${width}.png`});
  a.setAuxFailures([]);await a.page.locator('#reload').click();await a.page.waitForFunction(()=>!document.querySelector('#reload').disabled);assert.equal(await a.page.locator('[data-aux-warning]').count(),0);
  await a.ctx.setOffline(true);await a.page.locator('#reload').click();assert.match(await a.page.locator('[data-source-status]').innerText(),/オフライン/);
  await a.ctx.setOffline(false);await a.page.locator('#reload').click();await a.page.waitForFunction(()=>!document.querySelector('#reload').disabled);
  await a.page.reload();await a.page.waitForSelector('.grid');assert.match(await a.page.locator('[data-source-status]').innerText(),/保存済み/);
  await a.page.locator('#reload').click();await a.page.waitForFunction(()=>!document.querySelector('#reload').disabled);
  if(process.env.CALENDAR_PREVIEW_DIR) { await a.page.screenshot({path:`${process.env.CALENDAR_PREVIEW_DIR}/pstation-${width}.png`}); if(width===393) await a.page.locator('.stage > div.card').screenshot({path:`${process.env.CALENDAR_PREVIEW_DIR}/calendar-grid.png`}); }
  await a.page.getByRole('button',{name:'幸町',exact:true}).click();
  assert.match(await a.page.locator('[data-month-net]').innerText(),/取得分 1日/);
  await a.page.locator('.exchange-info summary').click();assert.match(await a.page.locator('.exchange-info').innerText(),/過去月も現在指定/);
  await a.page.locator('.exchange-info summary').click();
  if(process.env.CALENDAR_PREVIEW_DIR && width===393) await a.page.screenshot({path:`${process.env.CALENDAR_PREVIEW_DIR}/meruhen-${width}.png`});
  await a.page.locator('[data-month-net] .stat-value').evaluate(el=>el.innerHTML='+256,185<small>枚</small>');
  await a.page.addStyleTag({content:'.stat-value{font-size:44px!important}.stat-detail,.exchange-note{font-size:22px!important}'});
  await a.page.waitForTimeout(100);
  assert.ok(await a.page.locator('[data-month-net]').evaluate(e=>e.classList.contains('large-number')));
  assert.ok(await a.page.locator('.month-stats').evaluate(e=>e.scrollWidth<=e.clientWidth));await a.ctx.close();
 }
 const row={store:'saiwaichou',day:d2,machine:'重複確認',rack:1,games:1000,bb:1,rb:1,jo_net:1000};
 const b=await setup({...m,records:[row,{...row}]},{...p,records:[]});await b.page.waitForSelector('.grid');
 assert.match(await b.page.locator('[data-month-net]').innerText(),/\+1,000枚/);assert.match(await b.page.locator('[data-record-issues]').innerText(),/1件として/);await b.ctx.close();
 const c=await setup({...m,records:[row,{...row,jo_net:-1000}],day_summaries:[]},{...p,records:[]});await c.page.waitForSelector('.grid');
 assert.match(await c.page.locator('[data-month-net]').innerText(),/—/);assert.match(await c.page.locator('[data-record-issues]').innerText(),/集計から除外/);if(process.env.CALENDAR_PREVIEW_DIR) await c.page.screenshot({path:`${process.env.CALENDAR_PREVIEW_DIR}/conflict.png`});await c.ctx.close();
 const d=await setup({...m,records:[]},{...p,records:[]});await d.page.waitForSelector('.grid');assert.match(await d.page.locator('[data-month-rate]').innerText(),/13%/);assert.match(await d.page.locator('[data-month-net]').innerText(),/—/);await d.ctx.close();
 const e=await setup({...m,records:[],day_summaries:[]},{...p,records:[]});await e.page.waitForSelector('[role=status]');assert.match(await e.page.locator('#app').innerText(),/表示できるデータがありません/);await e.ctx.close();
 const missing=await setup(m,p,393,['rainbow']);await missing.page.waitForSelector('.grid');assert.match(await missing.page.locator('[data-aux-warning]').innerText(),/保存データなし/);await missing.ctx.close();
 const malformed=await setup(m,p,393,['bad:rainbow','bad:event-history']);await malformed.page.waitForSelector('.grid');assert.match(await malformed.page.locator('[data-aux-warning]').innerText(),/保存データなし/);await malformed.ctx.close();
 const estimatedP={...p,records:[...p.records,{store:'c740601',rate:'20',day:d2,machine:'サイトセブン補完',rack:3,games:6000,bb:20,rb:15,source_site:'site777',net_estimate:{value:1234,sure:true,method:'site777-axis-pixels-v2'}}]};
 const source=await setup(m,estimatedP);await source.page.waitForSelector('.grid');await source.page.getByRole('button',{name:'P-STATION',exact:true}).click();
 assert.match(await source.page.locator('[data-month-net]').innerText(),/推定含む/);
 await source.page.locator(`[data-open="${d2}"]`).click();
 const detail=await source.page.locator('.sheet').innerText();assert.match(detail,/サイトセブンの推定差枚.*グラフ画像/);assert.doesNotMatch(detail,/アナスロのグラフとBB/);
 if(process.env.CALENDAR_PREVIEW_DIR) await source.page.locator('.sheet').evaluate(el=>el.scrollTop=el.scrollHeight);
 if(process.env.CALENDAR_PREVIEW_DIR) await source.page.screenshot({path:`${process.env.CALENDAR_PREVIEW_DIR}/source-explanation.png`});
 await source.ctx.close();
 console.log('PASS: 重複・競合・店舗日時・失敗復旧・保存済み復帰・集計のみ・全件空・文字拡大');
}finally{await browser.close();server.close()}
