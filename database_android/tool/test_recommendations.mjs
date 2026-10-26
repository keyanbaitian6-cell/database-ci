import assert from 'node:assert/strict';
import test from 'node:test';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {RECOMMENDATION_DEFAULT,recommendationPlan,recommendationDays,recommendationCandidates,recommendationRows,recommendationFace,mergeRecommendations,recommendationResult,mergeRecommendationResults,recommendationResultValue} from '../../share_viewer/recommendations.mjs';

test('4機種と月曜開始の7日間だけを受け付け、他店舗・不正時刻は保存しない',()=>{
  assert.equal(recommendationDays('2026-10-26').at(-1),'2026-11-01');
  for(const change of [{machines:['A','A','B','C']},{machines:['A','B','C']},{store:'saiwaichou'},{week:'2026-10-27'},{updated_at:'2026-02-30T00:00:00Z'},{updated_at:'2026-10-25T24:00:00Z'}]) assert.throws(()=>recommendationPlan({...RECOMMENDATION_DEFAULT,...change}));
});
test('マイクロ秒・別週・不正原文を保ち、新しい4枠をまとめて採用する',()=>{
  const a={...RECOMMENDATION_DEFAULT,updated_at:'2026-10-25T09:00:00.123456+09:00'},b={...a,machines:['A','B','C','D'],updated_at:'2026-10-25T00:00:00.123457Z'},other={...a,week:'2026-11-02'},raw={壊れた原文:true};
  assert.deepEqual(mergeRecommendations([a,other,raw],[b]),[other,b,raw]);
  assert.deepEqual(mergeRecommendations([b],[a]),[b]);
});
test('7台以上の候補は最新1日の異なる台番号で数え、他店舗・未来を混ぜない',()=>{
  const rows=['7台','6台'].flatMap((machine,j)=>Array.from({length:j?6:7},(_,rack)=>({store:'nagamachiminami',day:'2026-10-25',machine,rack})));
  rows.push(...Array(10).fill(rows.at(-1)),...rows.map(r=>({...r,store:'saiwaichou',machine:'他店'})),...rows.map(r=>({...r,day:'2026-11-02',machine:'未来'})));
  assert.deepEqual(recommendationCandidates(rows,'2026-10-26'),{day:'2026-10-25',machines:[{name:'7台',count:7}]});
});
test('空の日があっても台ごとの0枚・正負・欠測を区別して表示する',()=>{
  const row={store:'nagamachiminami',day:'2026-10-26',machine:'機種 A',rack:10,net:0};
  const rows=[row,{...row,day:'2026-10-28',machine:'機種+A',net:3000},{...row,store:'saiwaichou',rack:999},{...row,machine:'別機種',rack:888}];
  const result=recommendationRows(rows,'2026-10-26','機種 A');
  assert.equal(result.length,1);assert.equal(result[0].rack,10);assert.equal(result[0].cells[0].net,0);assert.equal(result[0].cells[1],null);assert.equal(result[0].cells[2].net,3000);
  rows.push({...row,net:9999});assert.equal(recommendationRows(rows,'2026-10-26','機種 A')[0].cells[0],null);
  assert.deepEqual([null,NaN,-1,0,999,1000,2999,3000].map(recommendationFace),['','','🥶','😌','😌','😀','😀','😍']);
});
test('PCと共有で初回4機種・週・不正な原文を含む合流結果が一致する',()=>{
  const a={...RECOMMENDATION_DEFAULT,updated_at:'2026-10-25T09:00:00.123456+09:00'},b={...a,machines:['A','B','C','D'],updated_at:'2026-10-25T00:00:00.123457Z'},raw={壊れた原文:true};
  const code='import json,sys;import recommendations as r;p=json.load(sys.stdin);print(json.dumps(dict(default=r.DEFAULT,merged=r.merge(p["old"],p["new"])),ensure_ascii=False))';
  const result=JSON.parse(execFileSync(process.env.PYTHON||'python',['-c',code],{cwd:fileURLToPath(new URL('../../database/',import.meta.url)),input:JSON.stringify({old:[a,raw],new:[b]}),encoding:'utf8'}));
  assert.deepEqual(result,{default:RECOMMENDATION_DEFAULT,merged:mergeRecommendations([a,raw],[b])});
});

test('台ごとの顔文字は空欄と自動への復帰を区別し、不正な原文は保持する',()=>{
  const r={store:'nagamachiminami',week:'2026-10-26',machine:'A',rack:100,day:'2026-10-26',value:'😇',updated_at:'2026-10-25T00:00:00.123456Z',device:'shared'};
  const blank={...r,value:'',updated_at:'2026-10-25T00:00:00.123457Z'},auto={...r,value:null,updated_at:'2026-10-25T00:00:00.123458Z'},raw={壊れた原文:true};
  assert.equal(recommendationResultValue([r],r,'😌'),'😇');
  assert.equal(recommendationResultValue(mergeRecommendationResults([r],[blank]),r,'😌'),'');
  assert.equal(recommendationResultValue(mergeRecommendationResults([blank],[auto]),r,'😌'),'😌');
  assert.deepEqual(mergeRecommendationResults([r,raw],[blank]),[blank,raw]);
  for(const change of [{value:'未知'},{rack:1.5},{day:'2026-11-02'},{updated_at:'2026-02-30T00:00:00Z'}])assert.throws(()=>recommendationResult({...r,...change}));
  for(const key of ['store','week','machine','rack','day','value','updated_at']){const raw={...r};delete raw[key];assert.throws(()=>recommendationResult(raw));}
});

test('小数秒6桁をDate.parseが扱わなくても編集順を失わず、不正原文のキーで停止しない',()=>{
  const original=Date.parse;
  try {
    Date.parse=s=>/\.\d{4,6}(?:Z|[+-])/.test(String(s))?NaN:original(s);
    const a={...RECOMMENDATION_DEFAULT,updated_at:'2026-10-25T00:00:00.123456Z'};
    const b={...a,machines:['A','B','C','D'],updated_at:'2026-10-25T00:00:00.123457Z'};
    assert.deepEqual(mergeRecommendations([a],[b]),[b]);
  } finally {Date.parse=original;}
});
