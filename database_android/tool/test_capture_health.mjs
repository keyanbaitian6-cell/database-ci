import test from 'node:test';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {validateData,mergeData,mergeNetSupplement} from '../web/pscube/data.mjs';
import {makeNetProbe,validateNetCapture,trimNetProbes,netCaptureLabel,viewerNetCapture,NET_PROBE_BUDGET,makeSyncWrite,mergeSyncStatus} from '../web/capture_health.mjs';
import {reanalyseNetCaptures} from '../web/pscube/graph_probe.mjs';
const fixture=()=>{
  const d=JSON.parse(readFileSync(new URL('../../database/tests/fixtures/pscube_net_capture.json',import.meta.url),'utf8'));
  d.records[0].net_capture.checked_at=new Date().toISOString();return d;
};
test('取得診断と数値を保持し、認証情報・HTML・任意の項目を持ち出さない',()=>{
  const d=fixture(),cap=d.records[0].net_capture;
  cap.secret='credential-sentinel';cap.probe.graph.apiKey='credential-sentinel';
  cap.probe.graph.datas.p[0].token='credential-sentinel';
  const saved=validateData(d);
  assert.equal(saved.records[0].net_capture.status,'invalid');
  assert.equal(JSON.stringify(saved).includes('credential-sentinel'),false);
  assert.deepEqual(validateData(saved),saved);
  const raw=makeNetProbe({...cap.probe},d.records);assert.ok(raw.probe);
});
test('0枚・欠測・通信失敗を区別し、台と数値が異なる診断を拒否する',()=>{
  const d=fixture(),r=d.records[0];
  assert.equal(netCaptureLabel({...r,net_medals:0}),'取得済み（0枚）');
  assert.equal(netCaptureLabel({...r,net_capture:{reason:'network'}}),'差枚の通信失敗');
  assert.equal(netCaptureLabel({...r,net_capture:null}),'未取得（理由未記録）');
  assert.throws(()=>validateData({...d,records:[{...r,games:301}]}));
  assert.throws(()=>validateNetCapture({...r.net_capture,http_status:900}));
});
test('元数値の7日・容量上限を適用しても台の記録は減らさない',()=>{
  const r=fixture().records[0],now=Date.now();
  const expired=structuredClone(r);expired.net_capture.checked_at=new Date(now-8*86400000).toISOString();
  trimNetProbes([expired],now);assert.equal(expired.net_capture.probe,undefined);assert.equal(expired.games,r.games);
  const huge=structuredClone(r.net_capture.probe);huge.graph.datas.p=Array.from({length:5000},(_,i)=>({'out-2':i,'value-2':i}));
  assert.equal(makeNetProbe(huge,[r]).probe_omitted,'size');
  const sample=structuredClone(r);sample.net_capture.probe.graph.datas.p=Array.from({length:1200},(_,i)=>({'out-2':i,'value-2':i}));
  const rows=Array.from({length:100},()=>structuredClone(sample));trimNetProbes(rows,now);
  assert.equal(rows.length,100);assert.ok(rows.some(x=>x.net_capture.probe_omitted==='budget'));
  assert.ok(rows.reduce((n,x)=>n+(x.net_capture.probe ? JSON.stringify(x.net_capture.probe).length : 0),0)<=NET_PROBE_BUDGET);
});
test('同じ数値の再読込では新しい診断を保持し、元数値から欠測だけ再解析する',()=>{
  const old=fixture(),fresh=structuredClone(old);delete fresh.records[0].net_capture;
  assert.deepEqual(mergeData(old,fresh).records[0].net_capture,old.records[0].net_capture);
  const result=reanalyseNetCaptures(old);assert.equal(result.filled,1);assert.equal(result.data.records[0].net_medals,250);
  assert.equal(old.records[0].net_medals,null);assert.equal(result.data.records[0].games,300);
  const known=fixture();known.records[0].net_medals=777;
  assert.equal(reanalyseNetCaptures(known).data.records[0].net_medals,777);
});
test('スマホ補完は一致する既存記録の欠測だけ。正常値・数値・機種タイプ・イベントは保持する',()=>{
  const old=fixture(),fresh=fixture();fresh.records[0].net_medals=250;
  const result=mergeNetSupplement(old,fresh);assert.equal(result.records[0].net_medals,250);
  old.records[0].net_medals=0;assert.equal(mergeNetSupplement(old,fresh).records[0].net_medals,0);
  old.records[0].net_medals=null;fresh.records[0].games++;delete fresh.records[0].net_capture;
  assert.equal(mergeNetSupplement(old,fresh).records[0].net_medals,undefined);
  assert.equal(mergeNetSupplement({...old,records:[]},fresh).records.length,0);
});
test('書き出し元とGoogleの処理時刻を分け、古い出力で新しい状態を巻き戻さない',()=>{
  const rows=fixture().records,at=new Date().toISOString();
  const status=makeSyncWrite('pc',at,rows);
  assert.equal(status.writes[0].stores[0].day,'2026-10-01');
  const old=makeSyncWrite('pc','2020-01-01T00:00:00Z',rows);
  assert.equal(mergeSyncStatus(status,old).writes[0].at,at);
  assert.equal(makeSyncWrite('cloud',at,rows),null);
});

test('再解析コマンドは新規バックアップだけを確定し、元ファイル・既存出力を上書きしない',async()=>{
  const fs=await import('node:fs/promises'),os=await import('node:os'),path=await import('node:path');
  const {spawnSync}=await import('node:child_process');
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'pscube-reanalyse-'));
  try {
    const input=path.join(dir,'input.json'),output=path.join(dir,'output.json'),text=JSON.stringify(fixture());
    await fs.writeFile(input,text);
    const run=()=>spawnSync(process.execPath,[fileURLToPath(new URL('./reanalyse_pscube_net.mjs',import.meta.url)),input,output],{encoding:'utf8'});
    const first=run();assert.equal(first.status,0,first.stderr);
    const out=JSON.parse(await fs.readFile(output,'utf8'));
    assert.equal(out.source,'browser');assert.equal(out.records[0].net_medals,250);
    assert.equal(await fs.readFile(input,'utf8'),text);
    const saved=await fs.readFile(output,'utf8'),second=run();
    assert.equal(second.status,1);assert.match(second.stderr,/既に存在/);
    assert.equal(await fs.readFile(output,'utf8'),saved);
    assert.deepEqual((await fs.readdir(dir)).sort(),['input.json','output.json']);
  } finally {await fs.rm(dir,{recursive:true,force:true});}
});

test('軽量データを繰り返し書き出しても原本の有無を失わず、店舗の最新日件数を数える',()=>{
  const cap=fixture().records[0].net_capture;
  assert.equal(viewerNetCapture(viewerNetCapture(cap)).probe_available,true);
  const rows=fixture().records,old={...rows[0],day:'2026-09-30'};
  const status=makeSyncWrite('pc',new Date().toISOString(),[old,...rows,old]);
  assert.equal(status.writes[0].stores[0].day,'2026-10-01');
  assert.equal(status.writes[0].stores[0].count,1);
});
