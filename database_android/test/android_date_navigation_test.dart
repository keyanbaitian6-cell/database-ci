import 'dart:async';

import 'package:database_android/android_record_page.dart';
import 'package:database_android/date_events.dart';
import 'package:database_android/main.dart';
import 'package:database_android/machine_sections.dart';
import 'package:database_android/models.dart';
import 'package:database_android/record_analysis.dart';
import 'package:database_android/shared_widgets.dart';
import 'package:database_android/viewer_pages.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'android_variety_review_test.dart' show ReviewController, app;

SlotRecord row(String day, {String machine = '北斗', int rack = 1}) => SlotRecord(
  store: 'nagamachiminami',
  day: day,
  machine: machine,
  rack: rack,
  games: 3000,
  bb: 15,
  rb: 5,
);

ReviewController data() {
  final c = ReviewController()
    ..records = [
      row('2026-09-28'),
      row('2026-09-25'),
      row('2026-09-24', machine: '別機種'),
    ];
  for (final e in [
    const DateEvent(
      store: 'nagamachiminami',
      day: '2026-09-28',
      name: '超探す楽しみ',
    ),
    const DateEvent(store: 'nagamachiminami', day: '2026-09-25', name: '4台構成'),
    const DateEvent(store: 'saiwaichou', day: '2026-09-25', name: '他店舗イベント'),
  ]) {
    c.dateEvents[e.key] = e;
  }
  return c;
}

Future<void> phone(WidgetTester tester, ReviewController c) async {
  await tester.binding.setSurfaceSize(const Size(393, 852));
  addTearDown(() => tester.binding.setSurfaceSize(null));
  addTearDown(c.dispose);
}

