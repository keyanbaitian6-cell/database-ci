// 閲覧専用の共有ページ（share_viewer/、お試し 2026-10-09）の数え方。推定差枚は database/tests/test_meruhen_net.py、
// 並べ方は test/event_calendar_test.dart・tests/test_event_calendar.py と同じ例で、同じ答えになること。
// このページだけ、差枚は50位まで・強かった機種は10位まで出す（利用者指定 2026-10-10。自分用のカレンダーはTOP10・5選のまま）。
import assert from 'node:assert/strict';
import test from 'node:test';
import {meruhenNetDetail} from '../../share_viewer/net.mjs';
import {
  compactSigned, dayNet, daySummary, displayMachineName, enteredInAdvance, eventLabel, indexRecords,
  meruhenRecords, mergeEvents, monthWeeks, pscubeRecords, scriptIdFrom, storeLabel, viewerNameFrom,
  calendarDays, idleVarietyRacks, isHiddenMachine, storeDays,
  lastRainbowDay, lastRainbowText, rackMark, storeHasRainbow,
  VARIETY_SORTS, applyRainbowMarks, isoTime, markTime, mergeMarks, varietyRainbowRows, varietyRecordRows,
  byLongestGap, daysSinceRainbow, rackDays, rainbowVarietyMax, windowDays,
  lineupDay, suffixReport, isZorome, hasSuffixSummary,
  rackWon, showWinRate, winRateText, daySummaries, calendarDay,
} from '../../share_viewer/data.mjs';

function measurement(heights, withCurve = true) {
  const curve = heights.map((h, i) => [i * 10 + 0.5, 200.5 - h]);
  const ys = curve.map(p => p[1]);
  return {baseline_y: 200.5, peak_y: Math.min(...ys), trough_y: Math.max(...ys), end_y: curve.at(-1)[1], ...(withCurve ? {curve} : {})};
}
const net = (heights, maxHold, games) => meruhenNetDetail(measurement(heights), maxHold, games);
const down = [0, 0, 0, -5, -17, -17, -18, -36, -40, -55, -75, -89, -87, -109, -106, -105, -116, -139, -156, -161, -161];

test('推定差枚：PC・Androidと同じ例で同じ値（段階の選び方・回転数での選び直し・決められない台）', () => {
  assert.equal(net([0, -63, 40, 147, 128], 2376).value, 1422);
  assert.equal(net([0, -8, 163, 97], 1982).value, 1078);
  assert.equal(net([0, 60, 30], 400).value, 167);
  assert.equal(net([0, 120, 40, -50], 2900).value, -1111);
  assert.equal(net([0, 50, 20], null).value, null);
  assert.equal(net([0, 50, 20], 88888888).value, null);
  assert.equal(net([0, 0, 0], 0).value, 0);
  assert.equal(net([0, -40, -80], 0).value, null);
  assert.equal(meruhenNetDetail({baseline_y: 150.5, peak_y: 100, trough_y: 160, end_y: 120}, 500).value, null);
  assert.equal(meruhenNetDetail(null, 500).value, null);
  assert.deepEqual(net(down, 234), {value: -8944, needsCheck: false});
  assert.deepEqual(net(down, 234, 1634), {value: -1789, needsCheck: true});
  assert.equal(net([0, 0, 0, -4, -4, -13, -21, -21, -26, -26, -28, -73, -69, -70, -77, -77, -95, -95, -112, -145, -161, -161], 293, 790).value, -894);
  assert.equal(net([0, 0, 0, -1, -24, -44, -41, -48, -48, -64, -81, -80, -72, -92, -98, -98, -98], 279, 1228).value, -1089);
  assert.deepEqual(net([0, 0, 0, -136, -133, -133], 113, 168), {value: null, needsCheck: false});
  assert.deepEqual(net([0, 0, 0, -136, -133, -133], 113, 300), {value: -739, needsCheck: true});
  assert.deepEqual(net([0, -63, 40, 147, 128], 2376, 8584), {value: 1422, needsCheck: false});
  // 4点だけ（曲線なし）。
  const known = {baseline_y: 200.5, peak_y: 200.5 - 147, trough_y: 200.5 + 63, end_y: 200.5 - 128, peak_x: 300, trough_x: 100, end_x: 356};
  assert.equal(meruhenNetDetail(known, 2376).value, 1422);
  const ambiguous = {baseline_y: 200.5, peak_y: 100.5, trough_y: 370.5, end_y: 360.5, peak_x: 100, trough_x: 300, end_x: 356};
  assert.equal(meruhenNetDetail(ambiguous, 1500).value, null);
  const noX = {baseline_y: 200.5, peak_y: 200.5 - 147, trough_y: 200.5 + 63, end_y: 200.5 - 128};
  assert.equal(meruhenNetDetail(noX, 2376).value, 1422);
});

