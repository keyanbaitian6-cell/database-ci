import test from 'node:test';
import assert from 'node:assert/strict';
import { emptyData, validateData } from '../web/pscube/data.mjs';
import { profileOf, implausible, scoreRecord, comparisonPool, nextDayEvidence, nextDayCandidates,
  qualifiesFocus, compareEvidence, graphMetrics, dayShift, percentile } from '../web/pscube/scoring.mjs';

const base = 'https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c1/cgi-bin/';
const machine = (patch = {}) => ({ store: 'c1', rate: '20', machine: '試験機種', expected_count: null,
  url: `${base}nc-v05-011.php?cd_ps=2&bai=20`, machine_type: 'other', ...patch });
const compact = d => d.replaceAll('-', '');
const rec = (rack, day, games, bb, rb, my, graph = null, m = {}) => ({ store: 'c1', rate: '20', machine: m.machine ?? '試験機種',
  rack, day, bb, rb, at_art: 0, games, my, observed_at: null, detail_url: `${base}nc-v06-001.php?cd_dai=${rack}#${compact(day)}`, graph });
const make = (records, machinePatch) => validateData({ ...emptyData(), machines: [machine(machinePatch)], records });
const graph = (peakY, endY) => ({ kind: 'daily', zero_y: 100, points: [[0, 100], [5, peakY], [10, endY]] });

test('machine profile: explicit type wins, otherwise the name decides (half-width kana too)', () => {
  assert.equal(profileOf({ machine: 'ﾏｲｼﾞｬｸﾞﾗｰV' }), 'normal');
  assert.equal(profileOf({ machine: 'ハッピージャグラーVIII' }), 'normal');
  assert.equal(profileOf({ machine: 'ニューキングハナハナ' }), 'normal');
  assert.equal(profileOf({ machine: '北斗の拳' }), 'other');
  assert.equal(profileOf({ machine: 'ジャグラー', machine_type: 'other' }), 'other');
  assert.equal(profileOf({ machine: '北斗の拳', machine_type: 'normal' }), 'normal');
});

test('hand-computed score for a non-normal machine (payout rank + graph shape)', () => {
  const pool = [1000, 2000, 3000].map((my, i) => rec(10 + i, '2026-09-30', 3000, 5, 5, my));
  const data = make([...pool, rec(1, '2026-10-01', 3000, 5, 5, 1500, graph(20, 60))]);
  const s = scoreRecord(data.records.find(r => r.rack === 1), data);
  // weight = cbrt(3000/4500 * 3/23 * 1/4); rank = 1/3
  const w = Math.cbrt(3000 / 4500 * 3 / 23 / 4);
  const hold = 50 * (0.5 + w * (1 / 3 - 0.5));
  assert.ok(Math.abs(s.parts.hold - hold) < 1e-9);
  assert.equal(s.parts.end, 25); assert.equal(s.parts.retention, 12.5); assert.equal(s.parts.hit, null);
  assert.equal(s.total, Math.round((hold + 37.5) * 10) / 10);
  assert.equal(s.provisional, true); assert.equal(s.coverage, 100);
});

test('normal type adds hit frequency (v12 weights 60/20/10/10)', () => {
  const pool = [2, 6, 10].map((hits, i) => rec(10 + i, '2026-09-30', 3000, hits, 0, 1000 + i));
  const data = make([...pool, rec(1, '2026-10-01', 3000, 8, 0, 1500, graph(20, 60))], { machine_type: 'normal' });
  const s = scoreRecord(data.records.find(r => r.rack === 1), data);
  const w = Math.cbrt(3000 / 4500 * 3 / 23 / 4);
  assert.ok(Math.abs(s.parts.hit - 60 * (0.5 + w * (2 / 3 - 0.5))) < 1e-9);
  assert.deepEqual(s.weights, { hit: 60, hold: 20, end: 10, retention: 10 });
});

test('absolute payout lifts the rank score only, and only for the 20-yen rate', () => {
  const pool = [19000, 19000, 19000].map((my, i) => rec(10 + i, '2026-09-30', 3000, 5, 5, my));
  const top = rec(1, '2026-10-01', 3000, 5, 5, 19000, graph(20, 20));
  const data = make([...pool, top]);
  assert.equal(scoreRecord(data.records.find(r => r.rack === 1), data).parts.hold, 50);
  const low = scoreRecord(make([...pool, { ...top, my: 100 }]).records.find(r => r.rack === 1), make([...pool, { ...top, my: 100 }]));
  assert.ok(low.parts.hold < 25);
});

test('no score at 500G or below, or for implausible numbers; they are not comparison peers', () => {
  const data = make([rec(1, '2026-10-01', 500, 3, 3, 800), rec(2, '2026-10-01', 600, 3, 3, 88888888), rec(3, '2026-10-01', 20001, 1, 1, 1),
    rec(4, '2026-09-30', 3000, 5, 5, 99999999), rec(5, '2026-10-01', 3000, 5, 5, 800)]);
  assert.equal(scoreRecord(data.records[0], data).total, null);
  assert.match(scoreRecord(data.records[0], data).reasons[0], /500G以下/);
  assert.match(scoreRecord(data.records[1], data).reasons[0], /異常/);
  assert.ok(implausible(data.records[2]));
  assert.equal(comparisonPool(data.records[4], data).length, 0);
});