Future<void> previous(WidgetTester tester) async {
  await tester.tap(find.byTooltip('前の記録日'));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('各台：日付を素早く戻した後、遅い前日の計算で上書きされない', (tester) async {
    final c = DelayedController()
      ..records = [row('2026-09-28'), row('2026-09-25')];
    await phone(tester, c);
    await tester.pumpWidget(
      app(AndroidRecordPage(controller: c, record: c.records.first)),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('前の記録日'));
    await tester.pump();
    await tester.tap(find.byTooltip('次の記録日'));
    await tester.pumpAndSettle();
    c.pending.complete(
      calculateDay((c.records, 'nagamachiminami', '2026-09-25')),
    );
    await tester.pumpAndSettle();
    expect(
      tester.widget<SavedGraphPage>(find.byType(SavedGraphPage)).record.day,
      '2026-09-28',
    );
    expect(
      tester.widget<ViewerDateBar>(find.byType(ViewerDateBar)).day,
      '2026-09-28',
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('各台：イベントの更新を反映し、読み込み中に閉じても例外にならない', (tester) async {
    final c = DelayedController()
      ..records = [row('2026-09-28'), row('2026-09-25')];
    await phone(tester, c);
    await tester.pumpWidget(
      app(AndroidRecordPage(controller: c, record: c.records.first)),
    );
    await tester.pumpAndSettle();
    const event = DateEvent(
      store: 'nagamachiminami',
      day: '2026-09-28',
      name: '華の日',
    );
    c.dateEvents[event.key] = event;
    c.replaceRecords(c.records);
    await tester.pumpAndSettle();
    expect(find.text('華の日'), findsOneWidget);
    await tester.tap(find.byTooltip('前の記録日'));
    await tester.pump();
    await tester.pumpWidget(app(const SizedBox()));
    c.pending.complete(
      calculateDay((c.records, 'nagamachiminami', '2026-09-25')),
    );
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });

  testWidgets('各台：日付とイベント切替、別機種への入替日は空表示、次の日に戻れる', (tester) async {
    final c = data();
    await phone(tester, c);
    await tester.pumpWidget(
      app(AndroidRecordPage(controller: c, record: c.records.first)),
    );
    await tester.pumpAndSettle();
    expect(find.text('超探す楽しみ'), findsOneWidget);
    await previous(tester);
    expect(
      tester.widget<SavedGraphPage>(find.byType(SavedGraphPage)).record.day,
      '2026-09-25',
    );
    expect(find.text('4台構成'), findsOneWidget);
    expect(find.text('他店舗イベント'), findsNothing);
    await previous(tester);
    expect(find.byType(SavedGraphPage), findsNothing);
    expect(find.text('この日の記録はありません'), findsOneWidget);
    expect(
      tester
          .widget<IconButton>(
            find.byWidgetPredicate(
              (w) => w is IconButton && w.tooltip == '前の記録日',
            ),
          )
          .onPressed,
      isNull,
    );
    await tester.tap(find.byTooltip('次の記録日'));
    await tester.pumpAndSettle();
    expect(find.byType(SavedGraphPage), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('各台：表示中の削除を反映し、古い台データを残さない', (tester) async {
    final c = data();
    await phone(tester, c);
    await tester.pumpWidget(
      app(AndroidRecordPage(controller: c, record: c.records.first)),
    );
    await tester.pumpAndSettle();
    c.replaceRecords([row('2026-09-28', rack: 2), row('2026-09-25')]);
    await tester.pumpAndSettle();
    expect(find.text('この日の記録はありません'), findsOneWidget);
    await previous(tester);
    expect(
      tester.widget<SavedGraphPage>(find.byType(SavedGraphPage)).record.rack,
      1,
    );
  });

  testWidgets('履歴機種：グラフ表示を保って日付・イベント・台の詳細を切替', (tester) async {
    final c = data();
    await phone(tester, c);
    await tester.pumpWidget(
      app(
        HistoryGroupPage(
          controller: c,
          day: '2026-09-28',
          store: 'nagamachiminami',
          machine: '北斗',
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('グラフ表示'));
    await tester.pumpAndSettle();
    await previous(tester);
    final section = tester.widget<MachineSection>(find.byType(MachineSection));
    expect(section.graph, isTrue);
    expect(section.entries.single.$1.day, '2026-09-25');
    expect(find.text('4台構成'), findsOneWidget);
    section.onTap(section.entries.single.$1, section.entries.single.$2);
    await tester.pumpAndSettle();
    expect(find.byType(AndroidRecordPage), findsOneWidget);
    await previous(tester);
    expect(find.text('この日の記録はありません'), findsOneWidget);
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(
      tester.widget<ViewerDateBar>(find.byType(ViewerDateBar)).day,
      '2026-09-25',
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('結果：候補の日付を切り替え、一覧をスクロールしても日付バーを操作できる', (tester) async {
    final c = data();
    await phone(tester, c);
    await tester.pumpWidget(app(ResultsPage(controller: c)));
    await tester.pumpAndSettle();
    final barY = tester.getTopLeft(find.byType(ViewerDateBar)).dy;
    expect(
      tester
          .widget<NextDayCandidatesCard>(find.byType(NextDayCandidatesCard))
          .day,
      '2026-09-28',
    );
    await tester.drag(find.byType(ListView).first, const Offset(0, -650));
    await tester.pumpAndSettle();
    expect(tester.getTopLeft(find.byType(ViewerDateBar)).dy, barY);
    await previous(tester);
    expect(
      tester.widget<ViewerDateBar>(find.byType(ViewerDateBar)).day,
      '2026-09-25',
    );
    expect(find.text('4台構成'), findsOneWidget);
    await tester.drag(find.byType(ListView).first, const Offset(0, 2000));
    await tester.pumpAndSettle();
    final card = tester.widget<NextDayCandidatesCard>(
      find.byType(NextDayCandidatesCard),
    );
    expect(card.day, '2026-09-25');
    card.onPick(c.records[1]);
    await tester.pumpAndSettle();
    expect(find.byType(AndroidRecordPage), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('各台：遅い計算中は古い日を隠し、失敗後も日付変更できる', (tester) async {
    final c = DelayedController()..records = data().records;
    await phone(tester, c);
    await tester.pumpWidget(
      app(AndroidRecordPage(controller: c, record: c.records.first)),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('前の記録日'));
    await tester.pump();
    expect(find.byType(SavedGraphPage), findsNothing);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    c.pending.completeError(Exception('test error'));
    await tester.pumpAndSettle();
    expect(find.textContaining('採点できませんでした'), findsOneWidget);
    await tester.tap(find.byTooltip('次の記録日'));
    await tester.pumpAndSettle();
    expect(find.byType(SavedGraphPage), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}

class DelayedController extends ReviewController {
  final pending = Completer<DayView>();
  @override
  Future<DayView> dayView(String store, String day) =>
      day == '2026-09-25' ? pending.future : super.dayView(store, day);
}