test('TOP10は差枚の多い順（同じ差枚は回転数の多い方）、5選は2台以上の機種の平均回転数（Flutter・PCと同じ例）', () => {
  const racks = [['機種A', 1, 1200, 3000], ['機種A', 2, -300, 4000], ['機種A', 3, null, 5000], ['機種A', 4, 800, 2000],
    ['機種A', 5, 800, 2500], ['機種B', 11, 50, 9000], ['機種B', 12, 60, 8000], ['機種C', 21, 9999, 12000]];
  for (let i = 30; i < 40; i++) racks.push(['機種A', i, -i, 1000]);
  const rows = racks.map(([machine, rack, n, games]) => ({machine, rack, net: n, games}));
  const {top, machines} = daySummary(rows);
  assert.deepEqual(top.slice(0, 5).map(r => r.rack), [21, 1, 5, 4, 12]);
  assert.equal(top.length, 17, '差枚のある台は50位まで全部');
  assert.ok(!top.some(r => r.rack === 3), '差枚の無い台は入れない');
  assert.deepEqual(machines.map(m => [m.machine, m.racks, m.average]), [['機種B', 2, 8500], ['機種A', 15, 1767]]);
});

test('差枚は50位まで、強かった機種は10位まで', () => {
  const rows = [];
  for (let i = 0; i < 60; i++) rows.push({machine: `機種${i % 12}`, rack: i + 1, net: i * 10, games: 1000 + i});
  const {top, machines} = daySummary(rows);
  assert.equal(top.length, 50);
  assert.deepEqual([top[0].rack, top[49].rack], [60, 11]);
  assert.equal(machines.length, 10);
  assert.deepEqual(machines.map(m => m.machine).slice(0, 2), ['機種11', '機種10']);
});

test('台の読み込み：数値異常の台は数えず、差枚の無い日は0にしない。P’s CUBEは貸玉ごと・沖ドキは外す', () => {
  const m = meruhenRecords({records: [
    {store: 'saiwaichou', day: '2026-10-04', machine: '北斗', rack: 1, games: 3000, bb: 10, rb: 5, max_hold: 2376, graph_measurement: measurement([0, -63, 40, 147, 128])},
    {store: 'saiwaichou', day: '2026-10-04', machine: '北斗', rack: 2, games: 88888888, bb: 10, rb: 5, max_hold: 2376, graph_measurement: measurement([0, -63, 40, 147, 128])},
    {store: 'saiwaichou', day: '2026-10-05', machine: '北斗', rack: 3, games: 1000, bb: 1, rb: 1, max_hold: 100},
    {store: 'elsewhere', day: '2026-10-05', machine: 'x', rack: 1},
  ]});
  const byDay = indexRecords(m);
  assert.deepEqual(dayNet(byDay.get('saiwaichou|2026-10-04')), {total: 1422, captured: 1, racks: 1, judged: 1, won: 1, winRate: false});
  assert.deepEqual(dayNet(byDay.get('saiwaichou|2026-10-05')), {total: null, captured: 0, racks: 1, judged: 0, won: 0, winRate: false});
  const jo = meruhenRecords({records: [{store: 'saiwaichou', day: '2026-10-06', machine: '北斗', rack: 7, games: 3000, bb: 10, rb: 5,
    max_hold: 2376, graph_measurement: measurement([0, -63, 40, 147, 128]), jo_net: -280}]});
  assert.deepEqual([jo[0].net, jo[0].estimated], [-280, false], 'ジャグラーオンラインの差枚を優先');
  const p = pscubeRecords({format: 'pscube-viewer', records: [
    {store: 'c740601', rate: '20', day: '2026-10-04', machine: 'ﾏｲｼﾞｬｸﾞﾗｰV', rack: 1, games: 3000, bb: 10, rb: 5, my: 1000, net_medals: 300},
    {store: 'c740601', rate: '5', day: '2026-10-04', machine: 'ﾏｲｼﾞｬｸﾞﾗｰV', rack: 1, games: 3000, bb: 10, rb: 5, my: 1000, net_medals: -40},
    {store: 'c740601', rate: '20', day: '2026-10-04', machine: 'ｵｷﾄﾞｷ!', rack: 9, games: 3000, bb: 1, rb: 1, my: 1, net_medals: 999},
  ]});
  assert.deepEqual(p.map(r => [r.store, r.net]), [['pscube:c740601:20', 300], ['pscube:c740601:5', -40]]);
  assert.equal(storeLabel('pscube:c740601:20'), 'P-STATION（20スロ）', '閲覧専用ページの表記');
});

