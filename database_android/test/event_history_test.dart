import 'dart:convert';
import 'dart:io';

import 'package:database_android/app_controller.dart';
import 'package:database_android/database_service.dart';
import 'package:database_android/event_history.dart';
import 'package:database_android/event_history_model.dart';
import 'package:database_android/models.dart';
import 'package:database_android/list_views.dart' show displayMachineName;
import 'package:database_android/viewer_data.dart';
import 'package:database_android/viewer_pages.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/real_database.dart';

Map<String, dynamic> edit(
  Map base, {
  String value = '',
  String at = '2026-10-19T00:00:00Z',
  String device = 'android',
}) {
  final w = base['weeks'][0];
  return {
    'store': historyStore,
    'type': w['type'],
    'week': w['from'],
    'machine': w['machines'][0]['name'],
    'day': w['from'],
    'value': value,
    'updated_at': at,
    'device': device,
  };
}

SlotRecord record(String day, String machine, int rack) => SlotRecord(
  store: historyStore,
  day: day,
  machine: machine,
  rack: rack,
  games: 1000,
  bb: 4,
  rb: 2,
);

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test('固定した週の構成を取り込みで上書きしない', () async {
    final base = await loadHistoryBase();
    final old = emptyHistoryEdits(), incoming = emptyHistoryEdits();
    final week = {
      'store': historyStore,
      'type': 'バラエティ',
      'week': '2026-10-12',
      'lineup_day': '2026-10-12',
      'machines': [
        {'name': '機種A', 'record_name': '機種A', 'count': 2},
      ],
      'removed': false,
      'updated_at': '2026-10-19T00:00:00Z',
    };
    old['weeks'] = [week];
    incoming['weeks'] = [
      {
        ...week,
        'lineup_day': '2026-10-13',
        'updated_at': '2026-10-19T00:00:01Z',
      },
    ];
    final result = mergeHistoryEdits(old, incoming, base);
    expect(result.weekConflicts, 1);
    expect(result.edits['weeks'][0]['lineup_day'], '2026-10-12');
  });
  test('週・記号の検証、空欄と不一致を保持', () async {
    final base = await loadHistoryBase();
    final old = emptyHistoryEdits(), fresh = emptyHistoryEdits();
    old['cells'] = [edit(base, value: '😀', device: 'pc')];
    fresh['cells'] = [edit(base, at: '2026-10-19T00:00:01Z')];
    final merged = mergeHistoryEdits(old, fresh, base);
    expect(merged.conflicts, 1);
    expect(merged.edits['cells'][0]['value'], '');
    fresh['cells'] = [edit(base, value: '任意文字列')];
    expect(mergeHistoryEdits(old, fresh, base).rejected, 1);
    final again = mergeHistoryEdits(merged.edits, old, base);
    expect(again.conflicts, 0);
    final broken = jsonDecode(jsonEncode(base)) as Map;
    (broken['weeks'] as List).add(broken['weeks'][0]);
    expect(() => parseHistoryBase(broken), throwsFormatException);
  });
  test('最初に十分そろった日の構成を固定し、機種名は推測で結ばない', () async {
    final records = [
      for (final e in {
        '2026-10-11': 10,
        '2026-10-12': 3,
        '2026-10-13': 10,
        '2026-10-16': 10,
      }.entries)
        for (var i = 0; i < e.value; i++)
          record(e.key, i < 2 ? '機種A' : '機種B', i + 1),
    ];
    final week = newHistoryVarietyWeek(records, '2026-10-12');
    expect(week['lineup_day'], '2026-10-13');
    expect((week['machines'] as List).length, 1);
    expect(
      historySavedName({'name': 'Lカバネリ', 'record_name': null}, {'L ｶﾊﾞﾈﾘ'}),
      isNull,
    );
    expect(
      historySavedName(
        {'name': 'Lカバネリ', 'record_name': 'L ｶﾊﾞﾈﾘ'},
        {'L ｶﾊﾞﾈﾘ'},
      ),
      'L ｶﾊﾞﾈﾘ',
    );
  });
  test('端末DBからバックアップを経由して編集を往復する', () async {
    final path = await newDatabasePath();
    final db = realDatabase(path);
    final controller = AppController(database: db);
    try {
      await controller.initialize();
      final base = await loadHistoryBase();
      final changes = emptyHistoryEdits();
      changes['cells'] = [edit(base, value: '😍')];
      await controller.saveHistoryEdits(changes);
      final file = File('$path.export.json');
      await db.exportBackup(file);
      final payload = jsonDecode(await file.readAsString());
      expect(payload['event_history_edits']['cells'][0]['value'], '😍');
      final result = await controller.importBackup(file);
      expect(result.historyConflicts, 0);
      expect(controller.historyEdits['cells'][0]['value'], '😍');
    } finally {
      controller.dispose();
      await db.close();
      await Directory(path).parent.delete(recursive: true);
    }
  });
  test('共通JSONの週・記号・除外件数がPythonとJSに一致', () async {
    final doc = jsonDecode(
      await File('test/fixtures/event_history_cases.json').readAsString(),
    ) as Map<String, dynamic>;
    final base = parseHistoryBase(doc['base']),
        cleaned = cleanHistoryEdits(doc, base);
    final weeks = historyWeeks(base, doc);
    expect({
      'rejected': cleaned.rejected,
      'weeks': [
        for (final w in weeks)
          {
            'type': w['type'],
            'from': w['from'],
            'results': [for (final m in w['machines']) m['results']],
            'links': [for (final m in w['machines']) m['record_name']],
          },
      ],
    }, doc['expected']);
  });
  test('機種名修正後も原文をバックアップに残し、正常な編集を継続', () async {
    final path = await newDatabasePath();
    final db = realDatabase(path);
    final controller = AppController(database: db);
    try {
      final base = await loadHistoryBase();
      final raw = emptyHistoryEdits();
      raw['cells'] = [
        {...edit(base), 'machine': '旧基準の機種名'},
      ];
      await db.applyChanges(
        ChangeSet(state: {'event_history_edits': jsonEncode(raw)}),
      );
      await controller.initialize();
      final file = File('$path.raw.json');
      await db.exportBackup(file);
      expect(jsonDecode(await file.readAsString())['event_history_edits'], raw);
      final valid = emptyHistoryEdits();
      valid['cells'] = [edit(base, value: '😍')];
      final result = await controller.saveHistoryEdits(valid);
      expect(cleanHistoryEdits(result, base).rejected, 1);
      expect(result['cells'].length, 2);
      await db.exportBackup(file);
      expect(
        jsonDecode(await file.readAsString())['event_history_edits'],
        result,
      );
    } finally {
      controller.dispose();
      await db.close();
      await Directory(path).parent.delete(recursive: true);
    }
  });
  test('週構成が異なっても台データを取り込み、既存週を維持', () async {
    final path = await newDatabasePath();
    final db = realDatabase(path);
    final controller = AppController(database: db);
    try {
      await controller.initialize();
      final week = {
        'store': historyStore,
        'type': 'バラエティ',
        'week': '2026-10-12',
        'lineup_day': '2026-10-12',
        'machines': [
          {'name': 'A', 'count': 2, 'record_name': 'A'},
        ],
        'updated_at': '2026-10-19T00:00:00Z',
        'removed': false,
      };
      final old = emptyHistoryEdits();
      old['weeks'] = [week];
      await controller.saveHistoryEdits(old);
      final incoming = emptyHistoryEdits();
      incoming['weeks'] = [
        {
          ...week,
          'machines': [
            {'name': 'B', 'count': 1},
          ],
        },
      ];
      incoming['cells'] = [
        {
          'store': historyStore,
          'type': 'バラエティ',
          'week': week['week'],
          'day': week['week'],
          'machine': 'B',
          'value': '😀',
          'updated_at': week['updated_at'],
        },
      ];
      final file = File('$path.conflict.json');
      await file.writeAsString(
        jsonEncode({
          'format': 'database-backup',
          'version': 1,
          'records': [record('2026-10-18', '通常', 1).toJson()],
          'event_history_edits': incoming,
        }),
      );
      final result = await controller.importBackup(file);
      expect(result.historyWeekConflicts, 1);
      expect(result.historyRejected, 1);
      expect(result.added, 1);
      expect(controller.historyEdits['weeks'][0]['machines'][0]['name'], 'A');
    } finally {
      controller.dispose();
      await db.close();
      await Directory(path).parent.delete(recursive: true);
    }
  });
  testWidgets('Androidの保存期間外と除外件数を表示', (tester) async {
    final base = (await tester.runAsync(loadHistoryBase))!;
    final raw = emptyHistoryEdits();
    raw['cells'] = [null];
    await tester.pumpWidget(
      MaterialApp(
        home: EventHistoryPage(
          data: const ViewerData(records: []),
          edits: raw,
          recordCutoff: '2026-10-06',
          loadBase: () => Future.value(base),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.textContaining('基準に合わない履歴1件'), findsOneWidget);
    expect(find.text('端末に記録がありません（60日より前）'), findsWidgets);
    expect(tester.takeException(), isNull);
  });
  testWidgets('空欄でも同日の保存名で開き、ViewerDataを維持する', (tester) async {
    final base = (await tester.runAsync(loadHistoryBase))!;
    final w = (base['weeks'] as List).last;
    final machine = w['machines'][0]['name'] as String;
    final edits = emptyHistoryEdits();
    edits['cells'] = [
      {
        'store': historyStore,
        'type': w['type'],
        'week': w['from'],
        'machine': machine,
        'day': w['from'],
        'value': '',
        'updated_at': '2026-10-19T00:00:00Z',
        'device': 'pc',
      },
    ];
    final data = ViewerData(
      records: [record(w['from'] as String, machine, 11)],
    );
    await tester.pumpWidget(
      MaterialApp(
        home: EventHistoryPage(
          data: data,
          edits: edits,
          loadBase: () => Future.value(base),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    await tester.tap(find.text('開く →').first);
    await tester.pumpAndSettle();
    final page = tester.widget<ViewerMachinePage>(
      find.byType(ViewerMachinePage),
    );
    expect(page.day, w['from']);
    expect(page.machine, machine);
    expect(identical(page.data, data), isTrue);
  });
  testWidgets('編集画面は記号選択を保存し、機種名列は横スクロールの外にある', (tester) async {
    tester.view.physicalSize = const Size(320, 860);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final base = (await tester.runAsync(loadHistoryBase))!;
    Map<String, dynamic>? received;
    await tester.pumpWidget(
      MaterialApp(
        home: EventHistoryPage(
          data: const ViewerData(records: []),
          loadBase: () => Future.value(base),
          onSave: (incoming) async {
            received = incoming;
            return mergeHistoryEdits(emptyHistoryEdits(), incoming, base).edits;
          },
        ),
      ),
    );
    await tester.pumpAndSettle();
    final fixedName = find.text(displayMachineNameForTest(base)).first;
    final before = tester.getTopLeft(fixedName).dx;
    final horizontal = find
        .byWidgetPredicate(
          (w) =>
              w is SingleChildScrollView &&
              w.scrollDirection == Axis.horizontal,
        )
        .first;
    await tester.dragFrom(
      tester.getTopLeft(horizontal) + const Offset(70, 20),
      const Offset(-120, 0),
    );
    await tester.pumpAndSettle();
    expect(
      tester
          .state<ScrollableState>(
            find
                .descendant(of: horizontal, matching: find.byType(Scrollable))
                .first,
          )
          .position
          .pixels,
      greaterThan(0),
    );
    expect(tester.getTopLeft(fixedName).dx, before);
    await tester.dragFrom(
      tester.getTopLeft(horizontal) + const Offset(70, 20),
      const Offset(500, 0),
    );
    await tester.pumpAndSettle();
    final dropdown = find
        .byWidgetPredicate(
          (w) =>
              w is DropdownButton<String> &&
              w.key is ValueKey &&
              (w.key as ValueKey).value.toString().startsWith('symbol:'),
        )
        .first;
    await tester.tap(dropdown);
    await tester.pumpAndSettle();
    await tester.tap(find.text('空欄').last);
    await tester.pumpAndSettle();
    expect(received?['cells'][0]['value'], '');
    expect(find.text('バラエティの週表を作成'), findsNothing);
    expect(tester.takeException(), isNull);
  });
}

String displayMachineNameForTest(Map base) => displayMachineName(
  (base['weeks'] as List).last['machines'][0]['name'] as String,
);
