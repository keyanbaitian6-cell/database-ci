import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {parsePrivateHistory, historySavedName} from '../../share_viewer/event_history.mjs';
import {fetchShared} from '../web/shared_events.mjs';

const base = JSON.parse(await fs.readFile(new URL('../assets/event_history.json', import.meta.url), 'utf8'));
const doc = () => ({format:'database-event-history',version:1,base:structuredClone(base),cells:[],weeks:[],links:[]});
const cell = (value = '', updated_at = '2026-10-19T00:00:00Z') => ({store:'nagamachiminami',type:'半列',week:'2026-08-24',machine:base.weeks[0].machines[0].name,day:'2026-08-24',value,updated_at});

test('空欄への編集、異なるセル、サーバー文書の時刻順を保持', () => {
  const d=doc(); d.cells=[cell('😀'),cell('', '2026-10-19T00:00:01Z'),{...cell('😍'),day:'2026-08-25'}];
  const week=parsePrivateHistory(d).weeks.find(w=>w.from==='2026-08-24');
  assert.deepEqual(week.machines[0].results.slice(0,2),['','😍']);
});
test('未知の記号・週・機種・他店・週外の日付は表示しない', () => {
  const d=doc(); d.cells=[cell('任意文字列'),{...cell(),week:'2026-10-12'},{...cell(),machine:'別機種'},{...cell(),store:'saiwaichou'},{...cell(),day:'2026-09-01'}];
  const parsed=parsePrivateHistory(d);
  assert.equal(parsed.rejected,5);
  assert.equal(parsed.weeks.find(w=>w.from==='2026-08-24').machines[0].results[0],'😀');
});
test('私有の基準がない応答・週の重複・任意記号の基準を拒否', () => {
  assert.throws(()=>parsePrivateHistory({format:'database-event-history',version:1}),/PC/);
  const d=doc(); d.base.weeks.push(d.base.weeks[0]); assert.throws(()=>parsePrivateHistory(d),/重複/);
  const broken=doc(); broken.base.weeks[0].machines[0].results[0]='任意文字列'; assert.throws(()=>parsePrivateHistory(broken),/記号/);
});
test('バラエティの保存した構成・分類日・結果を表示', () => {
  const d=doc();d.weeks=[{store:'nagamachiminami',type:'バラエティ',week:'2026-10-12',lineup_day:'2026-10-13',machines:[{name:'機種A',record_name:'保存名A',count:2}],updated_at:'2026-10-19T00:00:00Z',removed:false}];
  d.cells=[{...cell('😍'),type:'バラエティ',week:'2026-10-12',machine:'機種A',day:'2026-10-13'}];
  const w=parsePrivateHistory(d).weeks[0];
  assert.equal(w.lineup_day,'2026-10-13');assert.equal(w.machines[0].results[1],'😍');
});
test('機種名を推測で結び付けず、確認した保存名を使う', () => {
  const m={name:'L甲鉄城のカバネリ',record_name:null};
  assert.equal(historySavedName(m,new Set(['L 甲鉄城のｶﾊﾞﾈﾘ'])),null);
  m.record_name='L 甲鉄城のｶﾊﾞﾈﾘ';
  assert.equal(historySavedName(m,new Set([m.record_name])),m.record_name);
  assert.equal(historySavedName(m,new Set()),null);
});

test('iPhone用の通信部品も履歴のGETを許可し、未知のファイルは断る', async () => {
  const url='https://script.google.com/macros/s/TEST/exec';
  const calls=[];
  const result=await fetchShared(url,'event-history',async (input,options)=>{
    calls.push([input,options?.method??'GET']);return {ok:true,text:async()=>'{"fixture":true}'};
  });
  assert.equal(result,'{"fixture":true}');
  assert.deepEqual(calls,[[url+'?file=event-history','GET']]);
  await assert.rejects(fetchShared(url,'unknown-file'),/不正/);
});


test('共通JSONの週・記号・除外件数がPythonとDartに一致', async()=>{
  const d=JSON.parse(await fs.readFile(new URL('../test/fixtures/event_history_cases.json',import.meta.url),'utf8'));
  const parsed=parsePrivateHistory(d);
  assert.deepEqual({rejected:parsed.rejected,weeks:parsed.weeks.map(w=>({type:w.type,from:w.from,results:w.machines.map(m=>m.results),links:w.machines.map(m=>m.record_name)}))},d.expected);
});
test('マイクロ秒で編集を比較し、時差表記とZを同じ時間軸で扱う',()=>{
  const d=doc();d.cells=[cell('😍','2026-10-19T09:00:00.123457+09:00'),cell('😌','2026-10-19T00:00:00.123456Z')];
  assert.equal(parsePrivateHistory(d).weeks.find(w=>w.from==='2026-08-24').machines[0].results[0],'😍');
});
