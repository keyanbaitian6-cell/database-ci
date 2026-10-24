import test from 'node:test';
import assert from 'node:assert/strict';
import {netMedalsOfProbe} from '../web/pscube/data.mjs';

const line = (day, n) => ({YMD_biz:day, xField:`out-${n}`, yField:`value-${n}`});
const pair = (n, first, last) => [
  {[`out-${n}`]:0, [`value-${n}`]:first},
  {[`out-${n}`]:10, [`value-${n}`]:last},
];
const probe = (g, p) => ({rack:1, day:'20261023', graph:{datas:{g,p}}});

test('空の別日が前後にあっても正常日の正負・0枚を保持する', () => {
  const raw = probe([
    line(20261019,1), line(20261020,2), line(20261021,3), line(20261022,4), line(20261023,5),
  ], [
    {'out-1':null,'value-1':null}, {'out-3':'','value-3':''},
    ...pair(2,100,0), ...pair(4,20,20), ...pair(5,100,600),
  ]);
  assert.deepEqual([...netMedalsOfProbe(raw)], [
    ['2026-10-20',-100], ['2026-10-22',0], ['2026-10-23',500],
  ]);
});

test('不正・1点・片側欠損の日だけを除外し、端点だけで差枚を捏造しない', () => {
  const raw = probe([
    line(20261019,1), line(20261020,2), line(20261021,3), line(20261022,4), line(20261023,5),
  ], [
    ...pair(1,0,10), {'out-1':5,'value-1':null},
    {'out-2':0,'value-2':10},
    ...pair(3,0,1.5),
    {'out-4':10,'value-4':0}, {'out-4':0,'value-4':10},
    ...pair(5,500,100),
  ]);
  assert.deepEqual([...netMedalsOfProbe(raw)], [['2026-10-23',-400]]);
});

test('選択日が欠測でも取り込み用の解析では正常な過去日を返す', () => {
  const raw = probe([line(20261022,1), line(20261023,2)], pair(1,10,210));
  assert.deepEqual([...netMedalsOfProbe(raw,{requireSelected:false})], [['2026-10-22',200]]);
  assert.throws(() => netMedalsOfProbe(raw), /選択日のグラフ/,
    '手動貼り付けの選択日確認は維持する');
  assert.equal(netMedalsOfProbe(probe([line(20261023,1)],[]),{requireSelected:false}).size,0);
});

test('空の系列でも重複日付・共有フィールド・未来日は曖昧な応答として拒否する', () => {
  for (const g of [
    [line(20261022,1),line(20261022,2),line(20261023,3)],
    [line(20261022,1),{...line(20261023,2),xField:'out-1'}],
    [line(20261022,1),{...line(20261023,2),yField:'value-1'}],
    [line(20261024,1),line(20261023,2)],
    [null,line(20261023,2)],
  ]) assert.throws(() => netMedalsOfProbe(probe(g,pair(2,0,10)),{requireSelected:false}));
});

test('全体の単位・日付・台番号の不正は部分取得でも拒否する', () => {
  const raw=probe([line(20261023,1)],pair(1,10,110));
  for (const bad of [
    {...raw,rack:0}, {...raw,day:'20260230'},
    {...raw,graph:{...raw.graph,anjYUnit:0}},
    {...raw,graph:{...raw.graph,anjYUnit:Infinity}},
  ]) assert.throws(() => netMedalsOfProbe(bad,{requireSelected:false}));
});