test('イベント：入力時刻の新しい方、時刻のある方が勝つ、消した印は出さない、前日02:00までの入力は＊なし', () => {
  const events = mergeEvents(
    [{store: 'saiwaichou', day: '2026-10-04', name: '半列'},
      {store: 'saiwaichou', day: '2026-10-05', name: '華の日', updated_at: '2026-10-05T12:00:00+09:00'}],
    [{store: 'saiwaichou', day: '2026-10-04', name: '4台構成', updated_at: '2026-10-03T21:00:00+09:00'},
      {store: 'saiwaichou', day: '2026-10-05', name: null, updated_at: '2026-10-05T13:00:00+09:00'},
      {store: 'c740601', rate: '20', day: '2026-10-06', name: '業火の極', updated_at: '2026-10-05T12:00:00.000Z'}],
  );
  assert.equal(eventLabel(events.get('saiwaichou|2026-10-04')), '4台構成');
  assert.equal(eventLabel(events.get('saiwaichou|2026-10-05')), '', '消した印');
  assert.equal(eventLabel(events.get('pscube:c740601:20|2026-10-06')), '業火の極');
  assert.equal(enteredInAdvance({day: '2026-10-10', at: Date.parse('2026-10-10T01:59:59+09:00')}), true);
  assert.equal(enteredInAdvance({day: '2026-10-10', at: Date.parse('2026-10-10T02:00:00+09:00')}), false);
  assert.equal(eventLabel(mergeEvents([{store: 'saiwaichou', day: '2026-10-04', name: '半列'}]).get('saiwaichou|2026-10-04')), '半列＊', '時刻不明は＊');
});

test('表示：半角カナだけ全角に、10万枚以上は「万」、日曜始まりの週、リンクからスクリプトのID', () => {
  assert.equal(displayMachineName('ｺﾞｰｺﾞｰｼﾞｬｸﾞﾗｰ3'), 'ゴーゴージャグラー3');
  assert.equal(displayMachineName('ﾏｲｼﾞｬｸﾞﾗｰV'), 'マイジャグラーV');
  assert.equal(displayMachineName('Ｌ東京喰種'), 'Ｌ東京喰種');
  assert.equal(compactSigned(99999), '+99,999');
  assert.equal(compactSigned(133760), '+13.4万');
  assert.equal(compactSigned(-100297), '-10.0万');
  assert.equal(compactSigned(0), '0');
  const weeks = monthWeeks(2026, 10);
  assert.deepEqual(weeks[0], [null, null, null, null, '2026-10-01', '2026-10-02', '2026-10-03']);
  assert.equal(weeks.at(-1).filter(Boolean).at(-1), '2026-10-31');
  assert.equal(monthWeeks(2026, 2).length, 4);
  const id = 'AKfycb' + 'x'.repeat(40);
  assert.equal(scriptIdFrom(`https://keyanbaitian6-cell.github.io/database-share/#s=${id}`), id);
  assert.equal(scriptIdFrom(`https://script.google.com/macros/s/${id}/exec`), id);
  assert.equal(scriptIdFrom(id), id);
  assert.equal(scriptIdFrom('https://example.com/#s=short'), null);
  assert.equal(scriptIdFrom('<script>'), null);
  assert.equal(scriptIdFrom(`https://x/#s=${id}&u=himawari`), id);
  assert.equal(viewerNameFrom(`https://x/#s=${id}&u=himawari`), 'himawari');
  assert.equal(viewerNameFrom(`#u=himawari&s=${id}`), 'himawari');
  assert.equal(viewerNameFrom(`#s=${id}&u=<b>`), null);
  assert.equal(viewerNameFrom(`#s=${id}`), null);
});

// バラエティの回っていない台：閲覧ページ（test/variety_idle_test.dart）と同じ例で同じ答え。
const day = (n) => `2026-10-${String(n).padStart(2, '0')}`;
function idleSample() {
  const rows = [];
  const rec = (n, machine, rack, games) => rows.push({store: 'nagamachiminami', day: day(n), machine, rack, games, bb: 1, rb: 1});
  for (let n = 1; n <= 10; n++) {
    for (let rack = 1; rack <= 4; rack++) rec(n, '主力', rack, 300);
    rec(n, 'A', 10, n === 1 ? 2500 : 400 + n);
    rec(n, 'B', 20, n <= 3 ? 1000 : 999);
    rec(n, 'B', 21, n === 4 ? 1500 : 200);
    if (n !== 5) rec(n, 'C', 30, 100);
    rec(n, n >= 8 ? 'D' : 'E', 40, 50);
  }
  return indexRecords(rows);
}
const picks = (byDay, d, opts) => idleVarietyRacks(byDay, 'nagamachiminami', day(d), opts).map(r => [r.latest.machine, r.latest.rack, r.span]);

