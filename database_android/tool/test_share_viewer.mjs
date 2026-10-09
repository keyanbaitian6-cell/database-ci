// 閲覧専用の共有ページ（share_viewer/、お試し 2026-10-09）の数え方。推定差枚は database/tests/test_meruhen_net.py、
// TOP10・強かった機種5選は test/event_calendar_test.dart・tests/test_event_calendar.py と同じ例で、同じ答えになること。
import assert from 'node:assert/strict';
import test from 'node:test';
import {meruhenNetDetail} from '../../share_viewer/net.mjs';
import {
  compactSigned, dayNet, daySummary, displayMachineName, enteredInAdvance, eventLabel, indexRecords,
  meruhenRecords, mergeEvents, monthWeeks, pscubeRecords, scriptIdFrom, storeLabel, viewerNameFrom,
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
  assert.equal(top.length, 10);
  assert.ok(!top.some(r => r.rack === 3), '差枚の無い台は入れない');
  assert.deepEqual(machines.map(m => [m.machine, m.racks, m.average]), [['機種B', 2, 8500], ['機種A', 15, 1767]]);
});

test('台の読み込み：数値異常の台は数えず、差枚の無い日は0にしない。P’s CUBEは貸玉ごと・沖ドキは外す', () => {
  const m = meruhenRecords({records: [
    {store: 'saiwaichou', day: '2026-10-04', machine: '北斗', rack: 1, games: 3000, bb: 10, rb: 5, max_hold: 2376, graph_measurement: measurement([0, -63, 40, 147, 128])},
    {store: 'saiwaichou', day: '2026-10-04', machine: '北斗', rack: 2, games: 88888888, bb: 10, rb: 5, max_hold: 2376, graph_measurement: measurement([0, -63, 40, 147, 128])},
    {store: 'saiwaichou', day: '2026-10-05', machine: '北斗', rack: 3, games: 1000, bb: 1, rb: 1, max_hold: 100},
    {store: 'elsewhere', day: '2026-10-05', machine: 'x', rack: 1},
  ]});
  const byDay = indexRecords(m);
  assert.deepEqual(dayNet(byDay.get('saiwaichou|2026-10-04')), {total: 1422, captured: 1, racks: 1});
  assert.deepEqual(dayNet(byDay.get('saiwaichou|2026-10-05')), {total: null, captured: 0, racks: 1});
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
