// PC pywebview and Android WebView run this same generated page extractor.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');

const script = readFileSync(new URL('../assets/pscube_capture.js', import.meta.url), 'utf8');
const graph = {datas:{
  g:[
    {YMD_biz:20261001,xField:'out-1',yField:'value-1'},
    {YMD_biz:20261002,xField:'out-2',yField:'value-2'},
  ],
  p:[
    {'out-1':0,'value-1':100}, {'out-1':10,'value-1':75},
    {'out-2':10,'value-2':75}, {'out-2':20,'value-2':200},
  ],
}};
// 実ページと同じく、列 i のグラフ枠 svg{i} は CHART-yyyymmdd（サイトの「本日」から1日ずつ前）の中にある。
const charts = (latest, inner = () => '') => Array.from({length:7}, (_, i) => {
  const at = new Date(`${latest}T00:00:00Z`); at.setUTCDate(at.getUTCDate() - i);
  return `<ul id="CHART-${at.toISOString().slice(0, 10).replaceAll('-', '')}"><li><div id="svg${i}">${inner(i)}</div></li></ul>`;
}).join('');
const columns = Array.from({length:7}, (_, i) =>
  `<td class="column"><div>${[
    i ? `${i}日前` : '本日', '3', '1', '0', '0', '600', '120', '0',
  ].map(value => `<div>${value}</div>`).join('')}</div></td>`).join('');
const html = `<html><head><meta charset="utf-8"><title>P'sCUBE｜試験機種</title></head><body>
  <h1>SLOT</h1><h2>台番号 1120</h2>
  <a href="nc-v05-011.php?cd_ps=2&bai=20">全台一覧</a>
  <table><tr>${columns}</tr></table>${charts('2026-10-02')}</body></html>`;
const url = 'https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/cgi-bin/nc-v06-001.php?cd_dai=1120#20261002';
const browser = await chromium.launch({headless:true, executablePath:process.env.CHROMIUM_PATH || undefined, args:['--no-sandbox']});
try {
  const page = await browser.newPage();
  await page.addInitScript(graphData => {
    window.api = {apikey:'test',token:{_i:'test',_t:'test'}};
    window.jQuery = {ajax: options => {
      window.graphRequest = options;
      const request = {
        done(callback) { queueMicrotask(() => callback({Graph:{src:graphData}})); return request; },
        fail() { return request; },
      };
      return request;
    }};
  }, graph);
  await page.route('**/*', route => route.request().isNavigationRequest()
    ? route.fulfill({status:200, contentType:'text/html; charset=utf-8', body:html}) : route.abort());
  await page.goto(url, {waitUntil:'domcontentloaded'});
  const captured = JSON.parse(await page.evaluate(script));
  assert.equal(captured.error, undefined, captured.error);
  assert.equal(captured.records.length, 7);
  assert.equal(captured.records[0].net_medals, 125);
  assert.equal(captured.records[1].net_medals, -25);
  assert.equal(captured.records[0].my, 120);
  assert.equal(captured.records[2].net_medals, undefined);
  const request = await page.evaluate(() => ({url:window.graphRequest.url, data:window.graphRequest.data}));
  assert.equal(request.url, 'nc-m06-003.php');
  assert.equal(request.data.cd_dai, '1120');
  assert.equal(request.data.YMD_biz, '20261002');
  const captureGraph = async graphData => {
    await page.evaluate(value => {
      window.jQuery.ajax = () => {
        const request = {
          done(callback) { queueMicrotask(() => callback({Graph:{src:value}})); return request; },
          fail() { return request; },
        }; return request;
      };
    }, graphData);
    return JSON.parse(await page.evaluate(script));
  };
  // 別日が空・1点・不正でも、正常日の正確な差枚と既存の数値は返す。
  for (const oldPoints of [[],[{'out-1':0,'value-1':100}],[{'out-1':0,'value-1':NaN}]]) {
    const partial=await captureGraph({datas:{g:graph.datas.g,p:[...oldPoints,...graph.datas.p.slice(2)]}});
    assert.equal(partial.records[0].net_medals,125);
    assert.equal(partial.records[1].net_medals,undefined);
    assert.equal(partial.records[0].my,120);
    assert.equal(partial.net_warning,undefined);
  }
  // 選択日の点が無い場合も、正常な過去日の差枚は保存用データに残す。
  const missingSelected=await captureGraph({datas:{g:graph.datas.g,p:graph.datas.p.slice(0,2)}});
  assert.equal(missingSelected.records[0].net_medals,undefined);
  assert.equal(missingSelected.records[1].net_medals,-25);
  assert.match(missingSelected.net_warning,/選択日のグラフ/);
  const allMissing=await captureGraph({datas:{g:graph.datas.g,p:[]}});
  assert.ok(allMissing.records.every(r=>r.net_medals==null));
  assert.match(allMissing.net_warning,/選択日のグラフ/);
  await page.evaluate(() => {
    window.jQuery.ajax = () => {
      const request = {
        done() { return request; },
        fail(callback) { queueMicrotask(() => callback({status:403})); return request; },
      };
      return request;
    };
  });
  // 差枚の元データが取れなくても、台別の数値・グラフは保存用に返す。差枚は空欄（0にしない）で理由を付ける。
  const failed = JSON.parse(await page.evaluate(script));
  assert.equal(failed.error, undefined, failed.error);
  assert.equal(failed.records.length, 7);
  assert.ok(failed.records.every(r => r.net_medals === undefined || r.net_medals === null));
  assert.equal(failed.records[0].my, 120);
  assert.match(failed.net_warning, /差枚は未取得：通信に失敗しました（HTTP 403）/);
  assert.equal(failed.source_url, url);
  // 形式の違う応答・サイトの通信の準備ができていない場合も同じ。
  await page.evaluate(() => {
    window.jQuery.ajax = () => {
      const request = {
        done(callback) { queueMicrotask(() => callback({Graph:{src:{datas:{g:[], p:[]}}}})); return request; },
        fail() { return request; },
      };
      return request;
    };
  });
  const malformed = JSON.parse(await page.evaluate(script));
  assert.equal(malformed.records.length, 7);
  assert.match(malformed.net_warning, /差枚は未取得：P’s CUBEのグラフJSONではありません/);
  await page.evaluate(() => { delete window.api; });
  const unready = JSON.parse(await page.evaluate(script));
  assert.equal(unready.records.length, 7);
  assert.match(unready.net_warning, /差枚は未取得：サイトの通信の準備ができていません/);
  await page.close();
  console.log('PASS: PC/Android rack capture saves exact net values; source failures keep the rack data with net left empty');
} finally { await browser.close(); }
