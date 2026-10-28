import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:database_android/shared_widgets.dart';
import 'package:database_android/models.dart';
import 'package:database_android/theme.dart';
import 'package:database_android/viewer_data.dart';
import 'package:database_android/viewer_pages.dart';

import 'viewer_navigation_test.dart' as f;

const selectKey = ValueKey('viewer-select-rack');
const latestKey = ValueKey('viewer-latest-record');
const saveKey = ValueKey('viewer-rainbow-saving');
const toggleKey = ValueKey('rainbow-toggle');
SavedGraphPage shown(WidgetTester t) =>
    t.widget<SavedGraphPage>(find.byType(SavedGraphPage));
Future<void> tap(WidgetTester t, Finder finder) async {
  await t.tap(finder);
  await t.pumpAndSettle();
}

void main() {
  tearDown(() => viewerRainbowEditor = null);
  for (final store in ['nagamachiminami', 'pscube:c740601:20']) {
    testWidgets('$store：直接選択の範囲と、選択台の最新日を保つ', (t) async {
      await f.phone(t);
      await t.binding.setSurfaceSize(const Size(320, 852));
      final rows = [
        f.rec('2026-10-25', store: store, rack: 10),
        f.rec('2026-10-25', store: store, rack: 30),
        f.rec('2026-10-27', store: store, rack: 30),
        f.rec('2026-10-28', store: store, rack: 10),
        f.rec('2026-10-28', store: store, rack: 30, machine: '入替後'),
        f.rec('2026-10-25', store: store, rack: 99, machine: '別機種'),
        f.rec('2026-10-25', store: '別店', rack: 88),
        f.rec('2026-10-24', store: store, rack: 77),
      ];
      final changed = <String>[];
      await t.pumpWidget(
        f.app(
          ViewerRecordPage(
            data: ViewerData(records: rows),
            record: rows.first,
            onDayChanged: changed.add,
          ),
        ),
      );
      await tap(t, find.byKey(selectKey));
      final tiles = t
          .widgetList<ListTile>(
            find.descendant(
              of: find.byType(AlertDialog),
              matching: find.byType(ListTile),
            ),
          )
          .toList();
      expect(tiles.map((x) => (x.title! as Text).data), ['10番台', '30番台']);
      expect(tiles.first.selected, isTrue);
      await tap(
        t,
        find.descendant(
          of: find.byType(AlertDialog),
          matching: find.text('30番台'),
        ),
      );
      expect(shown(t).record.rack, 30);
      expect(shown(t).record.day, '2026-10-25');
      expect(changed, isEmpty);
      await tap(t, find.byKey(latestKey));
      expect(shown(t).record.rack, 30);
      expect(shown(t).record.day, '2026-10-27');
      expect(changed, ['2026-10-27']);
      expect(t.widget<TextButton>(find.byKey(latestKey)).onPressed, isNull);
      await tap(t, find.byKey(selectKey));
      await tap(t, find.text('閉じる'));
      expect(shown(t).record.rack, 30);
      expect(t.takeException(), isNull);
    });
  }
  testWidgets('欠測日から同じ台の最新記録へ戻れる', (t) async {
    await f.phone(t);
    final a = f.rec('2026-10-25');
    await t.pumpWidget(
      f.app(
        ViewerRecordPage(
          data: ViewerData(
            records: [
              a,
              f.rec('2026-10-26', machine: '別機種'),
            ],
          ),
          record: a,
        ),
      ),
    );
    await tap(t, find.byTooltip('次の記録日'));
    expect(t.widget<TextButton>(find.byKey(selectKey)).onPressed, isNull);
    await tap(t, find.byKey(latestKey));
    expect(shown(t).record.key, a.key);
    expect(t.takeException(), isNull);
  });
  testWidgets('100台の選択一覧をスクロールできる', (t) async {
    await f.phone(t);
    final rows = [for (var i = 1; i <= 100; i++) f.rec('2026-10-25', rack: i)];
    await t.pumpWidget(
      f.app(
        ViewerRecordPage(
          data: ViewerData(records: rows),
          record: rows.first,
        ),
      ),
    );
    await tap(t, find.byKey(selectKey));
    await t.scrollUntilVisible(
      find.text('100番台'),
      400,
      scrollable: find.descendant(
        of: find.byType(AlertDialog),
        matching: find.byType(Scrollable),
      ),
      maxScrolls: 30,
    );
    await tap(t, find.text('100番台'));
    expect(shown(t).record.rack, 100);
    expect(t.takeException(), isNull);
  });
  testWidgets('保存中は対象台を示し、台と日を移っても二重保存しない', (t) async {
    await f.phone(t);
    await t.binding.setSurfaceSize(const Size(320, 852));
    final a = f.rec('2026-10-25', rack: 1085),
        b = f.rec('2026-10-25', rack: 1088),
        c = f.rec('2026-10-26', rack: 1088);
    final pending = Completer<ViewerData?>();
    var calls = 0;
    viewerRainbowEditor = (record, on) {
      calls++;
      expect(record.key, a.key);
      return pending.future;
    };
    await t.pumpWidget(
      f.app(
        ViewerRecordPage(
          data: ViewerData(records: [a, b, c]),
          record: a,
        ),
      ),
    );
    await tap(t, find.byKey(toggleKey));
    expect(find.text('1085番台 🌈保存中'), findsOneWidget);
    expect(t.widget<OutlinedButton>(find.byKey(saveKey)).onPressed, isNull);
    await tap(t, find.text('次の台'));
    await tap(t, find.byKey(latestKey));
    expect(find.text('1085番台 🌈保存中'), findsOneWidget);
    expect(find.byKey(toggleKey), findsNothing);
    pending.complete(
      ViewerData(
        records: [
          a.copyWith(extra: {'rainbow': true}),
          b,
          c,
        ],
      ),
    );
    await t.pumpAndSettle();
    expect(find.byKey(saveKey), findsNothing);
    expect(shown(t).record.key, c.key);
    expect(shown(t).record.rainbow, isFalse);
    expect(calls, 1);
    expect(find.byKey(toggleKey), findsOneWidget);
    expect(t.takeException(), isNull);
  });
  // 2026-10-29：iPhoneで「○番台／🌈保存中」の2行の文字が枠の下で見切れた（利用者の画面）。
  // 字が必要な高さより小さく切られず、上の帯にも収まることを確かめる（修正前は必要32pxに対して28px）。
  for (final scale in [1.0]) {
    for (final width in [320.0, 393.0]) {
      testWidgets('保存中の表示は欠けずに上の帯へ収まる（幅$width）', (t) async {
        await t.binding.setSurfaceSize(Size(width, 852));
        addTearDown(() => t.binding.setSurfaceSize(null));
        final a = f.rec('2026-10-25', rack: 1085);
        final pending = Completer<ViewerData?>();
        viewerRainbowEditor = (_, _) => pending.future;
        await t.pumpWidget(
          MaterialApp(
            theme: buildAppTheme(),
            home: MediaQuery(
              data: MediaQueryData(
                size: Size(width, 852),
                textScaler: TextScaler.linear(scale),
              ),
              child: ViewerRecordPage(
                data: ViewerData(records: [a]),
                record: a,
              ),
            ),
          ),
        );
        await tap(t, find.byKey(toggleKey));
        final button = t.getRect(find.byKey(saveKey));
        final toolbar = t.getRect(
          find.descendant(
            of: find.byType(AppBar),
            matching: find.byType(NavigationToolbar),
          ),
        );
        expect(button.top, greaterThanOrEqualTo(toolbar.top));
        expect(button.bottom, lessThanOrEqualTo(toolbar.bottom));
        expect(button.right, lessThanOrEqualTo(width));
        final text = t.renderObject<RenderParagraph>(
          find.descendant(
            of: find.byKey(saveKey),
            matching: find.byType(RichText),
          ),
        );
        // 枠の中で、字が必要な高さ・幅より小さく切られていない。
        final shown = t.getRect(
          find.descendant(
            of: find.byKey(saveKey),
            matching: find.byType(RichText),
          ),
        );
        expect(
          text.size.height,
          greaterThanOrEqualTo(
            text.getMinIntrinsicHeight(text.size.width) - 0.5,
          ),
        );
        expect(text.didExceedMaxLines, isFalse);
        expect(shown.top, greaterThanOrEqualTo(button.top));
        expect(shown.bottom, lessThanOrEqualTo(button.bottom));
        expect(find.textContaining('1085番台'), findsWidgets);
        pending.complete(null);
        await t.pumpAndSettle();
        expect(t.takeException(), isNull);
      });
    }
  }
  // 2026-10-29：欠測日の案内から開く画面へ、🌈保存前の古い内容（widget.data）を渡していた。
  testWidgets('🌈保存後に欠測日の案内から開いた画面も、保存後の内容を使う', (t) async {
    await f.phone(t);
    final a = f.rec('2026-10-25', rack: 1085),
        b = f.rec('2026-10-26', rack: 1085, machine: '別機種');
    viewerRainbowEditor = (record, on) async => ViewerData(
      records: [
        a.copyWith(extra: {'rainbow': true}),
        b,
      ],
    );
    await t.pumpWidget(
      f.app(
        ViewerRecordPage(
          data: ViewerData(records: [a, b]),
          record: a,
        ),
      ),
    );
    await tap(t, find.byKey(toggleKey));
    expect(shown(t).record.rainbow, isTrue);
    await tap(t, find.byTooltip('次の記録日'));
    expect(find.text('この日の記録はありません'), findsOneWidget);
    await tap(t, find.text('この日の「別機種」を見る'));
    expect(shown(t).record.key, b.key);
    await tap(t, find.byTooltip('前の記録日'));
    await tap(t, find.textContaining('」を見る'));
    expect(shown(t).record.key, a.key);
    expect(shown(t).record.rainbow, isTrue);
    expect(t.takeException(), isNull);
  });
  testWidgets('保存失敗を案内して再操作できる', (t) async {
    await f.phone(t);
    final a = f.rec('2026-10-25');
    viewerRainbowEditor = (_, _) async => throw StateError('保存の試験');
    await t.pumpWidget(
      f.app(
        ViewerRecordPage(
          data: ViewerData(records: [a]),
          record: a,
        ),
      ),
    );
    await tap(t, find.byKey(toggleKey));
    expect(find.textContaining('1番台の🌈保存を完了できませんでした'), findsOneWidget);
    expect(find.byKey(saveKey), findsNothing);
    expect(find.byKey(toggleKey), findsOneWidget);
    expect(t.takeException(), isNull);
  });
}
