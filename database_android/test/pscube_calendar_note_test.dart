import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:database_android/machine_sections.dart';
import 'package:database_android/models.dart';
import 'package:database_android/pscube_calendar_note.dart';
import 'package:database_android/theme.dart';
import 'package:database_android/viewer_data.dart';
import 'package:database_android/viewer_main.dart';

import 'pscube_viewer_test.dart' show fixture;

// P-STATION【20】スロの翌日候補に添える暦の注記（2026-11-11 利用者「iPhoneのページにお願いします」）。
const store = 'pscube:c740601:20';

SlotRecord row(int rack, String machine, {String day = '2026-11-14', String scope = store}) => SlotRecord(
  store: scope,
  day: day,
  rack: rack,
  machine: machine,
  games: 3000,
  bb: 10,
  rb: 10,
);

/// 既存の閲覧ページ用の試験データを、最後の日・機種名・台番号だけ替えて使う。
Map<String, dynamic> shifted(String lastDay, String machine, {int rackBase = 0, String rate = '20'}) {
  final raw = fixture(rate: rate);
  final last = DateTime.parse(lastDay);
  for (final r in (raw['records'] as List).cast<Map<String, dynamic>>()) {
    final ago = DateTime(2026, 10, 1).difference(DateTime.parse(r['day'] as String)).inDays;
    final day = last.subtract(Duration(days: ago)).toIso8601String().substring(0, 10);
    final rack = (r['rack'] as int) + rackBase;
    r['day'] = day;
    r['rack'] = rack;
    r['machine'] = machine;
    r['detail_url'] =
        'https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/cgi-bin/nc-v06-001.php?cd_dai=$rack#${day.replaceAll('-', '')}';
  }
  ((raw['machines'] as List).first as Map<String, dynamic>)['machine'] = machine;
  return raw;
}

