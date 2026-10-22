import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {parsePrivateHistory, mergeHistoryCells, historyGradeGap} from '../../share_viewer/event_history.mjs';

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
