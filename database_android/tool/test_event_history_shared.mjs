import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {mergeRecommendations, RECOMMENDATION_DEFAULT, mergeRecommendationResults} from '../../share_viewer/recommendations.mjs';
import {parsePrivateHistory,mergeHistoryCells,newHistoryCell,historyEditKey} from '../../share_viewer/event_history.mjs';

const doc=()=>({format:'database-event-history',version:1,base:{version:2,store:'nagamachiminami',symbols:['😀','😍'],weeks:[
  {type:'バラエティ',from:'2026-10-19',to:'2026-10-25',machines:[{name:'共有テスト機種',count:1,results:Array(7).fill('')}]},
]},cells:[],weeks:[],links:[]});
const entry=(value='😀',updated_at='2026-10-20T00:00:00.123456Z')=>({store:'nagamachiminami',type:'バラエティ',week:'2026-10-19',machine:'共有テスト機種',day:'2026-10-19',value,updated_at,device:'shared'});

test('新しい編集だけを重ね、空欄・マイクロ秒・原文を保持する',()=>{
  const d=doc(); d.cells=[entry('😀'),{broken:true}];
  const merged=mergeHistoryCells(d,[entry('😍','2026-10-20T00:00:00.123455Z')]);
  assert.equal(parsePrivateHistory(merged).weeks[0].machines[0].results[0],'😀');
  assert.equal(parsePrivateHistory(merged).rejected,1);
  const blank=mergeHistoryCells(merged,[entry('','2026-10-20T00:00:00.123457Z')]);
  assert.equal(parsePrivateHistory(blank).weeks[0].machines[0].results[0],'');
  assert.deepEqual(d.cells,[entry('😀'),{broken:true}]);
  const next=newHistoryCell(blank,entry(),'😍',Date.parse('2026-10-20T00:00:00.123Z'));
  assert.equal(next.updated_at,'2026-10-20T00:00:00.124457Z');
  assert.equal(next.device,'shared');
});

test('未知の記号・機種・週・日付・他店舗では保存しない',()=>{
  for(const change of [{value:'未定義'},{machine:'別機種'},{week:'2026-10-12'},{day:'2026-10-26'},{store:'saiwaichou'}])
    assert.throws(()=>mergeHistoryCells(doc(),[{...entry(),...change}]));
});

test('Apps Scriptが検証元のコードと一致する',()=>{
  execFileSync(process.execPath,[fileURLToPath(new URL('build_event_history_share.mjs',import.meta.url)),'--check']);
});

test('Apps Scriptの保存時パーサーが拒否するBigIntリテラルを含めない',async()=>{
  for(const script of ['viewer_drive_script.gs','viewer_drive_script_readonly.gs']) {
    const source=await fs.readFile(new URL(script,import.meta.url),'utf8');
    assert.doesNotMatch(source,/\b\d+n\b/);
  }
});

async function drive(name) {
  const files=new Map(),writes=[];
  let locks=0;
  const make=(name,text)=>({text,getLastUpdated:()=>new Date(1000),isTrashed:()=>false,getBlob(){return {getDataAsString:()=>this.text};},
    setContent(value){this.text=value;writes.push(name);},getParents:()=>({hasNext:()=>true,next:()=>folder})});
  const folder={createFile(name,text){const f=make(name,text);files.set(name,f);writes.push(name);return f;}};
  files.set('database-event-history.json',make('database-event-history.json',JSON.stringify(doc())));
  class Clock extends Date { static now(){return Date.parse('2026-10-21T00:00:00Z');} }
  const sandbox={DriveApp:{getFilesByName(name){const f=files.get(name);let done=false;return {hasNext:()=>!done&&!!f,next(){done=true;return f;}};},getRootFolder:()=>folder},
    LockService:{getScriptLock:()=>({waitLock(){locks++;},releaseLock(){locks--;}})},
    ContentService:{MimeType:{JSON:'json'},createTextOutput:body=>({body,setMimeType(){return this;}})},console:{log(){}},JSON,Date:Clock};
  vm.createContext(sandbox);
  const source=process.env.HISTORY_COMPAT_DIR ? `${process.env.HISTORY_COMPAT_DIR}/${name}` : new URL(name,import.meta.url);
  vm.runInContext(await fs.readFile(source,'utf8'),sandbox);
  return {files,writes,get:()=>JSON.parse(sandbox.doGet({parameter:{file:'event-history'}}).body),
    postResults:recommendation_results=>JSON.parse(sandbox.doPost({postData:{contents:JSON.stringify({file:'event-history',cells:[],recommendation_results})}}).body),
    postPlans:recommendations=>JSON.parse(sandbox.doPost({postData:{contents:JSON.stringify({file:'event-history',cells:[],recommendations})}}).body),
    post:cells=>JSON.parse(sandbox.doPost({postData:{contents:JSON.stringify({file:'event-history',cells})}}).body),locks:()=>locks};
}

