import 'package:database_android/machine_sections.dart';
import 'package:database_android/models.dart';
import 'package:database_android/shared_widgets.dart';
import 'package:database_android/theme.dart';
import 'package:database_android/viewer_data.dart';
import 'package:database_android/viewer_main.dart';
import 'package:database_android/viewer_pages.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

SlotRecord rec(String store, String day, String machine, int rack) =>
    SlotRecord(
      store: store,
      day: day,
      machine: machine,
      rack: rack,
      games: 600,
      bb: 3,
      rb: 1,
      maxHold: 192,
      extra: store.startsWith('pscube:')
          ? {'source': 'pscube', 'my': 192, 'at_art': 0}
          : {},
    );

Future<void> open(
  WidgetTester tester,
  Widget page, {
  double height = 852,
}) async {
  await tester.binding.setSurfaceSize(Size(393, height));
  addTearDown(() => tester.binding.setSurfaceSize(null));
  await tester.pumpWidget(MaterialApp(theme: buildAppTheme(), home: page));
  await tester.pumpAndSettle();
}

void main() {
  for (final store in ['nagamachiminami', 'pscube:c740601:20']) {
    testWidgets('$store：同番号の旧機種は勝手に表示せず、利用者が選んで開く', (tester) async {
      final current = rec(store, '2026-10-05', '化物語', 1085);
      final old = rec(store, '2026-10-04', '北斗', 1085);
      final data = ViewerData(
        records: [current, old, rec('saiwaichou', '2026-10-04', '別店舗', 1085)],
      );
      await open(tester, ViewerRecordPage(data: data, record: current));
      await tester.tap(find.byTooltip('前の記録日'));
      await tester.pumpAndSettle();
      expect(find.text('この日の記録はありません'), findsOneWidget);
      expect(find.byType(SavedGraphPage), findsNothing);
      expect(find.text('この日の「北斗」を見る'), findsOneWidget);
      expect(find.textContaining('別店舗'), findsNothing);
      await tester.tap(find.text('この日の「北斗」を見る'));
      await tester.pumpAndSettle();
      final shown = tester.widget<SavedGraphPage>(find.byType(SavedGraphPage));
      expect(shown.record.machine, '北斗');
      expect(shown.record.day, '2026-10-04');
      expect(shown.record.store, store);
      expect(tester.takeException(), isNull);
    });

    testWidgets('$store：同じ機種の番号変更後は、その日の台一覧を開ける', (tester) async {
      final old = rec(store, '2026-10-04', '対象機種', 1085);
      final moved = rec(store, '2026-10-05', '対象機種', 1100);
      final data = ViewerData(records: [old, moved]);
      await open(tester, ViewerRecordPage(data: data, record: old));
      await tester.tap(find.byTooltip('次の記録日'));
      await tester.pumpAndSettle();
      expect(find.byType(SavedGraphPage), findsNothing);
      expect(find.text('この日は「対象機種」に、別の台番号の記録があります。'), findsOneWidget);
      await tester.tap(find.text('この日の機種一覧を見る'));
      await tester.pumpAndSettle();
      final table = tester.widget<MachineDataTable>(
        find.byType(MachineDataTable),
      );
      expect(table.entries.single.$1.rack, 1100);
      expect(table.entries.single.$1.day, '2026-10-05');
      expect(tester.takeException(), isNull);
    });

    testWidgets('$store：新台の記録より前の日から、保存済みの最新日へ戻れる', (tester) async {
      final current = rec(store, '2026-10-05', '新機種', 1085);
      final data = ViewerData(
        records: [current, rec(store, '2026-10-03', '別の機種', 1200)],
      );
      final changed = <String>[];
      await open(
        tester,
        ViewerRecordPage(
          data: data,
          record: current,
          onDayChanged: changed.add,
        ),
      );
      await tester.tap(find.byTooltip('前の記録日'));
      await tester.pumpAndSettle();
      expect(find.text('この日の記録はありません'), findsOneWidget);
      expect(find.text('この日の機種一覧を見る'), findsNothing);
      await tester.tap(find.text('この台の最新の記録へ戻る'));
      await tester.pumpAndSettle();
      expect(
        tester.widget<SavedGraphPage>(find.byType(SavedGraphPage)).record.day,
        '2026-10-05',
      );
      expect(changed, ['2026-10-03', '2026-10-05']);
      expect(data.records, hasLength(2));
      expect(tester.takeException(), isNull);
    });

    testWidgets('$store：旧番号の検索が外れた日には、検索を解除して新番号を確認できる', (tester) async {
      final data = ViewerData(
        records: [
          for (var rack = 20; rack < 24; rack++)
            rec(store, '2026-10-04', '対象機種', rack),
          for (var rack = 30; rack < 34; rack++)
            rec(store, '2026-10-05', '対象機種', rack),
        ],
      );
      await open(
        tester,
        ViewerMachinePage(
          data: data,
          store: store,
          machine: '対象機種',
          day: '2026-10-04',
          query: '20',
        ),
      );
      expect(
        tester
            .widget<MachineDataTable>(find.byType(MachineDataTable))
            .entries
            .single
            .$1
            .rack,
        20,
      );
      await tester.tap(find.byTooltip('次の記録日'));
      await tester.pumpAndSettle();
      expect(find.text('検索条件に合う台がありません'), findsOneWidget);
      expect(find.text('この日の記録はありません'), findsNothing);
      await tester.tap(find.text('この機種の全台を表示'));
      await tester.pumpAndSettle();
      final table = tester.widget<MachineDataTable>(
        find.byType(MachineDataTable),
      );
      expect(table.entries.map((e) => e.$1.rack), [30, 31, 32, 33]);
      expect(tester.takeException(), isNull);
    });

    testWidgets('$store：一覧は選択日の取り込み済み機種と台だけを数える', (tester) async {
      final data = ViewerData(
        records: [
          for (var rack = 1; rack <= 4; rack++)
            rec(store, '2026-10-05', '新機種', rack),
          for (var rack = 1; rack <= 8; rack++)
            rec(store, '2026-10-04', '旧機種', rack),
        ],
      );
      await open(tester, ViewerHome(initialData: data), height: 3000);
      expect(find.text('この日の機種一覧　1機種・4台'), findsOneWidget);
      expect(
        find.text('選んだ日の取り込み済みデータです。入れ替え前の機種・台番号は、日付を戻して確認できます。'),
        findsOneWidget,
      );
      await tester.tap(find.byTooltip('前の記録日'));
      await tester.pumpAndSettle();
      expect(find.text('この日の機種一覧　1機種・8台'), findsOneWidget);
      expect(data.records, hasLength(12));
      expect(tester.takeException(), isNull);
    });
  }
}
