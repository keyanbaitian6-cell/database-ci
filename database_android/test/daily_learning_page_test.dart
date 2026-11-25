import 'dart:convert';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:database_android/daily_learning_page.dart';
import 'package:database_android/models.dart';

Map<String, dynamic> fixture() => {
  'format': 'daily-learning',
  'version': 1,
  'updated_at': '2026-11-11T07:30:00+09:00',
  'status': '学習済み・比較中',
  'days': [
    {
      'target': '2026-11-11',
      'input_day': '2026-11-10',
      'saved_at': '2026-11-11T07:30:00+09:00',
      'groups': [
        {
          'store': 'nagamachiminami',
          'name': '試験機',
          'active': 'current',
          'status': '改善未確認',
          'selected': [
            ['nagamachiminami', '', '試験機', 101],
          ],
        },
      ],
    },
  ],
};

void main() {
  test('最初に開く対象日は23:30から翌日（日本時間）', () {
    expect(
      dailyDefaultTarget(DateTime.parse('2026-11-11T14:29:59Z')),
      '2026-11-11',
    );
    expect(
      dailyDefaultTarget(DateTime.parse('2026-11-11T14:30:00Z')),
      '2026-11-12',
    );
    expect(
      dailyDefaultTarget(DateTime.parse('2026-11-11T22:59:00Z')),
      '2026-11-12',
    );
    expect(
      dailyDefaultTarget(DateTime.parse('2026-12-31T14:45:00Z')),
      '2027-01-01',
    );
  });
  test('日次学習の形式と保存時刻形式を検査する', () {
    expect(parseDailyLearning(jsonEncode(fixture()))['days'], hasLength(1));
    final raw = fixture();
    (raw['days'] as List).first['saved_at'] = '2026-11-11T07:30:00';
    expect(() => parseDailyLearning(jsonEncode(raw)), throwsFormatException);
    expect(() => parseDailyLearning('{}'), throwsFormatException);
  });
  test('閲覧側はタイムゾーン付き日時形式のみ検査し、時間帯で拒否しない', () {
    // 2026-11-25 利用者の決定で閲覧側の保存時間帯チェックを撤廃（対象日の保存時刻はPC側だけで管理）。
    for (final (stamp, ok) in [
      ('2026-11-10T23:30:00+09:00', true),
      ('2026-11-10T23:29:59+09:00', true),
      ('2026-11-11T00:00:00+09:00', true),
      ('2026-11-11T08:00:00+09:00', true),
      ('2026-11-11T15:30:00+09:00', true),
      ('2026-11-11T23:30:00+09:00', true),
      ('2026-11-10T14:30:00Z', true),
      ('2026-11-11T07:30:00', false),
      ('not-a-date', false),
      ('', false),
    ]) {
      final raw = fixture();
      final day = (raw['days'] as List).first as Map;
      day['saved_at'] = stamp;
      for (final g in day['groups'] as List) {
        (g as Map).remove('saved_at');
      }
      if (ok) {
        expect(
          parseDailyLearning(jsonEncode(raw))['days'],
          hasLength(1),
          reason: stamp,
        );
      } else {
        expect(
          () => parseDailyLearning(jsonEncode(raw)),
          throwsFormatException,
          reason: stamp,
        );
      }
    }
  });
  // 対象日の選択欄から日を選ぶ（過去日には「・過去日」が付く）。
  Future<void> pickDay(WidgetTester tester, String label) async {
    await tester.tap(find.byType(DropdownButton<String>).last);
    await tester.pumpAndSettle();
    await tester.tap(find.text(label).last);
    await tester.pumpAndSettle();
  }

  testWidgets('店舗・対象日・従来方式・候補とエラーを表示する', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: DailyLearningPage(load: () async => jsonEncode(fixture())),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('日次学習・採用中の候補'), findsOneWidget);
    await pickDay(tester, '11月11日（水）・過去日');
    expect(find.text('採用中 従来方式'), findsOneWidget);
    expect(find.text('101番'), findsOneWidget);
    expect(find.text('1台'), findsWidgets);
    expect(find.textContaining('過去の対象日です'), findsOneWidget);
    await tester.pumpWidget(
      MaterialApp(
        home: DailyLearningPage(
          key: const ValueKey('failure'),
          load: () async => throw StateError('失敗'),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.textContaining('日次学習を読み込めません'), findsOneWidget);
  });
  testWidgets('半角カナの機種名を全角にそろえて表示する', (tester) async {
    // 2026-11-12 iPhoneの閲覧ページで半角カナ（例「ｻﾝﾌﾞﾚｲｸ」）が□になった。ほかの画面と同じ displayMachineName を通す。
    final raw = fixture();
    final g = ((raw['days'] as List).first['groups'] as List).first as Map;
    g['name'] = 'L MHRｻﾝﾌﾞﾚｲｸXA';
    g['selected'] = [
      ['nagamachiminami', '', 'L MHRｻﾝﾌﾞﾚｲｸXA', 1157],
    ];
    await tester.pumpWidget(
      MaterialApp(home: DailyLearningPage(load: () async => jsonEncode(raw))),
    );
    await tester.pumpAndSettle();
    await pickDay(tester, '11月11日（水）・過去日');
    expect(find.text('L MHRサンブレイクXA'), findsOneWidget);
    expect(find.text('1157番'), findsOneWidget);
    expect(find.textContaining('ｻﾝ'), findsNothing);
  });

  testWidgets('P-STATIONの台番号はWebだけで、共有カレンダーと同じ営業日の台を開く', (tester) async {
    const pstation = 'pscube:c740601:20';
    final now = DateTime.parse('2026-11-12T02:59:59+09:00');
    final raw = fixture();
    raw['days'] = [
      for (final day in ['2026-11-12', '2026-11-04', '2026-11-03'])
        {
          'target': day,
          'saved_at': '${day}T01:00:00+09:00',
          'groups': [
            {
              'store': pstation,
              'name': 'バラエティ',
              'active': 'current',
              'status': '改善未確認',
              'selected': [
                [pstation, '20', 'L MHRｻﾝﾌﾞﾚｲｸXA', 1286],
                [pstation, '20', '出典なし', 1290],
              ],
            },
            {
              'store': 'nagamachiminami',
              'name': '試験機',
              'active': 'current',
              'status': '改善未確認',
              'selected': [
                ['nagamachiminami', '', '試験機', 101],
              ],
            },
          ],
        },
    ];
    SlotRecord row(String day, String code, {String host = 'm.site777.jp'}) =>
        SlotRecord(
          store: pstation,
          day: day,
          machine: 'L MHRｻﾝﾌﾞﾚｲｸXA',
          rack: 1286,
          games: 2000,
          bb: 10,
          rb: 5,
          extra: {
            'source_site': 'site777',
            'source_url': 'https://$host/f/D3300.do?mdc=$code',
          },
        );
    final opened = <String>[];
    await tester.pumpWidget(
      MaterialApp(
        home: DailyLearningPage(
          store: pstation,
          load: () async => jsonEncode(raw),
          now: () => now,
          records: [
            row('2026-11-11', '0200'),
            row('2026-11-10', '0100'),
            row('2026-11-12', '9999', host: 'invalid.example'),
          ],
          openSite: (url) {
            opened.add(url);
            return true;
          },
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('L MHRサンブレイクXA'), findsOneWidget);
    expect(find.text('1290番'), findsOneWidget);
    expect(find.byTooltip('1290番の11月11日（水）のデータをサイトセブンで開く'), findsNothing);
    expect(opened, isEmpty, reason: '表示だけではリンク先を開かない');

    Finder link(String day) =>
        find.byTooltip('1286番の${dailyDateLabel(day)}のデータをサイトセブンで開く');
    final current = link('2026-11-11');
    if (kIsWeb) {
      expect(current, findsOneWidget, reason: '日本時間3時前の翌日候補は当営業日を開く');
      await tester.ensureVisible(current);
      await tester.tap(current);
      expect(opened, [
        'https://m.site777.jp/f/D4000.do?pmc=04034001&mdc=0200&dtdd=0&dn=1286',
      ]);
    } else {
      expect(current, findsNothing);
      expect(find.text('1286番'), findsOneWidget);
      await tester.tap(find.text('1286番'));
      expect(opened, isEmpty);
    }
    await pickDay(tester, '${dailyDateLabel('2026-11-04')}・過去日');
    final recent = link('2026-11-04');
    expect(recent, kIsWeb ? findsOneWidget : findsNothing);
    if (kIsWeb) {
      await tester.ensureVisible(recent);
      await tester.tap(recent);
      expect(opened.last, contains('&dtdd=7&dn=1286'));
    }
    await pickDay(tester, '${dailyDateLabel('2026-11-03')}・過去日');
    expect(link('2026-11-03'), findsNothing, reason: '8日前はリンクの対象外');
    expect(find.text('1286番'), findsOneWidget);

    await tester.tap(find.byType(DropdownButton<String>).first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('長町南').last);
    await tester.pumpAndSettle();
    expect(find.text('101番'), findsOneWidget);
    expect(find.byTooltip('101番の11月3日（火）のデータをサイトセブンで開く'), findsNothing);
  });

  // 2026-11-12：4画面で同じ順・意味にそろえた表示。
  Map<String, dynamic> many() {
    const long = 'とても長い機種名の表示を確かめるための試験機・スーパーロングネームエディションｻﾝﾌﾞﾚｲｸ';
    return {
      'format': 'daily-learning',
      'version': 1,
      'updated_at': '2026-11-11T07:30:00+09:00',
      'status': '長町南：11/11の事前予測は保存済みです／幸町：処理失敗（原本DBを読めません）。従来方式を使用してください／同期先未設定または利用不可',
      'days': [
        {
          'target': '2026-11-11',
          'input_day': '2026-11-10',
          'saved_at': '2026-11-11T00:30:00+09:00',
          'groups': [
            {
              'store': 'nagamachiminami',
              'name': long,
              'active': 'learned',
              'status': '改善を確認して採用中',
              'selected': [
                for (final n in [1162, 1157, 1203, 1204, 1205, 1206, 1207])
                  ['nagamachiminami', '', long, n],
              ],
            },
            {
              'store': 'nagamachiminami',
              'name': 'バラエティ',
              'active': 'current',
              'status': '学習データ不足・従来方式',
              'selected': [
                ['nagamachiminami', '', '機種A', 301],
                ['nagamachiminami', '', 'ｷｼｭﾋﾞｰ', 305],
              ],
            },
            {
              'store': 'saiwaichou',
              'name': '試験機',
              'active': 'current',
              'status': 'x',
              'selected': [
                ['saiwaichou', '', '試験機', 1],
              ],
            },
          ],
        },
      ],
    };
  }

  test('候補数・台の順番・注意の振り分け', () {
    final now = DateTime.parse('2026-11-11T07:00:00+09:00');
    final v = DailyView(many(), 'nagamachiminami', '2026-11-11', now);
    expect(v.count, 9);
    expect(v.scope, '1機種とバラエティ');
    expect(v.groups.map((g) => [for (final r in g.racks) r.rack]).toList(), [
      [1162, 1157, 1203, 1204, 1205, 1206, 1207],
      [301, 305],
    ]);
    expect(v.groups[1].racks.map((r) => r.machine).toList(), ['機種A', 'ｷｼｭﾋﾞｰ']);
    expect(v.groups[0].racks.first.machine, isNull);
    expect(v.alerts, ['同期先未設定または利用不可']);
    final s = DailyView(many(), 'saiwaichou', '2026-11-11', now);
    expect(s.alerts.first, startsWith('処理失敗'));
    final none = DailyView(many(), 'pscube:c740601:20', '2026-11-11', now);
    expect(none.count, 0);
    expect(none.alerts.last, contains('保存済み候補はありません'));
    final later = DailyView(
      many(),
      'nagamachiminami',
      '2026-11-11',
      DateTime.parse('2026-11-14T09:00:00+09:00'),
    );
    expect(
      later.alerts.join(),
      allOf(contains('過去の対象日'), contains('11月14日（土）の分の処理結果は届いていません')),
    );
    // 2026-11-12：前の晩の23:30台に保存した候補に、0時を過ぎると「本日の処理結果は届いていません」と出ていた。
    const saved = '2026-11-12T23:40:00+09:00';
    DateTime at(String s) => DateTime.parse(s);
    for (final t in [
      '2026-11-12T23:45:00+09:00',
      '2026-11-13T00:10:00+09:00',
      '2026-11-13T07:00:00+09:00',
      '2026-11-13T15:00:00+09:00',
      '2026-11-13T23:29:00+09:00',
    ]) {
      expect(dailyStale(saved, at(t)), isFalse, reason: t);
    }
    expect(dailyStale(saved, at('2026-11-13T23:30:00+09:00')), isTrue);
    expect(
      dailyStale('2026-11-12T08:10:00+09:00', at('2026-11-13T06:00:00+09:00')),
      isTrue,
    );
    expect(
      dailyStale('2026-11-12T23:29:59+09:00', at('2026-11-12T23:45:00+09:00')),
      isTrue,
    );
    expect(
      dailyStale('2026-11-12T14:40:00Z', at('2026-11-13T06:00:00+09:00')),
      isFalse,
    );
    expect(dailyStale('x', at('2026-11-13T06:00:00+09:00')), isTrue);
    final night = many()..['updated_at'] = saved;
    expect(
      DailyView(
        night,
        'nagamachiminami',
        '2026-11-11',
        at('2026-11-13T06:00:00+09:00'),
      ).alerts.join(),
      isNot(contains('届いていません')),
    );
    expect(dailyDateLabel('2026-11-12'), '11月12日（木）');
    expect(dailyTime('2026-11-11T15:02:00Z'), '11月12日 0:02');
  });

  for (final width in [320.0, 393.0, 1280.0]) {
    testWidgets('幅${width.toInt()}で長い機種名・7台・バラエティでもはみ出さず、説明は開閉できる', (
      tester,
    ) async {
      tester.view.physicalSize = Size(width, 2400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(
        MaterialApp(
          home: DailyLearningPage(load: () async => jsonEncode(many())),
        ),
      );
      await tester.pumpAndSettle();
      await pickDay(tester, '11月11日（水）・過去日');
      expect(
        tester.takeException(),
        isNull,
      ); // はみ出し（RenderFlex overflowed）があると例外になる
      expect(find.text('9台'), findsOneWidget);
      expect(find.text('採用中 日次学習版'), findsOneWidget);
      expect(find.text('採用中 従来方式'), findsOneWidget);
      // ラベルは1行（2026-11-12、320px幅で2行に折れていた）。13pxの文字1行分の高さ。
      expect(tester.getSize(find.text('採用中 日次学習版')).height, lessThan(20));
      expect(find.textContaining('ｻﾝ'), findsNothing);
      expect(find.textContaining('ｷｼｭ'), findsNothing);
      expect(find.text('キシュビー'), findsOneWidget);
      // 台は保存した順のまま。
      final racks = tester
          .widgetList<Text>(find.byType(Text))
          .map((t) => t.textSpan?.toPlainText() ?? t.data ?? '')
          .where((s) => RegExp(r'^\d+番$').hasMatch(s))
          .toList();
      expect(racks, [
        '1162番',
        '1157番',
        '1203番',
        '1204番',
        '1205番',
        '1206番',
        '1207番',
        '301番',
        '305番', //
      ]);
      // 注意は開いたまま、説明は閉じている。
      expect(find.textContaining('過去の対象日です'), findsOneWidget);
      expect(find.text('改善を確認して採用中'), findsNothing);
      await tester.tap(find.text('採用方式の説明・保存時刻').first);
      await tester.pumpAndSettle();
      expect(find.text('改善を確認して採用中'), findsOneWidget);
      expect(find.text('保存 11月11日 0:30（日本時間）'), findsWidgets);
      expect(tester.takeException(), isNull);
    });
  }
}
