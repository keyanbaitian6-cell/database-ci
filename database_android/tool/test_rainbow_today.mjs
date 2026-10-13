import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import {rainbowTodayRows, indexRecords, meruhenRecords, applyRainbowMarks, mergeMarks} from '../../share_viewer/data.mjs';

const fixture = JSON.parse(fs.readFileSync(new URL('../test/fixtures/variety_week.json', import.meta.url), 'utf8'));
const data = () => indexRecords(meruhenRecords(fixture));
const mark = (on, updated_at = '2026-10-14T04:00:00Z') => ({store: 'saiwaichou', day: '2026-10-14', rack: 1101, on, updated_at});

test('本日未取得でも1台機種を表示。過去の印や数値行を本日へコピーしない', () => {
  const byDay = data(), before = JSON.stringify([...byDay]);
  const report = rainbowTodayRows(byDay, [], 'saiwaichou', '2026-10-14');
  assert.equal(report.lineupDay, '2026-10-13');
  assert.deepEqual(report.rows.map(x => x.rack), [1101,1102,1103,1104,1105,1106]);
  assert.ok(report.rows.every(x => !x.imported && !x.marker.rainbow));
  assert.ok(report.rows.every(x => !Object.hasOwn(x.marker, 'games')));
  assert.equal(JSON.stringify([...byDay]), before);
  assert.equal(rainbowTodayRows(byDay, [], 'nagamachiminami', '2026-10-14').rows.length, 0);
});
test('共有の未取得日の印が表示され、外す時刻は端末やPCの古い印より優先される', () => {
  const byDay = data();
  assert.equal(rainbowTodayRows(byDay, [mark(true)], 'saiwaichou', '2026-10-14').rows[0].marker.rainbow, true);
  const marks = mergeMarks([mark(true)], [mark(false, '2026-10-14T05:00:00Z')]);
  assert.equal(rainbowTodayRows(byDay, marks, 'saiwaichou', '2026-10-14').rows[0].marker.rainbow, false);
  byDay.set('saiwaichou|2026-10-14', [{...byDay.get('saiwaichou|2026-10-13')[0], rack:1101, day:'2026-10-14', games:4567, rainbow:true, rainbowAt:'2026-10-14T06:00:00Z'}]);
  const row = rainbowTodayRows(byDay, marks, 'saiwaichou', '2026-10-14').rows[0];
  assert.equal(row.marker.rainbow, true);
  assert.equal(row.imported, true);
  assert.equal(row.record.games, 4567);
});
test('本日データの取り込み後に同じ台番号へ印が反映され、入れ替えや一部取得でも一覧を失わない', () => {
  const byDay = data();
  const old = byDay.get('saiwaichou|2026-10-13');
  byDay.set('saiwaichou|2026-10-14', [{...old[0], rack:1101, day:'2026-10-14', machine:'入れ替え後', rainbow:false, rainbowAt:null}]);
  byDay.set('saiwaichou|2026-10-15', old.map(r=>({...r, day:'2026-10-15'})));
  let report = rainbowTodayRows(byDay, [mark(true)], 'saiwaichou', '2026-10-14');
  assert.equal(report.lineupDay, '2026-10-13');
  assert.equal(report.rows[0].marker.machine, '入れ替え後');
  assert.equal(report.rows.length, 6);
  applyRainbowMarks(byDay, [mark(true)]);
  report = rainbowTodayRows(byDay, [], 'saiwaichou', '2026-10-14');
  assert.equal(report.rows[0].marker.rainbow, true);
  assert.equal(byDay.get('saiwaichou|2026-10-14')[0].rainbow, true);
});
