import 'dart:convert';
import 'dart:io';

import 'package:database_android/event_history.dart';
import 'package:database_android/event_history_model.dart';
import 'package:database_android/models.dart';
import 'package:database_android/viewer_data.dart';
import 'package:database_android/viewer_pages.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  SlotRecord rack(String day, String machine, int rack, int? net) => SlotRecord(
    store: saiwaichouHistoryStore,
    day: day,
    machine: machine,
    rack: rack,
    games: 1000,
    bb: 4,
    rb: 2,
    extra: {'jo_net': ?net},
  );
  test('幸町の自動の優・良：全台の差枚と週表の台数がそろう日だけ。手入力が優先', () {
    final week = <String, dynamic>{
      'type': 'バラエティ',
      'from': '2026-10-19',
      'to': '2026-10-25',
      'machines': [
        {
          'name': '機種A',
          'record_name': '機種A',
          'count': 1,
          'results': ['良', '', '', '', '', '', ''],
        },
        {
          'name': '機種B',
          'record_name': '機種B',
          'count': 2,
          'results': List.filled(7, ''),
        },
      ],
    };
    final racks = historyRacksByDay([
      rack('2026-10-19', '機種A', 1, 5000),
      rack('2026-10-19', '機種B', 2, 2000),
      rack('2026-10-19', '機種B', 3, 500),
      rack('2026-10-20', '機種B', 2, 3000),
      rack('2026-10-21', '機種B', 2, 0),
      rack('2026-10-21', '機種B', 3, -1),
      rack('2026-10-22', '機種B', 2, 0),
      rack('2026-10-22', '機種B', 3, 0),
      rack('2026-10-23', '機種B', 2, 9000),
      rack('2026-10-23', '機種B', 3, null),
      rack('2026-10-24', '機種A', 1, 2499),
      SlotRecord(
        store: saiwaichouHistoryStore,
        day: '2026-10-25',
        machine: '機種A',
        rack: 1,
        games: 88888888,
        bb: 4,
        rb: 2,
        extra: {'jo_net': 9000},
      ),
      SlotRecord(
        store: historyStore,
        day: '2026-10-20',
        machine: '機種A',
        rack: 1,
        games: 1000,
        bb: 4,
        rb: 2,
        extra: {'jo_net': 9000},
      ),
    ]);
    final shown = saiwaichouAutoWeeks([week], racks).single['machines'] as List;
    expect(shown[0]['results'], ['良', '', '', '', '', '良', '']);
    expect(shown[1]['results'], ['優', '', '', '良', '', '', '']);
    expect(
      (week['machines'] as List)[1]['results'],
      List.filled(7, ''),
      reason: '元の週表は変えない',
    );
    for (final (total, grade) in [
      (-1, ''),
      (0, '良'),
      (2499, '良'),
      (2500, '優'),
      (null, ''),
    ]) {
      expect(saiwaichouNetGrade(total), grade);
    }
  });
  test('幸町の赤字：今日を除いた直前5日に+800枚を超えた日も優も無い。週またぎ・境界・台数を区別する', () {
    final machine = {'name': '機種A', 'record_name': '保存名A', 'count': 1};
    final previous = List.filled(7, ''), current = List.filled(7, '');
    final weeks = <Map<String, dynamic>>[
      {
        'type': 'バラエティ',
        'from': '2026-10-12',
        'to': '2026-10-18',
        'machines': [
          {...machine, 'results': previous},
        ],
      },
      {
        'type': 'バラエティ',
        'from': '2026-10-19',
        'to': '2026-10-25',
        'machines': [
          {...machine, 'results': current},
        ],
      },
    ];
    bool gap(List<SlotRecord> records, [String? end = '2026-10-20']) =>
        saiwaichouGradeGap(weeks, machine, end, historyRacksByDay(records));
    expect(gap([]), isTrue, reason: '記録なし・差枚不明は超えていないと数える');
    expect(
      gap([rack('2026-10-16', '保存名A', 1, 801)]),
      isFalse,
      reason: '前週の5日目',
    );
    expect(
      gap([rack('2026-10-20', '保存名A', 1, 800)]),
      isTrue,
      reason: '+800枚ちょうどは超えていない',
    );
    expect(
      gap([rack('2026-10-15', '保存名A', 1, 9000)]),
      isTrue,
      reason: '6日前は対象外',
    );
    expect(
      gap([rack('2026-10-21', '保存名A', 1, 9000)]),
      isTrue,
      reason: '最終日より後は対象外',
    );
    expect(
      gap([
        rack('2026-10-20', '保存名A', 1, 9000),
        rack('2026-10-20', '保存名A', 2, 0),
      ]),
      isTrue,
      reason: '台数が週表と違う合計は使わない',
    );
    previous[4] = '良';
    expect(gap([]), isTrue, reason: '良は超えた日と数えない');
    previous[4] = '優';
    expect(gap([]), isFalse, reason: '手入力の優は超えた日と数える');
    (weeks[0]['machines'] as List)[0]['name'] = '旧表示名';
    expect(gap([]), isFalse, reason: '明示した保存名で前週と対応');
    previous[4] = '';
    previous[3] = '優';
    expect(gap([]), isTrue, reason: '5日前の優は対象外');
    expect(gap([], null), isFalse, reason: '記録のない週は赤くしない');
    final now = DateTime.utc(2026, 10, 28, 16); // 日本時間10/29 1:00
    expect(
      saiwaichouGapEnd('2026-10-29', now),
      '2026-10-28',
      reason: '今日（日本時間）は含めない',
    );
    expect(saiwaichouGapEnd('2026-10-25', now), '2026-10-25');
    expect(saiwaichouGapEnd(null, now), isNull);
  });
  for (final width in [320.0, 393.0, 1280.0]) {
    for (final location in [historyStore, saiwaichouHistoryStore]) {
      testWidgets('ブラウザ履歴：$location・${width.toInt()}pxで1週表示・前後移動・読み取り専用', (
        tester,
      ) async {
        tester.view.physicalSize = Size(width, 900);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        const machine = 'L スマスロ 長い機種名の折り返しを確認するテスト機種';
        final saiwaichou = location == saiwaichouHistoryStore;
        final doc = jsonDecode(
          File('test/fixtures/saiwaichou_history_cases.json')
              .readAsStringSync(),
        ) as Map;
        var saves = 0;
        final edits = saiwaichou
            ? Map<String, dynamic>.from(doc)
            : emptyHistoryEdits();
        if (saiwaichou) {
          final variety = edits[saiwaichouHistoryKey];
          variety['weeks'].add({
            ...Map<String, dynamic>.from(variety['weeks'][0]),
            'week': '2026-10-12',
            'lineup_day': '2026-10-12',
          });
        }
        Map<String, dynamic> week(String from, String to, String result) => {
          'type': 'バラエティ',
          'from': from,
          'to': to,
          'machines': [
            {
              'name': machine,
              'record_name': machine,
              'count': 1,
              'results': [result, '', '', '', '', '', ''],
            },
          ],
        };
        final base = <String, dynamic>{
          'version': 2,
          'store': historyStore,
          'symbols': ['😀', '😍'],
          'weeks': [
            week('2026-10-12', '2026-10-18', '😀'),
            week('2026-10-19', '2026-10-25', '😍'),
          ],
        };
        final name = saiwaichou ? '同名機種' : machine;
        await tester.pumpWidget(
          MaterialApp(
            home: EventHistoryPage(
              store: location,
              browserLayout: true,
              edits: edits,
              data: ViewerData(
                records: [
                  SlotRecord(
                    store: location,
                    day: '2026-10-19',
                    machine: name,
                    rack: 1,
                    games: 1000,
                    bb: 4,
                    rb: 2,
                  ),
                ],
              ),
              loadBase: () async => base,
              onSave: (incoming) async {
                saves++;
                return incoming;
              },
            ),
          ),
        );
        await tester.pumpAndSettle();
        if (!saiwaichou) {
          final kind = tester.widget<DropdownButtonFormField<String>>(
            find.byWidgetPredicate(
              (w) =>
                  w is DropdownButtonFormField<String> &&
                  w.decoration.labelText == 'イベント種別',
            ),
          );
          kind.onChanged!('バラエティ');
          await tester.pumpAndSettle();
        }
        DropdownButtonFormField<String> selectedWeek() =>
            tester.widget<DropdownButtonFormField<String>>(
              find.byWidgetPredicate(
                (w) =>
                    w is DropdownButtonFormField<String> &&
                    w.decoration.labelText == '対象週',
              ),
            );
        expect(selectedWeek().initialValue, '2026-10-19');
        expect(
          find.byKey(ValueKey('history-card:2026-10-12:$name')),
          findsNothing,
        );
        expect(
          find.byKey(ValueKey('history-card:2026-10-19:$name')),
          findsOneWidget,
        );
        await tester.tap(find.text('前の週'));
        await tester.pumpAndSettle();
        expect(selectedWeek().initialValue, '2026-10-12');
        await tester.tap(find.text('次の週'));
        await tester.pumpAndSettle();
        expect(selectedWeek().initialValue, '2026-10-19');
        await tester.tap(find.text('前の週'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('最新の週'));
        await tester.pumpAndSettle();
        expect(selectedWeek().initialValue, '2026-10-19');
        final dayKey = ValueKey('history-day:2026-10-19:$name:0');
        await tester.ensureVisible(find.byKey(dayKey));
        final rect = tester.getRect(find.byKey(dayKey));
        expect(rect.left, greaterThanOrEqualTo(0));
        expect(rect.right, lessThanOrEqualTo(width));
        await tester.tap(find.byKey(dayKey));
        await tester.pumpAndSettle();
        expect(
          tester
              .widget<ViewerMachinePage>(find.byType(ViewerMachinePage))
              .store,
          location,
        );
        await tester.pageBack();
        await tester.pumpAndSettle();
        expect(selectedWeek().initialValue, '2026-10-19');
        expect(saves, 0);
        expect(tester.takeException(), isNull);
      });
    }
  }
}
