import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {parsePrivateHistory, mergeHistoryCells, historyGradeGap} from '../../share_viewer/event_history.mjs';
import {saiwaichouMachineNet, saiwaichouGrade, saiwaichouGapEnd, saiwaichouGap} from '../../share_viewer/data.mjs';

test('自動の優・良は全台の差枚と週表の台数がそろう日だけ（PC・閲覧ページと同じ境界）',()=>{
  const r=net=>({net});
  assert.equal(saiwaichouMachineNet([r(2000),r(500)],2),2500);
  assert.equal(saiwaichouMachineNet([r(2000)],2),null,'台数不足');
  assert.equal(saiwaichouMachineNet([r(2000),r(null)],2),null,'差枚不明の台');
  assert.equal(saiwaichouMachineNet([],1),null,'記録なし');
  for(const [total,grade] of [[-1,''],[0,'良'],[2499,'良'],[2500,'優'],[null,'']]) assert.equal(saiwaichouGrade(total),grade);
});

test('赤字は今日を除いた直前5日に+800枚を超えた日も優も無い機種',()=>{
  const nets={}, grades={};
  const gap=(end='2026-10-20')=>saiwaichouGap(end,d=>({net:nets[d]??null,grade:grades[d]??''}));
  assert.equal(gap(),true,'記録なし・差枚不明は超えていないと数える');
  nets['2026-10-16']=801; assert.equal(gap(),false,'5日目の+801枚');
  delete nets['2026-10-16']; nets['2026-10-20']=800; assert.equal(gap(),true,'+800枚ちょうどは超えていない');
  nets['2026-10-15']=9000; nets['2026-10-21']=9000; assert.equal(gap(),true,'範囲外の日は見ない');
  grades['2026-10-18']='良'; assert.equal(gap(),true);
  grades['2026-10-18']='優'; assert.equal(gap(),false,'手入力の優は超えた日と数える');
  assert.equal(gap(null),false,'記録のない週を赤くしない');
  const now=Date.parse('2026-10-28T16:00:00Z'); // 日本時間10/29 1:00
  assert.equal(saiwaichouGapEnd('2026-10-29',now),'2026-10-28','今日（日本時間）は含めない');
  assert.equal(saiwaichouGapEnd('2026-10-25',now),'2026-10-25');
  assert.equal(saiwaichouGapEnd(null,now),null);
});

test('赤字は最終記録日までの5暦日で判定し、前週・境界・空欄・未来・対応名を区別する',()=>{
  const machine={name:'機種A',record_name:'保存名A'};
  const weeks=[{type:'バラエティ',from:'2026-10-12',to:'2026-10-18',machines:[{...machine,results:Array(7).fill('')}]},
    {type:'バラエティ',from:'2026-10-19',to:'2026-10-25',machines:[{...machine,results:Array(7).fill('')}]}];
  assert.equal(historyGradeGap(weeks,machine,'2026-10-20'),true);
  weeks[0].machines[0].results[4]='良'; // 10/16は直近5暦日に含む。
  assert.equal(historyGradeGap(weeks,machine,'2026-10-20'),false);
  weeks[0].machines[0].name='旧表示名';
  assert.equal(historyGradeGap(weeks,machine,'2026-10-20'),false,'明示した保存名で前週と対応');
  weeks[0].machines[0].results[4]=''; weeks[0].machines[0].results[3]='優';
  weeks[1].machines[0].results[2]='良';
  assert.equal(historyGradeGap(weeks,machine,'2026-10-20'),true,'5日前の優と翌日の良は対象外');
  weeks[1].machines[0].results[1]='良';
  assert.equal(historyGradeGap(weeks,machine,'2026-10-20'),false,'最終記録日の良を含む');
  assert.equal(historyGradeGap(weeks,{name:'別機種'},'2026-10-20'),true);
  assert.equal(historyGradeGap(weeks,machine,null),false,'記録なしの週を赤くしない');
});

const doc=JSON.parse(await fs.readFile(new URL('../test/fixtures/saiwaichou_history_cases.json',import.meta.url),'utf8'));

test('幸町の結果・除外件数と店舗分離がPython・Dartに一致する',()=>{
  const parsed=parsePrivateHistory(doc.saiwaichou_variety,'saiwaichou');
  assert.equal(parsed.rejected,doc.expected.rejected);
  assert.deepEqual(parsed.weeks[0].machines.map(m=>m.results),doc.expected.results);
  assert.equal(parsePrivateHistory(doc).weeks[0].machines[0].results[0],'😍');
  assert.throws(()=>parsePrivateHistory(doc,'saiwaichou'),/基準/);
});

test('幸町の顔文字・3台機種・別イベントの基準を受け入れない',()=>{
  const base=doc.saiwaichou_variety.base;
  assert.throws(()=>parsePrivateHistory({...doc.saiwaichou_variety,base:{...base,symbols:['😍']}},'saiwaichou'),/優・良/);
  const bad={...base,weeks:[{type:'バラエティ',from:'2026-10-19',to:'2026-10-25',machines:[{name:'機種A',count:3,results:Array(7).fill('')}]}]};
  assert.throws(()=>parsePrivateHistory({...doc.saiwaichou_variety,base:bad},'saiwaichou'),/1〜2台/);
  assert.throws(()=>parsePrivateHistory({...doc.saiwaichou_variety,base:{...bad,weeks:[{...bad.weeks[0],type:'半列'}]}},'saiwaichou'),/週/);
});

test('共有の顔文字編集は幸町を保持し、幸町への書き込みを拒否する',()=>{
  const merged=mergeHistoryCells(doc,[]);
  assert.deepEqual(merged.saiwaichou_variety,doc.saiwaichou_variety);
  assert.throws(()=>mergeHistoryCells(doc,[doc.saiwaichou_variety.cells[0]]),/記号/);
});