test('回っていない台：バラエティで、選んだ日から前へ毎日1000G未満が7日以上（閲覧ページと同じ例）', () => {
  const byDay = idleSample();
  assert.deepEqual(picks(byDay, 10), [['A', 10, 9], ['B', 20, 7]]);
  const a = idleVarietyRacks(byDay, 'nagamachiminami', day(10))[0];
  assert.deepEqual([a.from, a.maxGames, a.days[0].day], [day(2), 410, day(10)]);
  assert.deepEqual(picks(byDay, 9), [['A', 10, 8]]);
  assert.deepEqual(picks(byDay, 7), [['E', 40, 7]], '入れ替え前のEは7日目の時点で7日');
  assert.deepEqual(picks(byDay, 6), []);
  assert.deepEqual(picks(byDay, 10, {gamesLimit: 500}), [['A', 10, 9]]);
  assert.deepEqual(picks(byDay, 10, {minDays: 3}).map(x => [x[1], x[2]]), [[10, 9], [20, 7], [21, 6], [30, 5], [40, 3]]);
  assert.deepEqual(picks(byDay, 10, {minDays: 3, gamesLimit: 3000}).map(x => [x[1], x[2]]), [[10, 10], [20, 10], [21, 10], [30, 5], [40, 3]]);
  assert.deepEqual(storeDays(byDay, 'nagamachiminami').slice(0, 2), [day(10), day(9)]);
});

test('回っていない台：期間はカレンダーの日数（記録の無い日は飛ばして期間に含める）', () => {
  const rows = [];
  for (const n of [1, 2, 3, 8, 9, 10]) {
    for (let rack = 1; rack <= 4; rack++) rows.push({store: 'saiwaichou', day: day(n), machine: '主力', rack, games: 300, bb: 1, rb: 1});
    rows.push({store: 'saiwaichou', day: day(n), machine: 'X', rack: 50, games: 200, bb: 1, rb: 1});
  }
  const byDay = indexRecords(rows);
  const [x] = idleVarietyRacks(byDay, 'saiwaichou', day(10));
  assert.deepEqual([x.span, x.days.length, x.from], [10, 6, day(1)]);
  assert.deepEqual(idleVarietyRacks(byDay, 'saiwaichou', day(10), {minDays: 14}), []);
  assert.equal(calendarDays('2026-09-28', '2026-10-04'), 7);
});

test('幸町の聖闘士星矢 海皇覚醒（1279番台、稼働停止）は表示しない。沖ドキなど以前の記録は出す', () => {
  assert.ok(isHiddenMachine('saiwaichou', 'L 聖闘士星矢 海皇覚醒 ED'));
  assert.ok(!isHiddenMachine('nagamachiminami', 'L聖闘士星矢海皇覚醒ED'));
  assert.ok(!isHiddenMachine('saiwaichou', 'L／オキドキデュオ2／FR'));
  const m = meruhenRecords({records: [
    {store: 'saiwaichou', day: '2026-10-09', machine: 'L聖闘士星矢海皇覚醒ED', rack: 1279, games: 0, bb: 0, rb: 0, jo_net: 0},
    {store: 'saiwaichou', day: '2026-10-09', machine: 'L／オキドキデュオ2／FR', rack: 900, games: 3000, bb: 10, rb: 5, jo_net: 120},
  ]});
  assert.deepEqual(m.map(r => r.rack), [900]);
});

test('確定が出た台の印🌈（PCで付ける）と最終🌈：閲覧ページ・PCと同じ例（RAINBOW.md）', () => {
  const rec = (day, rack, rainbow, machine = 'ハナハナ') => ({store: 'nagamachiminami', day, machine, rack, games: 3000, bb: 10, rb: 5,
    ...(rainbow ? {rainbow: true} : {})});
  const records = meruhenRecords({records: [rec('2026-09-26', 660, true), rec('2026-10-05', 660, true, '別の機種'),
    rec('2026-10-10', 660, false), rec('2026-10-10', 661, false)]});
  assert.deepEqual(records.map(r => r.rainbow), [true, true, false, false]);
  assert.equal(rackMark(records[0]), '🌈');
  assert.equal(rackMark(records[2]), '');
  const byDay = indexRecords(records);
  assert.equal(lastRainbowDay(byDay, 'nagamachiminami', 660, '2026-10-10'), '2026-10-05', '機種が変わっても同じ台番号');
  assert.equal(lastRainbowDay(byDay, 'nagamachiminami', 660, '2026-10-01'), '2026-09-26');
  assert.equal(lastRainbowDay(byDay, 'nagamachiminami', 661, '2026-10-10'), null);
  assert.equal(lastRainbowText('2026-10-05', '2026-10-10'), '10/5（5日前）');
  assert.equal(lastRainbowText('2026-10-10', '2026-10-10'), '当日');
  assert.equal(lastRainbowText(null, '2026-10-10'), 'なし');
  assert.equal(storeHasRainbow(byDay, 'nagamachiminami'), true);
  assert.equal(storeHasRainbow(byDay, 'saiwaichou'), false, '🌈の無い店では最終🌈の欄を出さない');
});

