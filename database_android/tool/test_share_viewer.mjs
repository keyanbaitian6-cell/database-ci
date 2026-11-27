// 閲覧専用の共有ページ（share_viewer/、お試し 2026-10-09）の数え方。推定差枚は database/tests/test_meruhen_net.py、
// 並べ方は test/event_calendar_test.dart・tests/test_event_calendar.py と同じ例で、同じ答えになること。
// このページだけ、差枚は50位まで・強かった機種は10位まで出す（利用者指定 2026-10-10。自分用のカレンダーはTOP10・5選のまま）。
import assert from 'node:assert/strict';
import test from 'node:test';
import {meruhenNetDetail} from '../../share_viewer/net.mjs';
import {readFileSync} from 'node:fs';
import {
  compactSigned, dayNet, daySummary, displayMachineName, enteredInAdvance, eventComparison, eventLabel, indexRecords,
  meruhenRecords, mergeEvents, monthWeeks, pscubeRecords, scriptIdFrom, storeLabel, viewerNameFrom,
  calendarDays, idleVarietyRacks, isHiddenMachine, storeDays,
  lastRainbowDay, lastRainbowText, rackMark, storeHasRainbow,
  VARIETY_SORTS, applyRainbowMarks, isoTime, markTime, mergeMarks, varietyRainbowRows, varietyRecordRows,
  byLongestGap, daysSinceRainbow, rackDays, rainbowVarietyMax, windowDays,
  lineupDay, suffixReport, isZorome, hasSuffixSummary,
  rackWon, showWinRate, winRateText, daySummaries, calendarDay,
  monthDayList, periodWinRate, winRateYears, yearWinRates, loadFailureReason, loadFailureText,
  characterBirthdayCellLabel, characterBirthdayLabel, characterBirthdaysOn, parseCharacterBirthdays,
  lowGames, lowGamesNote, machinePickups,
} from '../../share_viewer/data.mjs';

function measurement(heights, withCurve = true) {
  const curve = heights.map((h, i) => [i * 10 + 0.5, 200.5 - h]);
  const ys = curve.map(p => p[1]);
  return {baseline_y: 200.5, peak_y: Math.min(...ys), trough_y: Math.max(...ys), end_y: curve.at(-1)[1], ...(withCurve ? {curve} : {})};
}
const net = (heights, maxHold, games) => meruhenNetDetail(measurement(heights), maxHold, games);
const down = [0, 0, 0, -5, -17, -17, -18, -36, -40, -55, -75, -89, -87, -109, -106, -105, -116, -139, -156, -161, -161];

test('終点の半px補正：正負共通、全座標と4点、ゼロ線へ戻る日と一日中ゼロ', () => {
  for (const [heights, expected] of [[[0, 60, 30], 164], [[0, 60, -30], -169]]) {
    for (const withCurve of [true, false]) {
      assert.equal(meruhenNetDetail(measurement(heights, withCurve), 400).value, expected);
    }
  }
  assert.equal(net([0, 60, 0], 400).value, -3);
  assert.equal(net([0, 0, 0], 0).value, 0);
});