test('same-day, future, other-machine and stale (>30 days) records are never comparison peers', () => {
  const day = '2026-10-01';
  const data = validateData({ ...emptyData(),
    machines: [machine(), machine({ machine: '別機種', url: `${base}nc-v05-011.php?cd_ps=2&bai=20` })],
    records: [rec(1, day, 3000, 5, 5, 1000), rec(2, day, 3000, 5, 5, 1000), rec(3, '2026-10-02', 3000, 5, 5, 1000),
      rec(4, '2026-09-30', 3000, 5, 5, 1000, null, { machine: '別機種' }), rec(5, '2026-08-31', 3000, 5, 5, 1000),
      rec(6, '2026-09-01', 3000, 5, 5, 1000)] });
  assert.deepEqual(comparisonPool(data.records[0], data).map(r => r.rack), [6]);
  assert.equal(dayShift(day, -30), '2026-09-01');
});

test('missing graph is filled neutrally and marked provisional', () => {
  const pool = [1000, 2000, 3000].map((my, i) => rec(10 + i, '2026-09-30', 3000, 5, 5, my));
  const data = make([...pool, rec(1, '2026-10-01', 3000, 5, 5, 1500)]);
  const s = scoreRecord(data.records.find(r => r.rack === 1), data);
  assert.equal(s.coverage, 50); assert.equal(s.parts.end, null);
  assert.ok(s.reasons.some(r => r.includes('グラフ未取得')));
});

test('graph metrics follow the SVG orientation (smaller y is higher)', () => {
  assert.deepEqual(graphMetrics(graph(20, 60)), { peak: 80, end: 40 });
  assert.deepEqual(graphMetrics(graph(100, 130)), { peak: 0, end: -30 });
  assert.equal(percentile(2, [1, 2, 2, 3]), (1 + 1) / 4);
});

function season(days, topAlways = true) {
  const rows = [];
  days.forEach((day, di) => {
    for (let rack = 1; rack <= 6; rack++) {
      const top = topAlways ? rack === 1 : rack === 1 + di % 6;
      rows.push(rec(rack, day, 3000 + rack, 3 + (top ? 8 : rack % 3), 3, 1000 + (top ? 900 : rack * 10)));
    }
  });
  return rows;
}
const five = ['2026-09-27', '2026-09-28', '2026-09-29', '2026-09-30', '2026-10-01'];

test('a rack that is top every day becomes the ★ with a stable ranking; ceil(25%) racks are picked', () => {
  const data = make(season(five), { machine_type: 'normal' });
  const e = nextDayEvidence(data.records.find(r => r.rack === 1 && r.day === '2026-10-01'), data);
  assert.equal(e.usedDays, 5); assert.ok(e.todayUsed);
  assert.ok(e.stabilityZ > 3 && e.stabilityZ < 3.3);
  const result = nextDayCandidates(data, data.machines[0], '2026-10-01');
  assert.equal(result.eligible, 6); assert.equal(result.candidates.length, 2);
  assert.equal(result.candidates[0].record.rack, 1);
  assert.equal(result.candidates[0].focus, !(result.candidates[0].todayScore >= 88));
});

test('fewer than 4 eligible racks gives no candidate; fewer than 3 usable days gives no index', () => {
  const data = make(season(five).filter(r => r.rack <= 3), { machine_type: 'normal' });
  assert.equal(nextDayCandidates(data, data.machines[0], '2026-10-01').candidates.length, 0);
  const short = make(season(five.slice(-2)), { machine_type: 'normal' });
  assert.equal(nextDayEvidence(short.records.find(r => r.rack === 1 && r.day === '2026-10-01'), short).rawIndex, null);
});

test('★ needs today in the index, a stable ranking and a score below 88', () => {
  const evidence = { rawIndex: 55, todayUsed: true, stabilityZ: 2 };
  assert.ok(qualifiesFocus(evidence, 87.9)); assert.ok(qualifiesFocus(evidence, null));
  assert.ok(!qualifiesFocus(evidence, 88)); assert.ok(!qualifiesFocus({ ...evidence, todayUsed: false }, 50));
  assert.ok(!qualifiesFocus({ ...evidence, stabilityZ: 1.95 }, 50)); assert.ok(!qualifiesFocus({ ...evidence, rawIndex: null }, 50));
});

test('ties: more used days, then the newer latest day, then the smaller rack number', () => {
  const e = (rack, usedDays, latestUsed, rawIndex = 55) => ({ record: { rack }, usedDays, latestUsed, rawIndex });
  assert.ok(compareEvidence(e(9, 6, '2026-09-01'), e(1, 5, '2026-10-01')) < 0);
  assert.ok(compareEvidence(e(9, 5, '2026-10-01'), e(1, 5, '2026-09-30')) < 0);
  assert.ok(compareEvidence(e(1, 5, '2026-10-01'), e(2, 5, '2026-10-01')) < 0);
  assert.ok(compareEvidence(e(2, 5, '2026-10-01'), e(1, 5, '2026-10-01')) > 0);
  // 小数9桁で丸めてから比べる：差が10億分の1未満なら同点として台番号で決める。
  assert.ok(compareEvidence(e(2, 1, 'a', 55.0000000004), e(1, 1, 'a', 55.0000000001)) > 0);
});