for(const script of ['viewer_drive_script.gs','viewer_drive_script_readonly.gs']) {
  test(`${script}：4機種の構成変更は拒否し、台ごとの顔文字だけを保存する`,async()=>{
    const d=await drive(script),original=d.files.get('database-event-history.json').text;
    const plan={...RECOMMENDATION_DEFAULT,updated_at:'2026-10-20T00:00:00Z'};
    assert.match(d.postPlans([plan]).error,/機種構成はPC/);assert.deepEqual(d.writes,[]);
    const r={store:'nagamachiminami',week:plan.week,machine:plan.machines[0],rack:100,day:'2026-10-26',value:'😇',updated_at:'2026-10-20T00:00:00.123456Z',device:'shared'};
    assert.equal(d.postResults([r]).ok,true);assert.equal(d.get().recommendations_editing,false);assert.equal(d.get().recommendation_results_editing,true);
    assert.deepEqual(d.get().recommendation_results,[r]);
    assert.equal(d.post([entry()]).ok,true);assert.deepEqual(d.get().recommendation_results,[r]);
    const next={...r,day:'2026-10-27',value:''};assert.equal(d.postResults([next]).ok,true);
    const newer={...r,value:'😍',updated_at:'2026-10-20T00:00:00.123457Z'};
    const pc=JSON.parse(original);pc.recommendation_results=[newer];d.files.get('database-event-history.json').text=JSON.stringify(pc);
    assert.equal(d.postResults([r]).ok,true);assert.deepEqual(d.get().recommendation_results,mergeRecommendationResults([newer],[r,next]));
    assert.deepEqual(JSON.parse(d.files.get('database-event-history.json').text),pc);assert.ok(d.writes.every(n=>n==='database-event-history-shared.json'));
    assert.equal(d.locks(),0);
  });
  test(`${script}：不正な台別結果・未来時刻・壊れた原文を保存しない`,async()=>{
    const d=await drive(script),r={store:'nagamachiminami',week:'2026-10-26',machine:RECOMMENDATION_DEFAULT.machines[0],rack:100,day:'2026-10-26',value:'😇',updated_at:'2026-10-20T00:00:00Z'};
    for(const change of [{store:'saiwaichou'},{week:'2026-10-27'},{machine:'未選定機種'},{day:'2026-11-02'},{value:'未知'},{rack:1.5},{updated_at:'2026-10-30T00:00:00Z'},{updated_at:'2026-02-30T00:00:00Z'}]) assert.ok(d.postResults([{...r,...change}]).error);
    assert.deepEqual(d.writes,[]);assert.ok(d.postResults([r,{...r,value:'不正'}]).error);assert.deepEqual(d.writes,[]);
    assert.equal(d.postResults([r]).ok,true);
    const shared=d.files.get('database-event-history-shared.json'),broken=JSON.stringify({...JSON.parse(shared.text),recommendation_results:'壊れた原文'});shared.text=broken;
    const count=d.writes.length;assert.ok(d.postResults([r]).error);assert.equal(shared.text,broken);assert.equal(d.writes.length,count);assert.equal(d.locks(),0);
  });
  test(`${script}：PCの幸町をGETで保持し、共有からは書き換えない`,async()=>{
    const d=await drive(script);
    const sample=JSON.parse(await fs.readFile(new URL('../test/fixtures/saiwaichou_history_cases.json',import.meta.url),'utf8'));
    const pc={...doc(),saiwaichou_variety:sample.saiwaichou_variety};
    d.files.get('database-event-history.json').text=JSON.stringify(pc);
    assert.deepEqual(d.get().saiwaichou_variety,pc.saiwaichou_variety);
    assert.equal(d.post([entry()]).ok,true);
    assert.deepEqual(d.get().saiwaichou_variety,pc.saiwaichou_variety);
    const before=d.writes.length;
    assert.ok(d.post([sample.saiwaichou_variety.cells[0]]).error);
    assert.equal(d.writes.length,before);
    assert.deepEqual(JSON.parse(d.files.get('database-event-history.json').text),pc);
  });
  test(`${script}：記号保存・再取得・PCの再出力・新しい編集を保持する`,async()=>{
    const d=await drive(script), original=d.files.get('database-event-history.json').text;
    assert.equal(d.get().shared_editing,true);
    const a=d.post([entry()]);assert.equal(a.ok,true);
    const b=d.post([{...entry('😍'),day:'2026-10-20'}]);assert.equal(b.ok,true);
    assert.deepEqual(parsePrivateHistory(d.get()).weeks[0].machines[0].results.slice(0,2),['😀','😍']);
    assert.equal(d.files.get('database-event-history.json').text,original);
    assert.ok(d.writes.every(n=>n==='database-event-history-shared.json'));
    const newer=doc();newer.cells=[entry('😍','2026-10-20T00:00:00.123457Z')];
    d.files.get('database-event-history.json').text=JSON.stringify(newer);
    const stale=d.post([entry()]);assert.equal(stale.keptNewer,1);
    assert.equal(parsePrivateHistory(d.get()).weeks[0].machines[0].results[0],'😍');
    const blank=d.post([entry('','2026-10-20T00:00:00.123458Z')]);assert.equal(blank.ok,true);
    assert.equal(parsePrivateHistory(d.get()).weeks[0].machines[0].results[0],'');
    assert.equal(d.locks(),0);
  });
  test(`${script}：不正な編集と破損した共有ファイルは書き換えない`,async()=>{
    const d=await drive(script);
    for(const cells of [[],Array(101).fill(entry()),[{...entry(),machine:'別機種'}],[{...entry(),value:'未知'}],[entry('😀','9999-01-01T00:00:00Z')]])
      assert.ok(d.post(cells).error);
    assert.deepEqual(d.writes,[]);
    const mixed=d.post([entry(),{...entry(),machine:'今の週表にない機種'}]);
    assert.match(mixed.error,/対象の週・機種・日付/);
    assert.deepEqual(d.writes,[],'一部不正の一括送信は勝手に一部だけ保存しない');
    assert.equal(d.post([entry()]).ok,true);
    const shared=d.files.get('database-event-history-shared.json');shared.text='{壊れた';
    const before=d.writes.length;
    assert.ok(d.post([entry('😍')]).error);
    assert.equal(shared.text,'{壊れた');assert.equal(d.writes.length,before);assert.equal(d.locks(),0);
  });
}
