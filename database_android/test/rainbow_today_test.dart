import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:database_android/rainbow_today.dart';
import 'package:database_android/models.dart';
import 'package:database_android/rainbow_marks.dart';
import 'package:database_android/theme.dart';
import 'package:database_android/viewer_data.dart';
import 'package:database_android/viewer_pages.dart';
import 'package:database_android/variety_week.dart';

String fixture() => File('test/fixtures/variety_week.json').readAsStringSync();

void main() {
  test('本日は日本時間の日付。月年境界とUTCの日付に依存しない', () {
    expect(
      rainbowTodayDay(DateTime.parse('2026-12-31T15:00:00Z')),
      '2027-01-01',
    );
    expect(
      rainbowTodayDay(DateTime.parse('2026-12-31T14:59:59Z')),
      '2026-12-31',
    );
  });

  test('未取り込みでも最新のそろった1台機種一覧。数値の行を増やさず過去の印をコピーしない', () {
    final data = ViewerData.parse(fixture());
    final report = rainbowTodayRows(data, 'saiwaichou', '2026-10-14');
    expect(report.lineupDay, '2026-10-13');
    expect(report.rows.map((x) => x.marker.rack), [
      1101,
      1102,
      1103,
      1104,
      1105,
      1106,
    ]);
    expect(report.rows.every((x) => !x.imported && !x.marker.rainbow), isTrue);
    expect(data.records.where((r) => r.day == '2026-10-14'), isEmpty);
    final partial = ViewerData(
      records: [
        ...data.records,
        data.records.first.copyWith(day: '2026-10-14', machine: '一部取得'),
        data.records.first.copyWith(day: '2026-10-15', machine: '未来'),
      ],
    );
    expect(
      rainbowTodayRows(partial, 'saiwaichou', '2026-10-14').lineupDay,
      '2026-10-13',
    );
    expect(
      rainbowTodayRows(data, 'nagamachiminami', '2026-10-14').rows,
      isEmpty,
    );
  });

  test('未取得の印を保存・開き直し・Drive更新・取り込み後へ引き継ぎ、後から外した印が勝つ', () {
    var text = fixture();
    final original = ViewerData.parse(text);
    final marker = rainbowTodayRows(
      original,
      'saiwaichou',
      '2026-10-14',
    ).rows.first.marker;
    text = setRainbowMark(
      text,
      marker,
      true,
      DateTime.parse('2026-10-14T04:00:00Z'),
    );
    final saved = ViewerData.parse(text);
    expect(saved.records.length, original.records.length);
    expect(
      rainbowTodayRows(
        saved,
        'saiwaichou',
        '2026-10-14',
      ).rows.first.marker.rainbow,
      isTrue,
    );
    final imported = jsonDecode(fixture()) as Map<String, dynamic>;
    (imported['records'] as List).add(
      original.records
          .firstWhere((r) => r.rack == marker.rack)
          .copyWith(day: '2026-10-14', extra: const {}, games: 4567)
          .toJson(),
    );
    final updated = ViewerData.parse(
      keepRainbowMarks(text, jsonEncode(imported)),
    );
    final row = rainbowTodayRows(
      updated,
      'saiwaichou',
      '2026-10-14',
    ).rows.first;
    expect(row.imported, isTrue);
    expect(row.marker.rainbow, isTrue);
    expect(row.marker.games, 4567);
    text = setRainbowMark(
      text,
      marker,
      false,
      DateTime.parse('2026-10-14T05:00:00Z'),
    );
    final shared = withSharedRainbow(
      fixture(),
      jsonEncode({
        'format': 'database-rainbow',
        'marks': jsonDecode(sharedRainbowBody(text))['marks'],
      }),
    )!;
    expect(
      rainbowTodayRows(
        ViewerData.parse(shared),
        'saiwaichou',
        '2026-10-14',
      ).rows.first.marker.rainbow,
      isFalse,
    );
  });

  testWidgets('320/393pxで本日を切り替え、未取得のまま付け外し、7日間の候補へ戻れる', (tester) async {
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(() => viewerRainbowEditor = null);
    for (final width in [320.0, 393.0]) {
      tester.view.physicalSize = Size(width, 852);
      final decoded = jsonDecode(fixture()) as Map<String, dynamic>;
      (decoded['records'] as List).removeWhere(
        (r) =>
            (r['day'] as String).compareTo(rainbowTodayDay(DateTime.now())) >=
            0,
      );
      var text = jsonEncode(decoded);
      var data = ViewerData.parse(text);
      viewerRainbowEditor = (record, on) async {
        text = setRainbowMark(text, record, on, DateTime.now());
        return data = ViewerData.parse(text);
      };
      await tester.pumpWidget(
        MaterialApp(
          theme: buildAppTheme(),
          home: VarietyWeekPage(
            data: data,
            store: 'saiwaichou',
            day: '2026-10-13',
            currentData: () => data,
          ),
        ),
      );
      await tester.tap(find.text('本日'));
      await tester.pumpAndSettle();
      expect(
        find.text('本日 ${rainbowTodayDay(DateTime.now())}'),
        findsOneWidget,
      );
      final button = find.byKey(const ValueKey('today-rainbow-1101'));
      await tester.ensureVisible(button);
      await tester.tap(button);
      await tester.pumpAndSettle();
      expect(find.text('本日の🌈 1台'), findsOneWidget);
      expect(
        data.records.where((r) => r.day == rainbowTodayDay(DateTime.now())),
        isEmpty,
      );
      await tester.tap(button);
      await tester.pumpAndSettle();
      expect(find.text('本日の🌈 0台'), findsOneWidget);
      viewerRainbowEditor = (_, _) async => throw StateError('保存失敗');
      await tester.tap(button);
      await tester.pumpAndSettle();
      expect(find.text('🌈を保存できませんでした。もう一度押してください。'), findsOneWidget);
      expect(find.text('本日の🌈 0台'), findsOneWidget);
      await tester.tap(find.text('7日間の候補'));
      await tester.pumpAndSettle();
      expect(find.text('2026-10-07〜2026-10-13'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    }
  });

  testWidgets('開いたあとに届いたほかの端末の🌈も、本日の一覧に出る', (tester) async {
    // 2026-10-25：起動直後に開くと、あとから取り込んだ共有の🌈が出ないまま（CIの閲覧ページ試験がたまに失敗）。
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(320, 852);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);
    final decoded = jsonDecode(fixture()) as Map<String, dynamic>;
    final today = rainbowTodayDay(DateTime.now());
    (decoded['records'] as List).removeWhere(
      (r) => (r['day'] as String).compareTo(today) >= 0,
    );
    final text = jsonEncode(decoded);
    var data = ViewerData.parse(text);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: VarietyWeekPage(
          data: data,
          store: 'saiwaichou',
          day: '2026-10-13',
          currentData: () => data,
        ),
      ),
    );
    await tester.tap(find.text('本日'));
    await tester.pumpAndSettle();
    expect(find.text('本日の🌈 0台'), findsOneWidget);
    final marker = rainbowTodayRows(
      data,
      'saiwaichou',
      today,
    ).rows.first.marker;
    final shared = withSharedRainbow(
      text,
      jsonEncode({
        'format': 'database-rainbow',
        'marks': [
          {
            'store': 'saiwaichou',
            'day': today,
            'rack': marker.rack,
            'on': true,
            'updated_at': DateTime.now().toUtc().toIso8601String(),
          },
        ],
      }),
    )!;
    data = ViewerData.parse(shared);
    viewerDataRevision.value++;
    await tester.pumpAndSettle();
    expect(find.text('本日の🌈 1台'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });
}