test('共有ページから付ける🌈：新しい方が残る・バラエティ🌈の一覧（PCのバラエティ🌈と同じ例）', () => {
  const rec = (day, rack, machine, extra = {}) => ({store: 'nagamachiminami', day, machine, rack, games: 3000, bb: 10, rb: 5, ...extra});
  const records = meruhenRecords({records: [
    ...['2026-10-09', '2026-10-10'].flatMap(day => [1, 2, 3, 4].map(r => rec(day, r, '主力'))),
    rec('2026-10-09', 50, 'ハナハナ', {rainbow: true, rainbow_at: '2026-10-09T23:00:00.123456+09:00'}), rec('2026-10-09', 51, 'ハナハナ'),
    rec('2026-10-09', 60, '旧バラエティ'),
    rec('2026-10-10', 50, 'ハナハナ', {games: 5000}), rec('2026-10-10', 51, 'ハナハナ', {games: 800}),
    rec('2026-10-10', 60, '新バラエティ'), rec('2026-10-10', 61, '新バラエティ'),
  ]});
  assert.ok(Number.isFinite(isoTime('2026-10-09T23:00:00.123456+09:00')), '小数6桁の時刻も読める（iPhoneのSafari）');
  const byDay = indexRecords(records);
  // PCで付けた時刻（10/9 23:00 JST）より古い印は負け、新しい印は勝つ。記録の無い台の印は何もしない。
  assert.equal(applyRainbowMarks(byDay, [
    {store: 'nagamachiminami', day: '2026-10-09', rack: 50, on: false, updated_at: '2026-10-09T13:00:00.000Z'},
    {store: 'nagamachiminami', day: '2026-10-10', rack: 51, on: true, updated_at: '2026-10-11T01:00:00.000Z'},
    {store: 'nagamachiminami', day: '2026-10-10', rack: 999, on: true, updated_at: '2026-10-11T01:00:00.000Z'},
    {store: 'pscube:c1:20', day: '2026-10-10', rack: 1, on: true, updated_at: '2026-10-11T01:00:00.000Z'},
  ]), 1);
  const rows = varietyRainbowRows(byDay, 'nagamachiminami', '2026-10-10');
  assert.deepEqual(rows.map(x => [x.rack, x.machine]), [[50, 'ハナハナ'], [51, 'ハナハナ'], [60, '新バラエティ'], [61, '新バラエティ']]);
  assert.deepEqual([rows[0].last, rows[0].count, rows[1].record.rainbow, rows[1].count], ['2026-10-09', 1, true, 1]);
  const older = varietyRainbowRows(byDay, 'nagamachiminami', '2026-10-09');
  assert.deepEqual(older.map(x => [x.rack, x.dayMachine, x.record ? x.record.games : null]),
    [[50, null, 3000], [51, null, 3000], [60, '旧バラエティ', 3000], [61, null, null]], '一覧は最新の並び、数値は選んだ日');
  assert.deepEqual([...rows].sort(VARIETY_SORTS['最終🌈の古い順']).map(x => x.rack), [60, 61, 50, 51]);
  // 付け外しの時刻は、台の時刻・前の印より必ず後。印の足し合わせは新しい方。
  assert.equal(markTime(Date.parse('2026-10-09T00:00:00Z'), '2026-10-09T23:00:00.123456+09:00'), '2026-10-09T14:00:00.124Z');
  const merged = mergeMarks([{store: 'nagamachiminami', day: '2026-10-10', rack: 51, on: true, updated_at: '2026-10-11T02:00:00.000Z'}],
    [{store: 'nagamachiminami', day: '2026-10-10', rack: 51, on: false, updated_at: '2026-10-11T01:00:00.000Z'}, {store: 'bad'}]);
  assert.deepEqual(merged.map(m => m.on), [true]);
});