test('推定差枚：PC・Androidと同じ例で同じ値（段階の選び方・回転数での選び直し・決められない台）', () => {
  assert.equal(net([0, -63, 40, 147, 128], 2376).value, 1417);
  assert.equal(net([0, -8, 163, 97], 1982).value, 1072);
  assert.equal(net([0, 60, 30], 400).value, 164);
  assert.equal(net([0, 120, 40, -50], 2900).value, -1122);
  assert.equal(net([0, 50, 20], null).value, null);
  assert.equal(net([0, 50, 20], 88888888).value, null);
  assert.equal(net([0, 0, 0], 0).value, 0);
  assert.equal(net([0, -40, -80], 0).value, null);
  assert.equal(meruhenNetDetail({baseline_y: 150.5, peak_y: 100, trough_y: 160, end_y: 120}, 500).value, null);
  assert.equal(meruhenNetDetail(null, 500).value, null);
  assert.deepEqual(net(down, 234), {value: -8972, needsCheck: false});
  assert.deepEqual(net(down, 234, 1634), {value: -1794, needsCheck: true});
  assert.equal(net([0, 0, 0, -4, -4, -13, -21, -21, -26, -26, -28, -73, -69, -70, -77, -77, -95, -95, -112, -145, -161, -161], 293, 790).value, -897);
  assert.equal(net([0, 0, 0, -1, -24, -44, -41, -48, -48, -64, -81, -80, -72, -92, -98, -98, -98], 279, 1228).value, -1094);
  assert.deepEqual(net([0, 0, 0, -136, -133, -133], 113, 168), {value: null, needsCheck: false});
  assert.deepEqual(net([0, 0, 0, -136, -133, -133], 113, 300), {value: -742, needsCheck: true});
  assert.deepEqual(net([0, -63, 40, 147, 128], 2376, 8584), {value: 1417, needsCheck: false});
  // 4点だけ（曲線なし）。
  const known = {baseline_y: 200.5, peak_y: 200.5 - 147, trough_y: 200.5 + 63, end_y: 200.5 - 128, peak_x: 300, trough_x: 100, end_x: 356};
  assert.equal(meruhenNetDetail(known, 2376).value, 1417);
  const ambiguous = {baseline_y: 200.5, peak_y: 100.5, trough_y: 370.5, end_y: 360.5, peak_x: 100, trough_x: 300, end_x: 356};
  assert.equal(meruhenNetDetail(ambiguous, 1500).value, null);
  const noX = {baseline_y: 200.5, peak_y: 200.5 - 147, trough_y: 200.5 + 63, end_y: 200.5 - 128};
  assert.equal(meruhenNetDetail(noX, 2376).value, 1417);
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

test('機種別ピックアップは合計差枚順で7件まで、欠損と0枚を区別して集計する', () => {
  const row = (machine, net, games, extra) => ({store: 'nagamachiminami', machine, net, games, bb: 1, rb: 1, ...extra});
  const rows = [
    row('機種A', 1800, 2000, {estimated: true}), row('機種A', -301, 1000),
    row('機種A', null, 1000, {graph: {baseline_y: 10, end_y: 8}}), row('機種A', null, 0),
    row('機種B', 1499, 5000), row('機種C', 0, 0), row('未取得', null, 8000),
    ...[-1, -2, -3, -4, -5].map((net, i) => row(`機種${i + 4}`, net, 1000)),
  ];
  const pickups = machinePickups(rows);
  assert.deepEqual(pickups.map(x => [x.machine, x.total]),
    [['機種A', 1499], ['機種B', 1499], ['機種C', 0], ['機種4', -1], ['機種5', -2], ['機種6', -3], ['機種7', -4]]);
  assert.deepEqual(pickups[0], {machine: '機種A', total: 1499, captured: 2, racks: 4, judged: 3, won: 2,
    averageNet: 750, averageGames: 1000, estimated: true});
  assert.equal(pickups[1].averageNet, 1499, '平均差枚が高くても、順位は合計差枚で決める');
  assert.equal(pickups[2].judged, 0, '0回転は勝率に数えない');
  assert.deepEqual(machinePickups([row('未取得', null, 1000)]), []);
});

test('台の読み込み：数値異常の台は数えず、差枚の無い日は0にしない。P’s CUBEは貸玉ごと・沖ドキは外す', () => {
  const m = meruhenRecords({records: [
    {store: 'saiwaichou', day: '2026-10-04', machine: '北斗', rack: 1, games: 3000, bb: 10, rb: 5, max_hold: 2376, graph_measurement: measurement([0, -63, 40, 147, 128])},
    {store: 'saiwaichou', day: '2026-10-04', machine: '北斗', rack: 2, games: 88888888, bb: 10, rb: 5, max_hold: 2376, graph_measurement: measurement([0, -63, 40, 147, 128])},
    {store: 'saiwaichou', day: '2026-10-05', machine: '北斗', rack: 3, games: 1000, bb: 1, rb: 1, max_hold: 100},
    {store: 'elsewhere', day: '2026-10-05', machine: 'x', rack: 1},
  ]});
  const byDay = indexRecords(m);
  assert.deepEqual(dayNet(byDay.get('saiwaichou|2026-10-04')), {total: 1417, captured: 1, racks: 1, judged: 1, won: 1, winRate: false});
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
  // アナスロで補った台の推定差枚（2026-11-06）：確かでない台は※、合計に入る。壊れた形・本当の差枚がある台では使わない。
  const anaslo = (rack, net_estimate, extra = {}) => ({store: 'c740601', rate: '20', day: '2026-11-04', machine: 'ﾏｲｼﾞｬｸﾞﾗｰV', rack,
    games: 3000, bb: 10, rb: 5, my: null, net_medals: null, source_site: 'anaslo', net_estimate, ...extra});
  const est = pscubeRecords({format: 'pscube-viewer', records: [
    anaslo(11, {value: 420, sure: true, method: 'anaslo-graph-v1'}),
    anaslo(12, {value: -650, sure: false, method: 'anaslo-graph-v1'}),
    anaslo(13, {value: 1.5, sure: true, method: 'anaslo-graph-v1'}),
    anaslo(14, {value: 100, sure: true, method: 'anaslo-graph-v1'}, {source_site: undefined, net_medals: -7}),
  ]});
  assert.deepEqual(est.map(r => [r.rack, r.net, r.needsCheck, r.estimated]),
    [[11, 420, false, true], [12, -650, true, true], [13, null, false, false], [14, -7, false, false]]);
  assert.deepEqual(dayNet(indexRecords(est).get('pscube:c740601:20|2026-11-04')).total, 420 - 650 - 7);
});

test('イベント：入力時刻の新しい方、時刻のある方が勝つ、消した印は出さない、その日の03:00より前の入力は＊なし（2026-10-26に2時から3時へ）', () => {
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
  assert.equal(enteredInAdvance({day: '2026-10-10', at: Date.parse('2026-10-10T02:30:00+09:00')}), true);
  assert.equal(enteredInAdvance({day: '2026-10-10', at: Date.parse('2026-10-10T02:59:59+09:00')}), true);
  assert.equal(enteredInAdvance({day: '2026-10-10', at: Date.parse('2026-10-10T03:00:00+09:00')}), false);
  assert.equal(eventLabel(mergeEvents([{store: 'saiwaichou', day: '2026-10-04', name: '半列'}]).get('saiwaichou|2026-10-04')), '半列＊', '時刻不明は＊');
});

test('イベントの小数秒6桁比較：同ミリ秒内の削除復活防止・受信順反転・時差表記違いの同一時刻・旧形式・03時境界', () => {
  const removed = {store: 'saiwaichou', day: '2026-12-12', name: null, updated_at: '2026-11-26T00:00:00.123900Z'};
  const oldNamed = {store: 'saiwaichou', day: '2026-12-12', name: '旧名', updated_at: '2026-11-26T00:00:00.123100Z'};
  // 削除先→旧名後、および旧名先→削除後のどちらでも削除が勝つ。
  assert.equal(eventLabel(mergeEvents([removed], [oldNamed]).get('saiwaichou|2026-12-12')), '');
  assert.equal(eventLabel(mergeEvents([oldNamed], [removed]).get('saiwaichou|2026-12-12')), '');
  // 逆に新名が後なら、どちらの順でも新名が勝つ。
  const newerNamed = {store: 'saiwaichou', day: '2026-12-12', name: '新名', updated_at: '2026-11-26T09:00:00.123900+09:00'};
  const olderRemoved = {store: 'saiwaichou', day: '2026-12-12', name: null, updated_at: '2026-11-26T00:00:00.123100Z'};
  assert.equal(eventLabel(mergeEvents([olderRemoved], [newerNamed]).get('saiwaichou|2026-12-12')), '新名');
  assert.equal(eventLabel(mergeEvents([newerNamed], [olderRemoved]).get('saiwaichou|2026-12-12')), '新名');
  // 時差表記だけが異なる同一時刻は、真に同時として後から読み込んだ方が勝つ。
  const utcSame = {store: 'saiwaichou', day: '2026-12-13', name: 'UTC側', updated_at: '2026-11-26T03:00:00.123456Z'};
  const jstSame = {store: 'saiwaichou', day: '2026-12-13', name: 'JST側', updated_at: '2026-11-26T12:00:00.123456+09:00'};
  const jstCompact = {store: 'saiwaichou', day: '2026-12-13', name: 'JST短縮', updated_at: '2026-11-26T12:00:00.123456+0900'};
  assert.equal(mergeEvents([utcSame], [jstSame]).get('saiwaichou|2026-12-13').name, 'JST側');
  assert.equal(mergeEvents([jstSame], [utcSame]).get('saiwaichou|2026-12-13').name, 'UTC側');
  assert.equal(mergeEvents([utcSame], [jstCompact]).get('saiwaichou|2026-12-13').name, 'JST短縮');
  // 時刻なしの旧形式：時刻ありが常に勝ち、両方時刻なしは手元（先）を残す。
  const untimedA = {store: 'saiwaichou', day: '2026-12-14', name: '旧形式A'};
  const untimedB = {store: 'saiwaichou', day: '2026-12-14', name: '旧形式B'};
  const timedRemove = {store: 'saiwaichou', day: '2026-12-14', name: null, updated_at: '2026-11-26T00:00:00.000001Z'};
  assert.equal(mergeEvents([untimedA], [untimedB]).get('saiwaichou|2026-12-14').name, '旧形式A');
  assert.equal(mergeEvents([untimedA], [timedRemove]).get('saiwaichou|2026-12-14').name, null);
  assert.equal(mergeEvents([timedRemove], [untimedA]).get('saiwaichou|2026-12-14').name, null);
  // 日本時間03時の境界（小数秒6桁、JST・UTC両表記）。
  const at = (updated_at) => mergeEvents([{store: 'saiwaichou', day: '2026-10-10', name: '華の日', updated_at}]).get('saiwaichou|2026-10-10');
  assert.equal(enteredInAdvance(at('2026-10-10T02:59:59.999999+09:00')), true);
  assert.equal(eventLabel(at('2026-10-09T17:59:59.999999Z')), '華の日');
  assert.equal(enteredInAdvance(at('2026-10-10T03:00:00.000000+09:00')), false);
  assert.equal(eventLabel(at('2026-10-09T18:00:00.000000Z')), '華の日＊');
  assert.equal(enteredInAdvance(at('2026-10-10T03:00:00.000001+09:00')), false);
  assert.equal(eventLabel(at('2026-10-09T18:00:00.000001Z')), '華の日＊');
});

test('イベント比較：同じ店と貸玉の直近3回、月をまたぐ連続日、欠測と0枚、機種別の延べ台数', () => {
  const store = 'pscube:c740601:20';
  const event = (day, extra) => ({store: 'c740601', rate: '20', day, name: '取材', ...extra});
  const events = mergeEvents([
    ...['2026-12-10', '2026-12-18', '2026-12-22', '2026-12-31', '2027-01-01', '2027-01-10'].map(day => event(day)),
    event('2026-12-30', {rate: '5'}), event('2026-12-20', {store: 'saiwaichou', rate: null}),
    event('2026-12-23', {name: '別の取材'}),
  ]);
  const row = (net, extra) => ({store, machine: 'ﾏｲｼﾞｬｸﾞﾗｰV', games: 1000, net, ...extra});
  const byDay = new Map([
    [`${store}|2026-12-18`, [row(0), row(null)]],
    [`${store}|2026-12-31`, [row(1200), row(-100)]],
    [`${store}|2027-01-01`, [row(100, {machine: 'マイジャグラーV', estimated: true}), row(null, {machine: '別機種'})]],
  ]);
  const report = eventComparison(events, byDay, store, '2026-12-31');
  assert.deepEqual(report.rounds.map(r => [r.from, r.to, r.recordedDays]),
    [['2026-12-31', '2027-01-01', 2], ['2026-12-22', '2026-12-22', 0], ['2026-12-18', '2026-12-18', 1]]);
  assert.deepEqual(report.rounds[0].byMachine.get('マイジャグラーV'),
    {won: 2, judged: 3, captured: 3, total: 1200, estimated: true});
  assert.equal(report.rounds[0].byMachine.get('別機種').captured, 0);
  assert.equal(report.rounds[1].byMachine.size, 0);
  assert.deepEqual(report.rounds[2].byMachine.get('マイジャグラーV'),
    {won: 0, judged: 1, captured: 1, total: 0, estimated: false});
  assert.deepEqual(eventComparison(events, byDay, store, '2026-12-10').rounds.map(r => r.from), ['2026-12-10']);
  assert.deepEqual(eventComparison(events, byDay, store, '2026-12-24').rounds, []);
});

test('長町南のイベント比較：月曜で別の回に分け、同じ週に別イベントを挟んでも同じ回', () => {
  const store = 'nagamachiminami';
  const events = mergeEvents([
    ...['2026-11-01', '2026-11-02', '2026-11-04', '2026-11-09'].map(day => ({store, day, name: '半列'})),
    {store, day: '2026-11-03', name: '新台入替'},
  ]);
  const {rounds} = eventComparison(events, new Map(), store, '2026-11-02');
  assert.deepEqual(rounds.map(r => [r.from, r.to, r.days]),
    [['2026-11-02', '2026-11-04', 2], ['2026-11-01', '2026-11-01', 1]]);
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

test('回っていない台：条件を変えても過去日の索引を作り直さず、履歴を更新したら結果も変える', () => {
  const byDay = idleSample();
  const first = byDay.get(`nagamachiminami|${day(1)}`).find(r => r.rack === 10);
  const machine = first.machine;
  let reads = 0;
  Object.defineProperty(first, 'machine', {get: () => { reads++; return machine; }});
  assert.deepEqual(picks(byDay, 10, {gamesLimit: 3000}), [['A', 10, 10], ['B', 20, 10], ['B', 21, 10]]);
  assert.ok(reads > 0);
  reads = 0;
  assert.deepEqual(picks(byDay, 9, {gamesLimit: 3000}), [['A', 10, 9], ['B', 20, 9], ['B', 21, 9]]);
  assert.deepEqual(picks(byDay, 10, {gamesLimit: 500}), [['A', 10, 9]]);
  assert.equal(reads, 0, '選択日・回転数を変えても同じ過去日を索引化し直さない');
  const updated = idleSample();
  updated.get(`nagamachiminami|${day(10)}`).find(r => r.rack === 10).games = 3000;
  assert.deepEqual(picks(updated, 10, {gamesLimit: 500}), []);
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
  assert.equal(otherDay.net, 1417);
  assert.equal(otherStore.net, 1417);
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

test('月間・年間の勝率：日ごとの台数を足して割る（日の勝率の平均ではない）。台データの日とHTMLの集計の日を合わせる', () => {
  // 2026-10-18 利用者「月ごとに月間の勝率出すのと、年間でも見れるページつくっておいてね」。
  assert.equal(monthDayList(2026, 2).length, 28);
  assert.equal(monthDayList(2024, 2).at(-1), '2024-02-29');
  assert.deepEqual([monthDayList(2026, 10)[0], monthDayList(2026, 10).at(-1)], ['2026-10-01', '2026-10-31']);
  const byDay = indexRecords(meruhenRecords({records: [
    // 10/2：台データ2台（プラス1・マイナス1）。この日の集計（999台中0台）は使わない。
    {store: 'saiwaichou', day: '2026-10-02', machine: 'M', rack: 1, games: 3000, bb: 5, rb: 2, graph_measurement: measurement([0, 80, 50])},
    {store: 'saiwaichou', day: '2026-10-02', machine: 'M', rack: 2, games: 3000, bb: 5, rb: 2, graph_measurement: measurement([0, 20, -30])},
    {store: 'nagamachiminami', day: '2026-10-02', machine: 'M', rack: 1, games: 3000, bb: 5, rb: 2, graph_measurement: measurement([0, 80, 50])},
  ]}));
  const summaries = daySummaries({day_summaries: [
    {store: 'saiwaichou', day: '2026-10-02', racks: 999, judged: 999, won: 0},
    {store: 'saiwaichou', day: '2026-10-03', racks: 110, judged: 100, won: 10},
    {store: 'saiwaichou', day: '2026-09-15', racks: 536, judged: 534, won: 201},
    {store: 'saiwaichou', day: '2025-12-31', racks: 536, judged: 523, won: 204},
  ]});
  const october = periodWinRate(byDay, summaries, 'saiwaichou', monthDayList(2026, 10));
  assert.deepEqual(october, {judged: 102, won: 11, days: 2});
  assert.equal(winRateText(october.won, october.judged), '勝率11%', '日の勝率の平均（30%）ではない');
  const year = yearWinRates(byDay, summaries, 'saiwaichou', 2026);
  assert.deepEqual(year.months.filter(m => m.judged).map(m => [m.month, m.judged, m.won, m.days]), [[9, 534, 201, 1], [10, 102, 11, 2]]);
  assert.deepEqual(year.total, {judged: 636, won: 212, days: 3});
  assert.deepEqual(winRateYears(byDay, summaries, 'saiwaichou'), [2026, 2025]);
  assert.deepEqual(winRateYears(byDay, summaries, 'nagamachiminami'), [2026]);
  assert.deepEqual(yearWinRates(byDay, summaries, 'saiwaichou', 2024).total, {judged: 0, won: 0, days: 0});
});

test('読み込みの失敗の理由：どの店が何で失敗したかを短く出す', () => {
  // 2026-10-18 利用者「最新を読み込んでも毎回一部の更新に失敗しましたと出る」。理由が出ず、原因を決められなかった。
  const ok = {status: 'fulfilled', value: {records: []}};
  const timeout = {status: 'rejected', reason: Object.assign(new Error('This operation was aborted'), {name: 'AbortError'})};
  const offline = {status: 'rejected', reason: new TypeError('Failed to fetch')};
  const http = {status: 'rejected', reason: new Error('読み込めませんでした（500）')};
  const script = {status: 'fulfilled', value: {error: '閲覧用の日別ファイルが見つかりません。同期を再実行してください。'}};
  assert.equal(loadFailureReason(ok), '');
  assert.equal(loadFailureReason(timeout), '時間切れ（30秒）');
  assert.equal(loadFailureReason(offline), '通信できませんでした');
  assert.equal(loadFailureReason(http), '読み込めませんでした（500）');
  assert.equal(loadFailureReason({status: 'fulfilled', value: null}), '中身が空でした');
  assert.equal(loadFailureText([['メルヘン', timeout], ['P-STATION', script]]),
    'メルヘン：時間切れ（30秒）、P-STATION：閲覧用の日別ファイルが見つかりません。同期を再実行してください。');
  assert.equal(loadFailureText([['メルヘン', ok], ['P-STATION', http]]), 'P-STATION：読み込めませんでした（500）');
  assert.equal(loadFailureReason({status: 'rejected', reason: new Error('x'.repeat(200))}).length, 80);
});

// キャラ誕生日（EVENT_CALENDAR.md「キャラ誕生日」、2026-10-18）。PC tests/test_character_birthdays.py・
// Flutter test/event_calendar_test.dart「キャラ誕生日」と同じ例で同じ答え。
const entry = (month, day, name, work = '作品') => ({month, day, name, work});
const sampleBirthdays = parseCharacterBirthdays({entries: [
  entry(2, 29, 'カイン・ドレッセル', '革命機ヴァルヴレイヴ'),
  entry(3, 1, 'ムーンライトルナシー', 'ウマ娘'),
  entry(10, 30, '天猛星ワイバーンのラダマンティス', '聖闘士星矢'),
]});
const labelsOn = (day) => characterBirthdaysOn(sampleBirthdays, day).map(b => b.label);

test('キャラ誕生日：壊れた形は空、おかしな項目・無い日は飛ばし、同じ人は1つ', () => {
  for (const bad of [null, [1], {entries: {}}, 'x']) assert.equal(parseCharacterBirthdays(bad).size, 0);
  const loaded = parseCharacterBirthdays({entries: [
    'x', null, [1], entry(2, 30, '無い日'), entry(4, 31, '無い日'), entry(13, 1, '無い月'), entry(0, 1, '無い月'),
    entry(1, 1.5, '小数'), {month: '1', day: 1, name: '文字の月'}, entry(1, 1, '  '), entry(1, 1, 5),
    entry(2, 29, 'うるう日'), entry(1, 1, ' 元日 ', 3), entry(5, 5, '同じ人'), entry(5, 5, '同じ人'),
  ]});
  assert.deepEqual([...loaded.keys()].sort(), ['01-01', '02-29', '05-05']);
  assert.deepEqual(loaded.get('05-05'), [{name: '同じ人', work: '作品'}]);
  assert.deepEqual(loaded.get('01-01'), [{name: '元日', work: ''}]);
});

test('キャラ誕生日：一覧は「名前（作品）」、2/29生まれはうるう年以外3/1に出す', () => {
  assert.deepEqual(labelsOn('2026-10-30'), ['天猛星ワイバーンのラダマンティス（聖闘士星矢）']);
  assert.equal(characterBirthdayLabel('名無し', ''), '名無し');
  assert.deepEqual(labelsOn('2027-03-01'), ['ムーンライトルナシー（ウマ娘）', 'カイン・ドレッセル（革命機ヴァルヴレイヴ、2/29生まれ）']);
  assert.equal(labelsOn('2100-03-01').at(-1), 'カイン・ドレッセル（革命機ヴァルヴレイヴ、2/29生まれ）', '100で割れて400で割れない年もうるう年でない');
  assert.deepEqual(labelsOn('2028-03-01'), ['ムーンライトルナシー（ウマ娘）']);
  assert.deepEqual(labelsOn('2028-02-29'), ['カイン・ドレッセル（革命機ヴァルヴレイヴ）']);
  assert.deepEqual(labelsOn('2027-02-28'), []);
  assert.equal(characterBirthdayCellLabel([]), '');
  assert.equal(characterBirthdayCellLabel(['キリト']), '🎂 キリト');
  assert.equal(characterBirthdayCellLabel(['a', 'b', 'c', 'd']), '🎂 a・b ほか2名');
});

test('キャラ誕生日：収録データを全件読み、PC・Flutterと同じ並び', () => {
  const doc = JSON.parse(readFileSync(new URL('../assets/character_birthdays.json', import.meta.url), 'utf-8'));
  const all = parseCharacterBirthdays(doc);
  assert.equal([...all.values()].reduce((n, v) => n + v.length, 0), doc.entries.length);
  assert.ok(doc.entries.length >= 573);
  const daysOf = (name) => [...all].filter(([, v]) => v.some(b => b.name === name)).map(([k]) => k);
  assert.deepEqual(daysOf('柴大寿'), ['07-24'], '一覧には12/15もあるが、利用者の指定で7/24だけ');
  assert.deepEqual(characterBirthdaysOn(all, '2026-10-20').map(b => b.name), ['天秤座の童虎', '灰谷竜胆', '無名'],
    '名前順（PCの sorted・Dartの compareTo と同じ並び）');
});

test('その日のまとめ：0回転の台と500回転未満の台の数（2026-10-21）', () => {
  const g = (games) => ({games});
  const racks = [0, 0, 1, 499, 500, 3000].map(g);
  assert.deepEqual(lowGames(racks), {zero: 2, short: 2}, '0回転は500回転未満に含めない・500Gちょうどは入れない');
  assert.equal(lowGamesNote(racks), '（2台が0回転。2台が500回転未満）');
  assert.equal(lowGamesNote([0, 0].map(g)), '（2台が0回転）');
  assert.equal(lowGamesNote([10].map(g)), '（1台が500回転未満）');
  assert.equal(lowGamesNote([500, 1000].map(g)), '', 'どちらも無ければ何も出さない');
});


test('🌈の分割送信：5,001件以上を保持し、失敗で停止して再送できる', async () => {
  const {sendRainbowBatches}=await import('../../share_viewer/data.mjs');
  const marks=Array.from({length:10001},(_,i)=>({rack:i+1,on:i%2===0,updated_at:'2026-10-29T00:00:00Z'}));
  const before=JSON.stringify(marks), sent=[];
  const failed=await sendRainbowBatches(marks,async body=>{sent.push(body);return sent.length===2?{error:'合成の失敗'}:{ok:true};},async()=>true);
  assert.equal(failed.error,'合成の失敗');assert.deepEqual(sent.map(b=>b.marks.length),[5000,5000]);
  const retry=[];assert.equal((await sendRainbowBatches(marks,async body=>{retry.push(body);return {ok:true};},async()=>true)).ok,true);
  assert.deepEqual(retry.map(b=>b.marks.length),[5000,5000,1]);
  assert.deepEqual(retry.flatMap(b=>b.marks),marks);assert.equal(JSON.stringify(marks),before);
  await assert.rejects(sendRainbowBatches(marks,async()=>{throw Error('通信失敗');},async()=>true),/通信失敗/);
});


test('🌈の独立保存：不正な1件も捨てずに停止し、重複は新しい方を残す', async () => {
  const {storedRainbowMarks}=await import('../../share_viewer/data.mjs');
  const old={store:'saiwaichou',day:'2026-10-28',rack:1,on:true,updated_at:'2026-10-29T00:00:00Z'};
  const newer={...old,on:false,updated_at:'2026-10-29T01:00:00Z'};
  for(const text of ['null','{}','[null]',JSON.stringify([old,{bad:true}])]) assert.throws(()=>storedRainbowMarks(text));
  assert.deepEqual(storedRainbowMarks(null),[]);
  assert.deepEqual(storedRainbowMarks(JSON.stringify([newer,old])),[newer]);
});


test('大量の🌈は保存保護の対応確認が無ければ送信せず、通常件数は従来どおり',async()=>{
  const {sendRainbowBatches,sharedRainbowCanBatch}=await import('../../share_viewer/data.mjs');
  for(const doc of [null,{}, {format:'database-release',capabilities:[]},{format:'wrong',capabilities:['rainbow-storage-v2']}]) assert.equal(sharedRainbowCanBatch(doc),false);
  assert.equal(sharedRainbowCanBatch({format:'database-release',capabilities:['rainbow-storage-v2']}),true);
  const marks=Array.from({length:5001},(_,i)=>({rack:i+1}));let posts=0;
  assert.match((await sendRainbowBatches(marks,async()=>{posts++;return {ok:true};})).error,/Googleスクリプトの更新/);
  assert.equal(posts,0);assert.equal(marks.length,5001);
  assert.equal((await sendRainbowBatches(marks.slice(0,5000),async()=>{posts++;return {ok:true};},()=>{throw Error('通常件数で確認不要');})).ok,true);
  assert.equal(posts,1);
});


test('Googleの保存保護の診断を共有の読み込み経路で取得できる',async()=>{
  const {fetchShared}=await import('../web/shared_events.mjs');const calls=[];
  const result=await fetchShared('https://script.google.com/macros/s/TEST_DIAG/exec','diagnostic',async url=>{
    calls.push(url);return new Response('{"format":"database-release","capabilities":["rainbow-storage-v2"]}',{status:200});
  });
  assert.equal(JSON.parse(result).format,'database-release');assert.equal(calls.length,1);
  assert.match(calls[0],/file=diagnostic$/);
  await assert.rejects(fetchShared('https://script.google.com/macros/s/TEST_DIAG/exec','arbitrary',()=>{throw Error('呼ばない');}),/不正/);
});


test('重複は一度だけ・競合は全件保留し、入力を変えず全集計へ共通適用', () => {
  const r={store:'saiwaichou',day:'2026-10-01',machine:'テスト',rack:1,games:1000,bb:1,rb:1,net:1000};
  const input=[r,{...r}], before=JSON.stringify(input);
  const same=indexRecords(input);
  assert.equal(dayNet(same.get('saiwaichou|2026-10-01')).total,1000);
  assert.equal(same.issues[0].kind,'duplicate');
  assert.equal(JSON.stringify(input),before);
  const conflict=indexRecords([r,{...r,net:-1000}, {...r,rack:2,net:0}]);
  const day=dayNet(conflict.get('saiwaichou|2026-10-01'));
  assert.equal(day.total,0); assert.equal(day.racks,1);assert.equal(day.judged,1);
  assert.equal(conflict.issues[0].kind,'conflict');
});

test('換算額：0・小額の正負・欠測、丸めない58枚単価',async()=>{
  const {exchangeValue}=await import('../../share_viewer/data.mjs');
  assert.equal(exchangeValue(null,50),'—'); assert.equal(exchangeValue(0,50),'0円');
  assert.equal(exchangeValue(1,50),'約＋20円');assert.equal(exchangeValue(-1,50),'約−20円');
  assert.equal(exchangeValue(256185,50),'約＋512.4万円');
  assert.equal(exchangeValue(81073,58),'約＋139.8万円');
  assert.equal(exchangeValue(58,58),'約＋1,000円');
});


test('推定差枚の説明は取得元別・混在に対応し、確定値に誤った推定説明を付けない',async()=>{
 const {netEstimateNote}=await import('../../share_viewer/data.mjs');
 const site={store:'pscube:c740601:20',source_site:'site777',estimated:true,net:1234};
 assert.match(netEstimateNote([site]),/サイトセブン.*グラフ画像/);
 assert.doesNotMatch(netEstimateNote([site]),/アナスロ|50枚/);
 assert.match(netEstimateNote([site]),/1枚単位の精度を保証するものではありません/);
 const a={...site,source_site:'anaslo'};
 assert.match(netEstimateNote([a]),/アナスロ.*BB・RB・G数/);
 assert.match(netEstimateNote([a,site]),/サイトセブン/);
 assert.match(netEstimateNote([a,site]),/アナスロ/);
 assert.equal(netEstimateNote([{...site,estimated:false}]),'');
 assert.equal(netEstimateNote([{...site,net:null}]),'');
});

test('カレンダーのヒートマップ段階：1台平均差枚の境界・0・勝率のみ・欠測を区別する', async () => {
  const {dayHeatLevel} = await import('../../share_viewer/data.mjs');
  assert.equal(dayHeatLevel(null), 'empty');
  assert.equal(dayHeatLevel({total: null, captured: 0, winRate: false}), 'empty');
  assert.equal(dayHeatLevel({total: 1000, captured: 0, winRate: false}), 'empty');
  assert.equal(dayHeatLevel({total: null, captured: 0, winRate: true}), 'rate');
  assert.equal(dayHeatLevel({total: 5000, captured: 20, winRate: false}), 'plus-3');
  assert.equal(dayHeatLevel({total: 4999, captured: 20, winRate: false}), 'plus-2');
  assert.equal(dayHeatLevel({total: 2000, captured: 20, winRate: false}), 'plus-2');
  assert.equal(dayHeatLevel({total: 1999, captured: 20, winRate: false}), 'plus-1');
  assert.equal(dayHeatLevel({total: 1, captured: 20, winRate: false}), 'plus-1');
  assert.equal(dayHeatLevel({total: 0, captured: 20, winRate: false}), 'zero');
  assert.equal(dayHeatLevel({total: -1, captured: 20, winRate: false}), 'minus-1');
  assert.equal(dayHeatLevel({total: -1999, captured: 20, winRate: false}), 'minus-1');
  assert.equal(dayHeatLevel({total: -2000, captured: 20, winRate: false}), 'minus-2');
});

test('台詳細の直近7日間の推移：基準日以前の最大7記録日・別機種の区別・イベントを返す', async () => {
  const {rackRecentHistory, mergeEvents} = await import('../../share_viewer/data.mjs');
  const recs = Array.from({length: 9}, (_, i) => ({
    store: 'nagamachiminami',
    day: `2026-11-${String(18 + i).padStart(2, '0')}`,
    machine: i === 5 ? '旧機種A' : 'ｺﾞｰｺﾞｰｼﾞｬｸﾞﾗｰ3',
    rack: 101,
    games: 4000 + i * 200,
    bb: 15,
    rb: 10,
    net: i % 2 === 0 ? 1000 : -500,
    estimated: false,
    rainbow: i === 7,
  }));
  const byDay = indexRecords(recs);
  const events = mergeEvents([{store: 'nagamachiminami', day: '2026-11-25', name: '特日', updated_at: '2026-11-24T12:00:00+09:00'}]);
  const history = rackRecentHistory(byDay, events, 'nagamachiminami', 101, '2026-11-25', 7);
  assert.equal(history.length, 7);
  assert.equal(history[0].day, '2026-11-25');
  assert.equal(history[6].day, '2026-11-19');
  assert.equal(history[0].event, '特日');
  assert.equal(history[0].rainbow, true);
  assert.equal(history[0].sameMachine, true);
  const swapped = history.find(h => h.day === '2026-11-23');
  assert.equal(swapped.machine, '旧機種A');
  assert.equal(swapped.sameMachine, false);
  assert.deepEqual(rackRecentHistory(byDay, events, 'nagamachiminami', 101, '2026-11-25', 0), []);
});

test('クイック検索：半角カナ・全角カナ・ひらがな・全角英数のゆらぎ吸収と機種統合・台番優先', async () => {
  const {normalizeSearchText, searchStoreEntities, machineDayHistory, rackDayHistory, mergeEvents} = await import('../../share_viewer/data.mjs');
  assert.equal(normalizeSearchText('ﾏｲｼﾞｬｸﾞﾗｰＶ　３'), 'まいじゃぐらーv 3');
  const byDay = indexRecords([
    {store: 'pscube:c740601:20', day: '2026-11-25', machine: 'ﾏｲｼﾞｬｸﾞﾗｰV', rack: 55, games: 6000, bb: 25, rb: 20, net: 2000, estimated: false},
    {store: 'pscube:c740601:20', day: '2026-11-24', machine: 'マイジャグラーV', rack: 55, games: 4000, bb: 10, rb: 10, net: -500, estimated: true},
    {store: 'pscube:c740601:20', day: '2026-11-25', machine: '北斗の拳', rack: 155, games: 5000, bb: 20, rb: 5, net: 1200, estimated: false},
    {store: 'pscube:c740601:20', day: '2026-11-25', machine: 'ハナハナ', rack: 550, games: 3000, bb: 8, rb: 6, net: -300, estimated: false},
  ]);
  const days = ['2026-11-25', '2026-11-24'];
  const empty = searchStoreEntities(byDay, 'pscube:c740601:20', days, '');
  assert.equal(empty.machines.length, 3, '半角カナと全角カナのマイジャグラーVを1機種に統合');
  assert.equal(empty.racks.length, 0);
  assert.equal(empty.featured[0].machine, 'マイジャグラーV');

  for (const q of ['まいじゃぐ', 'ﾏｲｼﾞｬｸﾞ', 'マイジャグラーＶ']) {
    const res = searchStoreEntities(byDay, 'pscube:c740601:20', days, q);
    assert.equal(res.machines.length, 1);
    assert.equal(res.machines[0].machine, 'マイジャグラーV');
    assert.equal(res.machines[0].totalNet, 1500);
    assert.equal(res.machines[0].daysCount, 2);
    assert.equal(res.machines[0].plusDays, 1);
  }

  const byRack = searchStoreEntities(byDay, 'pscube:c740601:20', days, '５５番');
  assert.equal(byRack.numericOnly, true);
  assert.deepEqual(byRack.racks.map(r => r.rack), [55, 550, 155], '完全一致→前方一致→部分一致の順');

  const events = mergeEvents([{store: 'c740601', rate: '20', day: '2026-11-25', name: '末尾イベ', updated_at: '2026-11-24T10:00:00+09:00'}]);
  const mh = machineDayHistory(byDay, events, 'pscube:c740601:20', 'マイジャグラーV', days);
  assert.equal(mh.entries.length, 2);
  assert.equal(mh.entries[0].day, '2026-11-25');
  assert.equal(mh.entries[0].rawMachine, 'ﾏｲｼﾞｬｸﾞﾗｰV');
  assert.equal(mh.entries[0].event, '末尾イベ');
  assert.equal(mh.summary.totalNet, 1500);
  assert.equal(mh.summary.plusDays, 1);
  assert.equal(mh.summary.estimated, true);

  const rh = rackDayHistory(byDay, events, 'pscube:c740601:20', 55, days);
  assert.equal(rh.entries.length, 2);
  assert.equal(rh.summary.totalNet, 1500);
  assert.equal(rh.summary.plusDays, 1);
  assert.equal(rh.summary.averageGames, 5000);
});

test('最新営業日の3店舗比較：台データ・HTML勝率集計のみ・記録なしを正確に比較する', async () => {
  const {latestStoreComparison, daySummaries, mergeEvents} = await import('../../share_viewer/data.mjs');
  const byDay = indexRecords([
    {store: 'nagamachiminami', day: '2026-11-26', machine: 'A', rack: 1, games: 5000, bb: 20, rb: 10, net: 1000, estimated: false},
    {store: 'nagamachiminami', day: '2026-11-26', machine: 'A', rack: 2, games: 5000, bb: 10, rb: 10, net: -200, estimated: false},
    {store: 'saiwaichou', day: '2026-11-25', machine: 'B', rack: 1, games: 4000, bb: 15, rb: 10, net: 500, estimated: true},
  ]);
  const summaries = daySummaries({day_summaries: [{store: 'saiwaichou', day: '2026-11-26', racks: 500, judged: 480, won: 200}]});
  const events = mergeEvents([{store: 'nagamachiminami', day: '2026-11-26', name: '全6祭', updated_at: '2026-11-25T10:00:00+09:00'}]);
  const rows = latestStoreComparison(byDay, summaries, events, ['nagamachiminami', 'saiwaichou', 'pscube:c740601:20']);
  assert.equal(rows[0].day, '2026-11-26');
  assert.equal(rows[0].total, 800);
  assert.equal(rows[0].averageNet, 400);
  assert.equal(rows[0].winRatePct, 50);
  assert.equal(rows[0].heat, 'plus-3');
  assert.equal(rows[0].event, '全6祭');
  assert.equal(rows[0].hasRacks, true);

  assert.equal(rows[1].day, '2026-11-26');
  assert.equal(rows[1].winRate, true);
  assert.equal(rows[1].winRatePct, 42);
  assert.equal(rows[1].heat, 'rate');
  assert.equal(rows[1].hasRacks, false);
  assert.equal(rows[1].hasSummary, true);

  assert.equal(rows[2].day, null);
  assert.equal(rows[2].heat, 'empty');
  assert.equal(rows[2].hasRacks, false);
  assert.equal(rows[2].hasSummary, false);
});

test('半角カナ・全角カナ・空白ゆれの同一機種判定：7日推移と機種順ソートで正しく扱う', async () => {
  const {sameMachineName, rackRecentHistory, allRacksOrder} = await import('../../share_viewer/data.mjs');
  assert.equal(sameMachineName('ﾏｲｼﾞｬｸﾞﾗｰV', 'マイジャグラーV'), true);
  assert.equal(sameMachineName('L+北斗の拳', 'L 北斗の拳'), true);
  assert.equal(sameMachineName('マイジャグラーV', 'ファンキージャグラー2'), false);
  const byDay = indexRecords([
    {store: 'pscube:c740601:20', day: '2026-11-22', machine: 'マイジャグラーV', rack: 55, games: 6000, bb: 25, rb: 20, net: 1500, estimated: true},
    {store: 'pscube:c740601:20', day: '2026-11-21', machine: 'ﾏｲｼﾞｬｸﾞﾗｰV', rack: 55, games: 5500, bb: 20, rb: 18, net: 800, estimated: false},
    {store: 'pscube:c740601:20', day: '2026-11-20', machine: '旧機種テスト', rack: 55, games: 4000, bb: 10, rb: 8, net: -600, estimated: false},
  ]);
  const history = rackRecentHistory(byDay, new Map(), 'pscube:c740601:20', 55, '2026-11-22', 7);
  assert.equal(history.length, 3);
  assert.equal(history[0].sameMachine, true);
  assert.equal(history[1].sameMachine, true, '半角カナ→全角カナ跨ぎでも同一機種と判定する');
  assert.equal(history[2].sameMachine, false);

  const ordered = allRacksOrder([
    {machine: 'ハナハナ', rack: 1},
    {machine: 'ｱｲﾑｼﾞｬｸﾞﾗｰ', rack: 2},
    {machine: 'マイジャグラー', rack: 3},
  ], 'machine');
  assert.deepEqual(ordered.map(r => r.rack), [2, 1, 3], '半角カナのアイムジャグラーが五十音順の先頭になる');
});



