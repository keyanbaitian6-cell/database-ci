import 'dart:convert';
import 'dart:io';

import 'package:database_android/app_controller.dart';
import 'package:database_android/event_history.dart';
import 'package:database_android/event_history_model.dart';
import 'package:database_android/models.dart';
import 'package:database_android/viewer_data.dart';
import 'package:database_android/viewer_pages.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/real_database.dart';

Future<Map<String, dynamic>> fixture() async => Map<String, dynamic>.from(
  jsonDecode(
    await File('test/fixtures/saiwaichou_history_cases.json').readAsString(),
  ) as Map,
);

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('Python・JSと同じ幸町の週・記号・店舗分離・除外件数', () async {
    final doc = await fixture();
    final variety = historyDocumentForStore(doc, saiwaichouHistoryStore);
    final base = parseHistoryBase(variety['base']);
    expect(
      cleanHistoryEdits(variety, base).rejected,
      doc['expected']['rejected'],
    );
    expect(
      historyWeeks(
        base,
        variety,
      ).single['machines'].map((m) => m['results']).toList(),
      doc['expected']['results'],
    );
    expect(
      historyWeeks(
        parseHistoryBase(doc['base']),
        doc,
      ).single['machines'][0]['results'][0],
      '😍',
    );
    expect(
      () => parseHistoryBase({
        ...base,
        'symbols': ['😍'],
      }),
      throwsFormatException,
    );
    expect(() => historyDocumentForStore(doc, '不明'), throwsFormatException);
  });

  test('幸町は長町南の編集・幸町を含まない旧バックアップでも消えない', () async {
    final doc = await fixture(),
        base = parseHistoryBase((await fixture())['base']);
    final clean = mergeHistoryEdits(emptyHistoryEdits(), doc, base).edits;
    final next = mergeHistoryEdits(clean, emptyHistoryEdits(), base).edits;
    expect(next[saiwaichouHistoryKey], clean[saiwaichouHistoryKey]);
    final raw = historyForBackup(jsonEncode(next))!;
    expect(raw[saiwaichouHistoryKey], next[saiwaichouHistoryKey]);
    expect(raw['cells'], isEmpty);
    final malformed = {
      ...emptyHistoryEdits(),
      saiwaichouHistoryKey: {
        ...emptyHistoryEdits(),
        saiwaichouHistoryKey: emptyHistoryEdits(),
      },
    };
    expect(() => validateHistoryEnvelope(malformed), throwsFormatException);
  });

  test('PCの幸町をAndroidで取り込み、通常の編集と書き出し後も保持する', () async {
    final path = await newDatabasePath();
    final db = realDatabase(path);
    final controller = AppController(database: db);
    try {
      await controller.initialize();
      final doc = await fixture();
      final file = File('$path.pc.json');
      await file.writeAsString(
        jsonEncode({
          'format': 'database-backup',
          'version': 1,
          'records': [],
          'event_history_edits': {
            ...emptyHistoryEdits(),
            saiwaichouHistoryKey: doc[saiwaichouHistoryKey],
          },
        }),
      );
      await controller.importBackup(file);
      final before = controller.historyEdits[saiwaichouHistoryKey];
      expect(before['cells'].where((c) => c['value'] == '優'), isNotEmpty);
      await controller.saveHistoryEdits(emptyHistoryEdits());
      expect(controller.historyEdits[saiwaichouHistoryKey], before);
      await expectLater(
        controller.saveHistoryEdits({
          ...emptyHistoryEdits(),
          saiwaichouHistoryKey: emptyHistoryEdits(),
        }),
        throwsFormatException,
      );
      await db.exportBackup(file);
      final exported = jsonDecode(await file.readAsString());
      expect(exported['event_history_edits'][saiwaichouHistoryKey], before);
    } finally {
      controller.dispose();
      await db.close();
      await Directory(path).parent.delete(recursive: true);
    }
  });

  testWidgets('幸町は優・良を閲覧し、PC以外の編集を出さず同店のデータを開く', (tester) async {
    final doc = (await tester.runAsync(fixture))!;
    SlotRecord row(String store, int rack) => SlotRecord(
      store: store,
      day: '2026-10-19',
      machine: '同名機種',
      rack: rack,
      games: 1000,
      bb: 4,
      rb: 2,
    );
    var saved = false;
    final data = ViewerData(
      records: [row(historyStore, 90), row(saiwaichouHistoryStore, 1)],
    );
    await tester.pumpWidget(
      MaterialApp(
        home: EventHistoryPage(
          store: saiwaichouHistoryStore,
          data: data,
          edits: doc,
          onSave: (_) async {
            saved = true;
            return doc;
          },
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('幸町のバラエティ履歴'), findsOneWidget);
    expect(find.text('優'), findsOneWidget);
    expect(find.text('良'), findsOneWidget);
    expect(
      find.byWidgetPredicate(
        (w) =>
            w is DropdownButton<String> && w.key.toString().contains('symbol:'),
      ),
      findsNothing,
    );
    expect(
      tester.widget<Text>(find.text('同名機種')).style?.color,
      isNot(const Color(0xffb91c1c)),
    );
    await tester.tap(find.text('開く →').first);
    await tester.pumpAndSettle();
    final page = tester.widget<ViewerMachinePage>(
      find.byType(ViewerMachinePage),
    );
    expect(page.store, saiwaichouHistoryStore);
    expect(page.machine, '同名機種');
    expect(saved, isFalse);
    expect(tester.takeException(), isNull);
  });
}