test('バラエティ🌈：幸町は1台だけの機種（2026-10-12）・ローテーション表の7日・空き順', () => {
  const rec = (store, day, rack, machine, extra = {}) => ({store, day, machine, rack, games: 3000, bb: 10, rb: 5, ...extra});
  const records = meruhenRecords({records: [
    rec('saiwaichou', '2026-10-10', 1201, '無職転生'), rec('saiwaichou', '2026-10-10', 1202, '頭文字D'),
    rec('saiwaichou', '2026-10-10', 50, 'ハナハナ'), rec('saiwaichou', '2026-10-10', 51, 'ハナハナ'),
    rec('saiwaichou', '2026-10-04', 1201, '無職転生', {rainbow: true}), rec('saiwaichou', '2026-10-08', 1202, '頭文字D', {rainbow: true}),
    rec('nagamachiminami', '2026-10-10', 50, 'ハナハナ'), rec('nagamachiminami', '2026-10-10', 51, 'ハナハナ'),
  ]});
  const byDay = indexRecords(records);
  assert.deepEqual([rainbowVarietyMax('saiwaichou'), rainbowVarietyMax('nagamachiminami')], [1, 3]);
  assert.deepEqual(varietyRainbowRows(byDay, 'saiwaichou', '2026-10-10').map(x => x.rack), [1201, 1202], '幸町：2台のハナハナは入れない');
  assert.deepEqual(varietyRainbowRows(byDay, 'nagamachiminami', '2026-10-10').map(x => x.rack), [50, 51], '長町南：1〜3台のまま');
  const days = windowDays('2026-10-10');
  assert.deepEqual([days.length, days[0], days[6]], [7, '2026-10-04', '2026-10-10']);
  assert.deepEqual(rackDays(byDay, 'saiwaichou', 1201, days).map(r => (r ? r.rainbow : null)), [true, null, null, null, null, null, false]);
  assert.deepEqual([daysSinceRainbow('2026-10-04', '2026-10-10'), daysSinceRainbow('2026-10-10', '2026-10-10'), daysSinceRainbow(null, '2026-10-10')], [6, 0, null]);
  const rows = varietyRainbowRows(byDay, 'saiwaichou', '2026-10-10');
  assert.deepEqual(byLongestGap(rows, '2026-10-10').map(x => x.rack), [1201, 1202], '空きの長い台（6日）が上');
  assert.deepEqual(byLongestGap([...rows, {rack: 7, last: null}], '2026-10-10').map(x => x.rack), [7, 1201, 1202], '一度も無い台がいちばん上');
});

test('🌈の記録は本日（開いた日）が選んだ日：取り込み前は幸町だけ印を付け外し、台番号は前の最新の記録を開く（2026-10-16）', () => {
  const rec = (store, day, rack, machine, extra = {}) => ({store, day, machine, rack, games: 3000, bb: 10, rb: 5, ...extra});
  const byDay = indexRecords(meruhenRecords({records: [
    rec('saiwaichou', '2026-10-10', 1201, '無職転生', {rainbow: true}), rec('saiwaichou', '2026-10-10', 1202, '頭文字D'),
    rec('nagamachiminami', '2026-10-10', 50, 'ハナハナ'),
  ]}));
  const marks = [{store: 'saiwaichou', day: '2026-10-11', rack: 1202, on: true, updated_at: '2026-10-11T03:00:00Z'}];
  const today = varietyRecordRows(byDay, marks, 'saiwaichou', '2026-10-11', '2026-10-11');
  assert.deepEqual(today.map(x => [x.rack, x.record, x.mark?.day, x.mark?.rainbow, x.open?.day, x.last]),
    [[1201, null, '2026-10-11', false, '2026-10-10', '2026-10-10'], [1202, null, '2026-10-11', true, '2026-10-10', '2026-10-11']],
    '本日は未取得：印だけ（他端末の印も）、台番号は10/10の記録、印を付けた台は最後の🌈が本日');
  assert.deepEqual(varietyRecordRows(byDay, marks, 'nagamachiminami', '2026-10-11', '2026-10-11').map(x => [x.rack, x.mark, x.open?.day]),
    [[50, null, '2026-10-10']], '長町南は取り込み前の印を作らない（「本日」と同じく幸町だけ）');
  const past = varietyRecordRows(byDay, marks, 'saiwaichou', '2026-10-10', '2026-10-11');
  assert.deepEqual(past.map(x => [x.rack, x.mark === x.record, x.open === x.record, x.last]),
    [[1201, true, true, '2026-10-10'], [1202, true, true, null]], '前の日を見ているときは従来どおりその日の記録');
});

