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
  test('赤字は最終記録日まで5暦日。週またぎ・空欄・境界・未来を区別する', () {
    final machine = {'name': '機種A', 'record_name': '保存名A'};
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
    expect(historyGradeGap(weeks, machine, '2026-10-20'), isTrue);
    previous[4] = '良';
    expect(historyGradeGap(weeks, machine, '2026-10-20'), isFalse);
    (weeks[0]['machines'] as List)[0]['name'] = '旧表示名';
    expect(historyGradeGap(weeks, machine, '2026-10-20'), isFalse);
    previous[4] = '';
    previous[3] = '優';
    current[2] = '良';
    expect(historyGradeGap(weeks, machine, '2026-10-20'), isTrue);
    current[1] = '良';
    expect(historyGradeGap(weeks, machine, '2026-10-20'), isFalse);
    expect(historyGradeGap(weeks, {'name': '別機種'}, '2026-10-20'), isTrue);
    expect(historyGradeGap(weeks, machine, null), isFalse);
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
