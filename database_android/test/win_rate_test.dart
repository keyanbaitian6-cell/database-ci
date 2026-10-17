import 'package:flutter_test/flutter_test.dart';

import 'package:database_android/daily_net_page.dart';
import 'package:database_android/event_calendar_page.dart';
import 'package:database_android/models.dart';

/// 差枚の分からない日の勝率（2026-10-17 利用者「差枚を出せないところについては勝率を書いてほしい
/// 何台中何台プラスってところから割り出して」）。PC tests/test_win_rate.py・共有ページ
/// tool/test_share_viewer.mjs と同じ例で同じ答えになること。
Map<String, dynamic> measurement(List<double> heights) {
  final curve = [
    for (var i = 0; i < heights.length; i++) [i * 10 + 0.5, 200.5 - heights[i]],
  ];
  final ys = curve.map((p) => p[1]);
  return {
    'baseline_y': 200.5,
    'peak_y': ys.reduce((a, b) => a < b ? a : b),
    'trough_y': ys.reduce((a, b) => a > b ? a : b),
    'end_y': curve.last[1],
    'curve': curve,
  };
}

SlotRecord rack(int n, [Map<String, dynamic> extra = const {}]) =>
    SlotRecord.fromJson({
      'store': 'saiwaichou',
      'kind_code': 21,
      'day': '2026-09-10',
      'machine': 'M',
      'rack': n,
      'games': 3000,
      'bb': 5,
      'rb': 2,
      ...extra,
    });

final racks = [
  rack(1, {
    'graph_measurement': measurement([0, 80, 50]),
  }), // 終点+50px → プラス
  rack(2, {
    'graph_measurement': measurement([0, 20, -30]),
  }), // マイナス
  rack(3, {
    'graph_measurement': measurement([0, 40, 0.5]),
  }), // 1px以内 → プラスにしない
  rack(4, {'games': 2000, 'bb': 0, 'rb': 0}), // 大当たり0回 → マイナス
  rack(5, {'games': 0, 'bb': 0, 'rb': 0}), // 未稼働 → 数えない
  rack(6), // グラフ無し → 数えない
];

void main() {
  test('same examples as PC and the share page', () {
    expect(racks.map((r) => r.won).toList(), [
      true,
      false,
      false,
      false,
      null,
      null,
    ]);
    expect(winRateLabel(1, 4), '勝率25%');
    expect(winRateLabel(255, 532), '勝率48%');
    expect(winRateLabel(1, 8), '勝率13%');
    expect(showWinRate(1, 4), isTrue);
    expect(showWinRate(2, 4), isFalse);
    expect(showWinRate(0, 0), isFalse);
    final hidden = rack(1, {
      'store': 'nagamachiminami',
      'day': '2026-10-07',
      'graph_measurement': measurement([0, 80, 50]),
    });
    expect(hidden.won, isNull);
    expect(rack(1, {'jo_net': -1}).won, isFalse);
  });

  test('calendar cell shows the win rate only when most nets are unknown', () {
    final second = [
      for (final (r, net) in [
        (racks[0], 500),
        (racks[1], -200),
        (racks[2], null),
        (racks[3], null),
      ])
        SlotRecord.fromJson({
          ...r.toJson(),
          'day': '2026-09-11',
          'jo_net': ?net,
        }),
    ];
    final byDay = {
      for (final d in dailyNet([...racks, ...second], 'saiwaichou')) d.day: d,
    };
    final first = byDay['2026-09-10']!;
    expect([first.captured, first.judged, first.won], [0, 4, 1]);
    expect(first.showsWinRate, isTrue);
    expect(dayNetCellLabel(first), '勝率25%');
    final next = byDay['2026-09-11']!;
    expect([next.captured, next.judged], [2, 4]);
    expect(dayNetCellLabel(next), '+300');
  });
}