test('バラエティ🌈の並べる台は、記録のそろった最新の日（一部しか取れていない日は使わない、2026-10-12）', () => {
  const rec = (day, rack) => ({store: 'nagamachiminami', day, machine: `機種${rack}`, rack, games: 3000, bb: 10, rb: 5});
  const records = meruhenRecords({records: [
    ...[1, 2, 3, 4, 5].map(r => rec('2026-10-09', r)), ...[1, 2, 3, 4].map(r => rec('2026-10-10', r)), rec('2026-10-11', 1)]});
  const byDay = indexRecords(records);
  assert.equal(lineupDay(byDay, 'nagamachiminami'), '2026-10-10', '4/5台＝8割はそろっている、1台の日は使わない');
  assert.deepEqual(varietyRainbowRows(byDay, 'nagamachiminami', '2026-10-11').map(x => [x.rack, !!x.record]),
    [[1, true], [2, false], [3, false], [4, false]]);
  assert.equal(lineupDay(byDay, 'saiwaichou'), null);
});

test('長町南10/7は推定差枚を出さない（グラフが直線だけの日、2026-10-12）。ジャグラーオンラインの差枚とほかの日は出す', () => {
  const g = measurement([0, -63, 40, 147, 128]);
  const rec = (store, d, extra = {}) => ({store, day: d, machine: '北斗', rack: 1, games: 3000, bb: 10, rb: 5, max_hold: 2376, graph_measurement: g, ...extra});
  const [hidden, joDay, otherDay, otherStore] = meruhenRecords({records: [
    rec('nagamachiminami', '2026-10-07'), rec('nagamachiminami', '2026-10-07', {rack: 2, jo_net: -280}),
    rec('nagamachiminami', '2026-10-08'), rec('saiwaichou', '2026-10-07')]});
  assert.equal(hidden.net, null);
  assert.equal(joDay.net, -280);
  assert.equal(otherDay.net, 1422);
  assert.equal(otherStore.net, 1422);
});

test('末尾別データまとめ（幸町、2026-10-12）：平均差枚の順・表示と同じ整数で同順位・差枚の無い台は平均に入れない・ゾロ目は44・99も', () => {
  const rec = (rack, net) => ({store: 'saiwaichou', day: '2026-10-10', machine: 'x', rack, games: 3000, bb: 1, rb: 1, ...(net == null ? {} : {jo_net: net})});
  const byDay = indexRecords(meruhenRecords({records: [rec(1000, 300), rec(1001, 300), rec(1002, 100), rec(1012, null), rec(1044, 50)]}));
  const report = suffixReport(byDay, 'saiwaichou', '2026-10-10', 1);
  const of = label => report.summaries.find(s => s.label === label);
  assert.deepEqual(report.leaders.map(s => s.label), ['末尾0', '末尾1']);
  assert.equal(report.rankOf(of('ゾロ目')), 3, 'ゾロ目（1000・1044、平均+175）も順位に入る');
  assert.equal(report.rankOf(of('末尾2')), 4);
  assert.equal(of('末尾2').records, 2);
  assert.equal(of('末尾2').averageNet, 100, '差枚の無い1012番台は平均に入れない');
  assert.equal(of('ゾロ目').records, 2);
  assert.ok(isZorome(1044) && isZorome(1099) && isZorome(1000) && !isZorome(1045));
  assert.equal(report.records, 5, 'ゾロ目は合計に二重に入れない');
});

test('P-STATION（P’s CUBE）の末尾別データまとめ（2026-10-12「共有のP-stationの方にも末尾データほしい」）：末尾0・1・2・3・5・6・7・8、ゾロ目に44は入らない、サイトの差枚で順位', () => {
  const store = 'pscube:c740601:20';
  assert.ok(hasSuffixSummary(store) && hasSuffixSummary('saiwaichou') && !hasSuffixSummary('nagamachiminami'));
  const rec = (rack, net) => ({store: 'c740601', rate: '20', day: '2026-10-10', machine: 'x', rack, games: 3000, bb: 1, rb: 1, my: 100, net_medals: net});
  const byDay = indexRecords(pscubeRecords({format: 'pscube-viewer', records: [rec(1003, 900), rec(1005, 100), rec(1044, 50), rec(1011, 300)]}));
  const report = suffixReport(byDay, store, '2026-10-10', 1);
  assert.deepEqual(report.summaries.map(s => s.label), ['末尾0', '末尾1', '末尾2', '末尾3', '末尾5', '末尾6', '末尾7', '末尾8', 'ゾロ目']);
  assert.deepEqual(report.leaders.map(s => s.label), ['末尾3']);
  assert.equal(report.summaries.find(s => s.label === 'ゾロ目').records, 1, '1011番台だけ（1044番台は入らない）');
  assert.ok(!isZorome(1044, store) && isZorome(1044, 'saiwaichou'));
  assert.equal(report.records, 3, '末尾4の1044番台は数えない');
});

