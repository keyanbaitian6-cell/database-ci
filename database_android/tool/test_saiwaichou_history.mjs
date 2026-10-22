import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {parsePrivateHistory, mergeHistoryCells} from '../../share_viewer/event_history.mjs';

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
