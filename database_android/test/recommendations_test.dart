import 'package:database_android/event_history_model.dart';
import 'package:database_android/models.dart';
import 'package:database_android/recommendations.dart';
import 'package:database_android/recommendations_view.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

SlotRecord row(
  String machine,
  int rack, {
  String day = '2026-10-26',
  int? net = 0,
  String store = 'nagamachiminami',
}) => SlotRecord.fromJson({
  'store': store,
  'day': day,
  'machine': machine,
  'rack': rack,
  'games': 1000,
  'bb': 4,
  'rb': 2,
  'jo_net': ?net,
});

void main() {
  final selected = {
    ...recommendationDefault,
    'machines': ['機種A', '機種B', '機種C', '機種D'],
  };
  test('画像の4機種・10/26〜11/1を既定にして、4枠以外・重複・他店舗を拒否', () {
    expect(
      recommendationPlans([]).single['machines'],
      recommendationDefault['machines'],
    );
    expect(recommendationDays('2026-10-26').last, '2026-11-01');
    for (final change in [
      {'week': '2026-10-27'},
      {
        'machines': ['A', 'A', 'B', 'C'],
      },
      {
        'machines': ['A', 'B', 'C'],
      },
      {'store': 'saiwaichou'},
      {'updated_at': '2026-02-30T00:00:00Z'},
      {'updated_at': '2026-10-25T24:00:00Z'},
    ]) {
      expect(
        () => recommendationPlan({...selected, ...change}),
        throwsFormatException,
      );
    }
  });
  test('7台以上は最新の単一日・異なる台番号で判定。他店舗・未来・重複行を混ぜない', () {
    final rows = [
      for (var i = 0; i < 7; i++) row('7台', i),
      for (var i = 0; i < 6; i++) row('6台', i),
      for (var i = 0; i < 10; i++) row('6台', 0),
      for (var i = 0; i < 10; i++) row('他店', i, store: 'saiwaichou'),
      for (var i = 0; i < 10; i++) row('未来', i, day: '2026-11-02'),
    ];
    expect(recommendationCandidates(rows, '2026-10-26').machines, {'7台': 7});
    rows.add(row('新しい一部', 99, day: '2026-10-27'));
    expect(recommendationCandidates(rows, '2026-10-26').machines, isEmpty);
  });
  test('空の日があっても各台・各日の差枚を残し、0枚と欠測と重複を区別', () {
    final rows = [
      row('機種 A', 10, net: 0),
      row('機種+A', 10, day: '2026-10-28', net: 3000),
      row('別機種', 888),
      row('機種 A', 999, store: 'saiwaichou'),
    ];
    final result = recommendationRows(rows, '2026-10-26', '機種 A');
    expect(result.single.rack, 10);
    expect(result.single.cells[0]!.netValue, 0);
    expect(result.single.cells[1], isNull);
    expect(result.single.cells[2]!.netValue, 3000);
    rows.add(row('機種 A', 10, net: 9999));
    expect(
      recommendationRows(rows, '2026-10-26', '機種 A').single.cells[0],
      isNull,
    );
    expect([null, -1, 0, 999, 1000, 2999, 3000].map(recommendationFace), [
      '',
      '🥶',
      '😌',
      '😌',
      '😀',
      '😀',
      '😍',
    ]);
  });
  test('マイクロ秒順の選定と別週・不正原文を保持し、既存の履歴合流でも消さない', () {
    final old = {...selected, 'updated_at': '2026-10-25T09:00:00.123456+09:00'};
    final newer = {
      ...selected,
      'machines': ['別A', '別B', '別C', '別D'],
      'updated_at': '2026-10-25T00:00:00.123457Z',
    };
    final other = {...selected, 'week': '2026-11-02'};
    final raw = {'壊れた原文': true};
    final out = mergeRecommendations([old, other, raw], [newer]);
    expect(out, [other, newer, raw]);
    final base = {
      'version': 2,
      'store': 'nagamachiminami',
      'symbols': ['😍'],
      'weeks': [],
    };
    final merged = mergeHistoryEdits(
      {...emptyHistoryEdits(), 'recommendations': out},
      emptyHistoryEdits(),
      base,
    );
    expect(merged.edits['recommendations'], out);
    expect(parseHistoryEdits(merged.edits, base)['recommendations'], out);
  });
  test('台ごとの顔文字は空欄・自動・競合を区別し、保存・バックアップでも保つ', () {
    final r = {
      'store': 'nagamachiminami',
      'week': '2026-10-26',
      'machine': '機種A',
      'rack': 100,
      'day': '2026-10-26',
      'value': '😇',
      'updated_at': '2026-10-25T00:00:00.123456Z',
      'device': 'shared',
    };
    final blank = {
          ...r,
          'value': '',
          'updated_at': '2026-10-25T00:00:00.123457Z',
        },
        auto = {
          ...r,
          'value': null,
          'updated_at': '2026-10-25T00:00:00.123458Z',
        },
        bad = {...r, 'value': '未知'};
    expect(
      recommendationResultIndex([r])[recommendationResultKey(r)]!['value'],
      '😇',
    );
    expect(
      recommendationResultIndex(
        mergeRecommendationResults([r], [blank]),
      )[recommendationResultKey(r)]!['value'],
      '',
    );
    expect(
      recommendationResultIndex(
        mergeRecommendationResults([blank], [auto]),
      )[recommendationResultKey(r)]!['value'],
      isNull,
    );
    expect(recommendationResultIndex([bad]), isEmpty);
    for (final key in r.keys) {
      final broken = {...r}..remove(key);
      if (key != 'device') {
        expect(() => recommendationResult(broken), throwsFormatException);
      }
    }
    final base = {
      'version': 2,
      'store': 'nagamachiminami',
      'symbols': ['😍'],
      'weeks': [],
    };
    final payload = {
      ...emptyHistoryEdits(),
      'recommendation_results': [r],
    };
    expect(
      mergeHistoryEdits(
        payload,
        emptyHistoryEdits(),
        base,
      ).edits['recommendation_results'],
      [r],
    );
  });
  for (final width in [320.0, 393.0, 1280.0]) {
    testWidgets('構成はPC限定・台別顔文字の保存：${width.toInt()}px', (tester) async {
      tester.view.physicalSize = Size(width, 1000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final rows = [
        for (final name in ['機種A', '機種B', '機種C', '機種D', '候補7台'])
          for (var i = 0; i < 7; i++)
            row(
              name,
              i + 100,
              net: i == 0
                  ? 0
                  : i == 1
                  ? null
                  : 3000,
            ),
        for (var i = 0; i < 6; i++) row('候補6台', i + 200),
      ];
      Map<String, dynamic>? saved;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: RecommendationsView(
                records: rows,
                plans: [selected],
                results: const [],
                onResult: (p) async {
                  saved = p;
                },
                onOpen: (_) {},
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const ValueKey('recommendation-card:0')),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('recommendation-card:3')),
        findsOneWidget,
      );
      expect(find.text('100番'), findsNWidgets(4));
      expect(tester.takeException(), isNull);
      expect(find.text('4機種を保存'), findsNothing);
      expect(find.text('4大オススメの週を追加'), findsNothing);
      final first = find.byKey(const ValueKey('recommendation-face:0:100:0'));
      await tester.ensureVisible(first);
      await tester.tap(first);
      await tester.pumpAndSettle();
      await tester.tap(find.text('😇').last);
      await tester.pumpAndSettle();
      expect(saved!['value'], '😇');
      expect(saved!['rack'], 100);
      expect(saved!['day'], '2026-10-26');
      expect(saved!['machine'], '機種A');
      expect(tester.takeException(), isNull);
    });
  }
}