test('勝率：差枚の分からない日は「何台中何台プラス」から（PC test_win_rate.py・Flutter win_rate_test.dart と同じ例）', () => {
  // 2026-10-17 利用者「差枚を出せないところについては勝率を書いてほしい」。アナスロ補完はグラフの終点だけが分かる。
  const rack = (n, extra) => ({store: 'saiwaichou', day: '2026-09-10', machine: 'M', rack: n, games: 3000, bb: 5, rb: 2, ...extra});
  const racks = meruhenRecords({records: [
    rack(1, {graph_measurement: measurement([0, 80, 50])}),        // 終点+50px → プラス
    rack(2, {graph_measurement: measurement([0, 20, -30])}),       // マイナス
    rack(3, {graph_measurement: measurement([0, 40, 0.5])}),       // 1px以内 → プラスにしない
    rack(4, {games: 2000, bb: 0, rb: 0}),                          // 大当たり0回 → マイナス
    rack(5, {games: 0, bb: 0, rb: 0}),                             // 未稼働 → 数えない
    rack(6, {}),                                                   // グラフ無し → 数えない
  ]});
  assert.deepEqual(racks.map(rackWon), [true, false, false, false, null, null]);
  const day = dayNet(racks);
  assert.deepEqual([day.captured, day.judged, day.won, day.winRate, day.total], [0, 4, 1, true, null]);
  assert.equal(winRateText(day.won, day.judged), '勝率25%');
  assert.equal(winRateText(255, 532), '勝率48%');
  assert.equal(winRateText(1, 8), '勝率13%', '0.5は切り上げ');
  // 差枚の分かる台が半分以上なら今までどおり総差枚。
  assert.equal(showWinRate(1, 4), true);
  assert.equal(showWinRate(2, 4), false);
  assert.equal(showWinRate(0, 0), false);
  // 推定差枚を出さない店・日（長町南10/7）はグラフも信用しないので数えない。
  const hidden = meruhenRecords({records: [{store: 'nagamachiminami', day: '2026-10-07', machine: 'M', rack: 1, games: 3000,
    bb: 5, rb: 2, graph_measurement: measurement([0, 80, 50])}]});
  assert.equal(rackWon(hidden[0]), null);
  // P’s CUBEの差枚のない台（アナスロ補完）は数えない（幸町だけの扱い）。
  const p = pscubeRecords({format: 'pscube-viewer', records: [
    {store: 'c740601', rate: '20', day: '2026-10-04', machine: 'ﾏｲｼﾞｬｸﾞﾗｰV', rack: 1, games: 3000, bb: 10, rb: 5, my: 1000, net_medals: 300},
  ]});
  assert.equal(rackWon(p[0]), true);
});

test('保存したHTMLからの日ごとの集計（day_summaries）：台データの無い日だけ勝率、形のおかしい日は捨てる', () => {
  // 2026-10-18 利用者「各日の勝率、何台中何台プラスで終わったかをそれだけを乗せて欲しい」。PC html_day_summary.py と同じ形。
  const map = daySummaries({day_summaries: [
    {store: 'saiwaichou', day: '2025-09-15', racks: 536, judged: 534, won: 201},
    {store: 'saiwaichou', day: '2025-09-16', racks: 10, judged: 5, won: 6},       // won > judged
    {store: 'saiwaichou', day: '2025-09-17', racks: 4, judged: 5, won: 1},        // judged > racks
    {store: 'saiwaichou', day: '2025-9-18', racks: 5, judged: 5, won: 1},         // 日付の形
    {store: 'unknown', day: '2025-09-19', racks: 5, judged: 5, won: 1},
    {store: 'saiwaichou', day: '2025-09-20', racks: 5, judged: 5.5, won: 1},
    null,
  ]});
  assert.deepEqual([...map], [['saiwaichou|2025-09-15', {racks: 536, judged: 534, won: 201}]]);
  assert.equal(daySummaries({}).size, 0);
  assert.equal(daySummaries(null).size, 0);
  const summary = map.get('saiwaichou|2025-09-15');
  const day = calendarDay([], summary);
  assert.deepEqual([day.winRate, day.judged, day.won, day.total, day.summary], [true, 534, 201, null, summary]);
  assert.equal(winRateText(day.won, day.judged), '勝率38%');
  // 台データのある日はその日の台から（集計は使わない）。
  const racks = meruhenRecords({records: [{store: 'saiwaichou', day: '2025-09-15', machine: 'M', rack: 1, games: 3000, bb: 5, rb: 2,
    max_hold: 2376, graph_measurement: measurement([0, -63, 40, 147, 128])}]});
  assert.deepEqual(calendarDay(racks, summary), {...dayNet(racks), summary: null});
  // 勝ち負けの分かる台が0台の集計は出さない。
  assert.equal(calendarDay([], {racks: 3, judged: 0, won: 0}).winRate, false);
});