Future<void> openHome(WidgetTester tester, Map<String, dynamic> raw) async {
  await tester.binding.setSurfaceSize(const Size(393, 3000));
  addTearDown(() => tester.binding.setSurfaceSize(null));
  await tester.pumpWidget(
    MaterialApp(
      theme: buildAppTheme(),
      home: ViewerHome(initialData: ViewerData.parse(jsonEncode(raw))),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  // 記録の機種名は半角カナのことがある（P’s CUBE・サイトセブン）。
  final rows = [
    row(1300, 'ｺﾞｰｺﾞｰｼﾞｬｸﾞﾗｰ3'),
    row(1323, 'ﾏｲｼﾞｬｸﾞﾗｰV'),
    row(1123, 'Lﾓﾝｽﾀｰﾊﾝﾀｰﾗｲｽﾞ：ｻﾝﾌﾞﾚｲｸ'),
    row(1223, 'LB SHAKE BONUS TRIGGER'),
  ];

  test('翌日が5・15・25日ならゴーゴージャグラー3の注記を出す', () {
    for (final day in ['2026-11-04', '2026-11-14', '2026-11-24']) {
      final notes = pscubeCalendarNotes(store, day, rows);
      expect(notes, hasLength(1), reason: day);
      expect(notes.single, contains('5のつく日'));
      expect(notes.single, contains('ゴーゴージャグラー3'));
      expect(notes.single, contains('過去の記録では'));
    }
    expect(pscubeCalendarNotes(store, '2026-11-14', rows).single, startsWith('翌日（11/15）'));
    // その日（当日が5のつく日）ではなく、翌日で決める。
    expect(pscubeCalendarNotes(store, '2026-11-15', rows), isEmpty);
    expect(pscubeCalendarNotes(store, '2026-11-05', rows), isEmpty);
  });

  test('ゴーゴージャグラー3の記録が無い日は出さない（撤去・未取り込み）', () {
    expect(pscubeCalendarNotes(store, '2026-11-14', [row(1323, 'ﾏｲｼﾞｬｸﾞﾗｰV')]), isEmpty);
    expect(pscubeCalendarNotes(store, '2026-11-14', const []), isEmpty);
    // 全角の名前でも同じ。
    expect(pscubeCalendarNotes(store, '2026-11-14', [row(1300, 'ゴーゴージャグラー3')]), hasLength(1));
  });

  test('翌日が23日なら、下2桁23のジャグラーだけを台番号と今の機種名で出す', () {
    final notes = pscubeCalendarNotes(store, '2026-11-22', rows);
    expect(notes, hasLength(1));
    expect(notes.single, startsWith('翌日（11/23）は23日です'));
    expect(notes.single, contains('1323番・マイジャグラーV'));
    expect(notes.single, isNot(contains('1123')));     // ジャグラー以外の下2桁23は出さない
    expect(notes.single, isNot(contains('1223')));
    expect(pscubeCalendarNotes(store, '2026-11-23', rows), isEmpty);
    // 入れ替えで機種が変わっていたら、変わった名前がそのまま出る。
    final changed = pscubeCalendarNotes(store, '2026-11-22', [row(1323, 'SマイジャグラーVI')]);
    expect(changed.single, contains('1323番・SマイジャグラーVI'));
    // 下2桁23のジャグラーが無ければ出さない。
    expect(pscubeCalendarNotes(store, '2026-11-22', [row(1300, 'ｺﾞｰｺﾞｰｼﾞｬｸﾞﾗｰ3'), row(1123, 'L北斗')]), isEmpty);
  });

  test('月末は翌月の日で決める・ふつうの日は何も出さない', () {
    expect(pscubeCalendarNotes(store, '2026-11-30', rows), isEmpty);           // 翌日は12/1
    expect(pscubeCalendarNotes(store, '2026-12-31', rows), isEmpty);           // 翌日は1/1
    expect(pscubeCalendarNotes(store, '2027-02-28', rows), isEmpty);           // 翌日は3/1
    expect(pscubeCalendarNotes(store, '2026-12-04', rows).single, startsWith('翌日（12/5）'));
    for (final day in ['2026-11-10', '2026-11-12', '2026-11-20', '2026-11-27']) {
      expect(pscubeCalendarNotes(store, day, rows), isEmpty, reason: day);
    }
    expect(pscubeCalendarNotes(store, 'こわれた日付', rows), isEmpty);
  });

  test('P-STATIONの20スロ以外の店では出さない', () {
    for (final other in ['pscube:c740601:5', 'pscube:c999999:20', 'nagamachiminami', 'saiwaichou']) {
      expect(pscubeCalendarNotes(other, '2026-11-14', rows), isEmpty, reason: other);
      expect(pscubeCalendarNotes(other, '2026-11-22', rows), isEmpty, reason: other);
    }
  });

  testWidgets('注記と断り書きを並べる。注記が無い日は何も置かない', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ListView(
            children: [
              ...pscubeCalendarNoteWidgets(store, '2026-11-14', rows),
              const Text('翌日候補'),
            ],
          ),
        ),
      ),
    );
    expect(find.byKey(const ValueKey('pscube-calendar-note-0')), findsOneWidget);
    expect(find.textContaining('翌日（11/15）は5のつく日です'), findsOneWidget);
    expect(find.text(pscubeCalendarNoteCaveat), findsOneWidget);
    expect(pscubeCalendarNoteWidgets(store, '2026-11-12', rows), isEmpty);
    // 狭い画面（iPhoneの幅）でもはみ出さない。
    tester.view.physicalSize = const Size(320, 640);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });

  testWidgets('閲覧ページ：翌日が15日なら、翌日候補のカードのすぐ上にゴーゴーの注記が出る', (tester) async {
    await openHome(tester, shifted('2026-11-14', 'ｺﾞｰｺﾞｰｼﾞｬｸﾞﾗｰ3', rackBase: 1299));
    final note = find.byKey(const ValueKey('pscube-calendar-note-0'));
    expect(note, findsOneWidget);
    expect(find.textContaining('翌日（11/15）は5のつく日です'), findsOneWidget);
    expect(find.text(pscubeCalendarNoteCaveat), findsOneWidget);
    expect(tester.getTopLeft(note).dy, lessThan(tester.getTopLeft(find.byType(NextDayCandidatesCard)).dy));
    expect(tester.takeException(), isNull);
  });

  testWidgets('閲覧ページ：翌日が23日なら、下2桁23のジャグラーの台番号が出る', (tester) async {
    await openHome(tester, shifted('2026-11-22', 'ﾏｲｼﾞｬｸﾞﾗｰV', rackBase: 1315));   // 1316〜1323番
    expect(find.textContaining('1323番・マイジャグラーV'), findsOneWidget);
    expect(find.textContaining('翌日（11/23）は23日です'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('閲覧ページ：ふつうの日・5スロでは注記を出さない', (tester) async {
    await openHome(tester, shifted('2026-11-12', 'ｺﾞｰｺﾞｰｼﾞｬｸﾞﾗｰ3', rackBase: 1299));
    expect(find.byType(NextDayCandidatesCard), findsOneWidget);
    expect(find.byKey(const ValueKey('pscube-calendar-note-0')), findsNothing);
    expect(find.text(pscubeCalendarNoteCaveat), findsNothing);
    await openHome(tester, shifted('2026-11-14', 'ｺﾞｰｺﾞｰｼﾞｬｸﾞﾗｰ3', rackBase: 1299, rate: '5'));
    expect(find.byType(NextDayCandidatesCard), findsOneWidget);
    expect(find.byKey(const ValueKey('pscube-calendar-note-0')), findsNothing);
  });
}
