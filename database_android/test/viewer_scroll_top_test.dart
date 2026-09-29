import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:database_android/answer_check.dart';
import 'package:database_android/exploratory_page.dart';
import 'package:database_android/models.dart';
import 'package:database_android/shared_widgets.dart';
import 'package:database_android/theme.dart';
import 'package:database_android/viewer_data.dart';
import 'package:database_android/viewer_main.dart';
import 'package:database_android/viewer_pages.dart';

SlotRecord rec(
  String day, {
  String machine = 'テスト',
  int rack = 1,
  int games = 3000,
}) => SlotRecord(
  store: 'nagamachiminami',
  day: day,
  machine: machine,
  rack: rack,
  games: games,
  bb: 10 + rack % 7,
  rb: 5,
  maxHold: 1500,
  graph: const GraphMeasurement(
    baselineY: 200,
    peakY: 100,
    troughY: 250,
    endY: 180,
  ),
);

Widget app(Widget page) => MaterialApp(theme: buildAppTheme(), home: page);

Future<void> phone(WidgetTester tester, {double height = 852}) async {
  await tester.binding.setSurfaceSize(Size(393, height));
  addTearDown(() => tester.binding.setSurfaceSize(null));
}

final topButton = find.byTooltip('一番上へ');

/// 画面のいちばん外側のリスト（本文）の位置。
double offsetOf(WidgetTester tester) => tester
    .state<ScrollableState>(
      find
          .descendant(
            of: find.byType(ListView).first,
            matching: find.byType(Scrollable),
          )
          .first,
    )
    .position
    .pixels;

/// 本文のリストを下へ [distance] だけスクロールする。
Future<void> scrollDown(WidgetTester tester, double distance) async {
  await tester.drag(find.byType(ListView).first, Offset(0, -distance));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('新規予測：戻るボタンが動き、候補のない日へ変えても残らない', (tester) async {
    await phone(tester, height: 400);
    final records = [
      for (var d = 20; d <= 28; d++)
        for (var m = 1; m <= 10; m++)
          for (var rack = 1; rack <= 8; rack++)
            rec('2026-09-$d', machine: '機種$m', rack: m * 10 + rack),
    ];
    await tester.pumpWidget(
      app(
        ExploratoryForecastPage(
          data: ViewerData(records: records),
          store: 'nagamachiminami',
          day: '2026-09-28',
          onOpen: (_) {},
        ),
      ),
    );
    await tester.pumpAndSettle();
    await scrollDown(tester, 1500);
    expect(offsetOf(tester), greaterThan(600));
    expect(topButton, findsOneWidget);
    await tester.tap(topButton);
    await tester.pumpAndSettle();
    expect(offsetOf(tester), 0);
    expect(topButton, findsNothing);
    await scrollDown(tester, 1500);
    final bar = tester.widget<ViewerDateBar>(find.byType(ViewerDateBar));
    bar.onChanged('2026-09-20');
    await tester.pumpAndSettle();
    expect(offsetOf(tester), lessThanOrEqualTo(600));
    expect(topButton, findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('ホーム：600px下へスクロールしたら右下に出て、押すと一番上へ戻り消える', (tester) async {
    await phone(tester);
    final records = [
      for (var m = 1; m <= 20; m++)
        for (var rack = 1; rack <= 4; rack++)
          rec('2026-09-28', machine: '機種$m', rack: m * 10 + rack),
    ];
    await tester.pumpWidget(
      app(ViewerHome(initialData: ViewerData(records: records))),
    );
    await tester.pumpAndSettle();
    expect(topButton, findsNothing);

    // 600px以下では出さない（Android版と同じ）。
    await scrollDown(tester, 500);
    expect(offsetOf(tester), inInclusiveRange(400, 600));
    expect(topButton, findsNothing);

    await scrollDown(tester, 1000);
    expect(offsetOf(tester), greaterThan(600));
    expect(topButton, findsOneWidget);
    // 右下（端から16px前後。丸の外側に押しやすくするための余白が少しある）。
    final corner = tester.getBottomRight(
      find.ancestor(of: topButton, matching: find.byType(Material)).first,
    );
    expect(corner.dx, closeTo(393 - 16, 3));
    expect(corner.dy, closeTo(852 - 16, 3));

    await tester.tap(topButton);
    await tester.pumpAndSettle();
    expect(offsetOf(tester), 0);
    expect(topButton, findsNothing);
    expect(find.textContaining('読み込んだバックアップ'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('機種ページ：日付を変えると一番上から表示し、ボタンも消える', (tester) async {
    await phone(tester);
    final records = [
      for (final day in ['2026-09-28', '2026-09-27'])
        for (var rack = 1; rack <= 40; rack++) rec(day, rack: rack),
    ];
    await tester.pumpWidget(
      app(
        ViewerMachinePage(
          data: ViewerData(records: records),
          store: 'nagamachiminami',
          machine: 'テスト',
          day: '2026-09-28',
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(topButton, findsNothing);
    await scrollDown(tester, 1200);
    expect(topButton, findsOneWidget);

    // 日付の切り替えは上に固定なので、下にいても押せる。
    await tester.tap(find.byTooltip('前の記録日'));
    await tester.pumpAndSettle();
    expect(offsetOf(tester), 0);
    expect(topButton, findsNothing);

    // 新しい日でも、下へスクロールすればまた出て、押すと戻る。
    await scrollDown(tester, 1200);
    expect(topButton, findsOneWidget);
    await tester.tap(topButton);
    await tester.pumpAndSettle();
    expect(offsetOf(tester), 0);
    expect(topButton, findsNothing);
    expect(tester.takeException(), isNull);
  });

  final rackDays = [for (var d = 20; d <= 28; d++) rec('2026-09-$d')];

  testWidgets('台の詳細（閲覧ページ）：下へスクロールしたら出て、押すと一番上へ戻る', (tester) async {
    await phone(tester, height: 600);
    await tester.pumpWidget(
      app(
        ViewerRecordPage(
          data: ViewerData(records: rackDays),
          record: rackDays.last,
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(topButton, findsNothing);
    await scrollDown(tester, 2000);
    expect(offsetOf(tester), greaterThan(600));
    expect(topButton, findsOneWidget);
    await tester.tap(topButton);
    await tester.pumpAndSettle();
    expect(offsetOf(tester), 0);
    expect(topButton, findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('台の詳細（Android版と共通の画面・指定なし）は、これまでどおり出さない', (tester) async {
    // 日付の切り替えが無い分だけ短いので、画面を低くして600pxより下まで動かす。
    await phone(tester, height: 400);
    await tester.pumpWidget(
      app(SavedGraphPage(record: rackDays.last, allRecords: rackDays)),
    );
    await tester.pumpAndSettle();
    await scrollDown(tester, 2000);
    expect(offsetOf(tester), greaterThan(600));
    expect(topButton, findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('答え合わせ：下へスクロールしたら出て、押すと一番上へ戻る', (tester) async {
    await phone(tester);
    final records = [
      for (var d = 10; d <= 28; d++)
        for (var rack = 1; rack <= 8; rack++) rec('2026-09-$d', rack: rack),
    ];
    await tester.pumpWidget(
      app(
        AnswerCheckPage(
          records: records,
          store: 'nagamachiminami',
          onOpen: (_, _) {},
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(topButton, findsNothing);
    await scrollDown(tester, 1500);
    expect(offsetOf(tester), greaterThan(600));
    expect(topButton, findsOneWidget);
    await tester.tap(topButton);
    await tester.pumpAndSettle();
    expect(offsetOf(tester), 0);
    expect(topButton, findsNothing);
    expect(tester.takeException(), isNull);
  });
}
