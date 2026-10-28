// 閲覧ページ（iPhone）で付け外しした🌈（2026-10-11、RAINBOW.md「iPhoneから付ける」）。端末の内容の
// rainbow_marks に時刻つきで持ち、台の記録の rainbow_at（PCで付け外しした時刻）より新しいものを表示に使う。
import 'dart:convert';

import 'package:database_android/models.dart';
import 'package:database_android/rainbow_marks.dart';
import 'package:database_android/theme.dart';
import 'package:database_android/viewer_data.dart';
import 'package:database_android/viewer_pages.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, Object?> raw(
  int rack, {
  String day = '2026-10-10',
  Map<String, Object?> extra = const {},
}) => {
  'store': 'nagamachiminami',
  'kind_code': 21,
  'day': day,
  'machine': '化物語',
  'rack': rack,
  'games': 3000,
  'bb': 10,
  'rb': 5,
  'max_hold': 1000,
  ...extra,
};

String doc(
  List<Map<String, Object?>> records, {
  String exported = '2026-10-10T23:00:00+09:00',
}) => jsonEncode({
  'header': {
    'format': 'database-backup',
    'version': 1,
    'source': 'pc',
    'exported_at': exported,
  },
  'records': records,
});

SlotRecord recordOf(String text, int rack) =>
    ViewerData.parse(text).records.firstWhere((r) => r.rack == rack);

void main() {
  final now = DateTime.utc(2026, 10, 11, 13);

  // 2026-10-29：端末の内容はまるごと読まず、最上位の rainbow_marks だけを差し替える。まるごと読んで
  // 書き直した従来の結果と、同じ文字（並びも同じ）・同じ中身になる。読めない形は従来どおりに読む。
  test('replacing only rainbow_marks gives the same text as rewriting all', () {
    String rewrite(String text, SlotRecord record, bool on) {
      final decoded = Map<String, dynamic>.from(jsonDecode(text) as Map);
      final marks = rainbowMarksOf(decoded);
      final key = '${record.store}|${record.day}|${record.rack}';
      marks[key] = updateRainbowMark(text, record, on, now).mark;
      return jsonEncode({
        ...decoded,
        'rainbow_marks': [
          for (final k in marks.keys.toList()..sort()) marks[k]!.toJson(),
        ],
      });
    }

    final tricky = raw(
      1086,
      extra: {
        'memo': r'括弧{"rainbow_marks":[1]}と\"引用\"と\\と]}',
        'nested': {
          'rainbow_marks': [
            {'x': '}'},
          ],
        },
      },
    );
    final marked = setRainbowMark(
      doc([raw(1085)]),
      recordOf(doc([raw(1085)]), 1085),
      true,
      now,
    );
    final cases = <String>[
      doc([raw(1085), tricky]),
      // 印が途中にあり、後ろにも項目がある。
      jsonEncode({
        'format': 'x',
        'rainbow_marks': (jsonDecode(marked) as Map)['rainbow_marks'],
        'records': [raw(1085), tricky],
        'tail': {'a': '"}'},
      }),
      jsonEncode({
        'records': [raw(1085)],
        'rainbow_marks': null,
      }),
      // 改行・字下げのある形（文字は変わるが、中身は同じ）。
      const JsonEncoder.withIndent('  ').convert(jsonDecode(marked)),
    ];
    for (final text in cases) {
      // まるごと読む代わりの近道が使われる（読めずに従来の読み方へ戻っていない）。
      expect(topLevelJsonValue(text, 'rainbow_marks'), isNotNull);
      final record = recordOf(text, 1085);
      for (final on in [true, false]) {
        final update = updateRainbowMark(text, record, on, now);
        expect(jsonDecode(update.text), jsonDecode(rewrite(text, record, on)));
        if (!text.contains('\n')) {
          expect(update.text, rewrite(text, record, on));
        }
        expect(update.marks[update.mark.key], same(update.mark));
      }
    }
    final span = topLevelJsonValue(cases[1], 'rainbow_marks')!;
    expect(
      jsonDecode(cases[1].substring(span.start, span.end)),
      (jsonDecode(cases[1]) as Map)['rainbow_marks'],
    );
    expect(topLevelJsonValue(cases[0], 'rainbow_marks')!.start, -1);
    // 最上位がオブジェクトでない・閉じていないものは読めない（従来の読み方へ）。
    expect(topLevelJsonValue('[1]', 'rainbow_marks'), isNull);
    expect(topLevelJsonValue('{"a":"}', 'rainbow_marks'), isNull);
  });

  // 2026-10-29：閲覧ページは🌈を付けるたびに端末の内容をまるごと3回読み、iPhoneで落ちた。
  // 保存後の表示は読み直さず、表示中の内容へ印を当てる。読み直したときと同じ表示・同じ送信内容になる。
  test('applying the saved marks equals reading the saved text again', () {
    final text = doc([
      raw(1085),
      raw(
        1086,
        extra: {'rainbow': true, 'rainbow_at': '2026-10-11T12:00:00+09:00'},
      ),
      raw(1087, extra: {'rainbow_at': '2026-10-12T23:00:00+09:00'}),
      raw(1085, day: '2026-10-09'),
    ]);
    var stored = text;
    var shown = ViewerData.parse(text);
    for (final (rack, on) in [
      (1085, true),
      (1086, false),
      (1087, true),
      (1085, false),
      (1085, true),
    ]) {
      final record = shown.records.firstWhere(
        (r) => r.rack == rack && r.day == '2026-10-10',
      );
      final update = updateRainbowMark(stored, record, on, now);
      expect(update.text, setRainbowMark(stored, record, on, now));
      expect(sharedRainbowBodyOf(update.marks), sharedRainbowBody(update.text));
      final reread = ViewerData.parse(update.text);
      shown = shown.withRainbowMarks(update.marks);
      String view(ViewerData d) => [
        for (final r in d.records)
          '${r.day}|${r.rack}|${r.rainbow}|${r.extra['rainbow_at']}',
      ].join('\n');
      expect(view(shown), view(reread));
      expect(shown.rainbowMarks.keys, reread.rainbowMarks.keys);
      stored = update.text;
    }
  });

  test('a mark set on the phone shows at once and is sent with every mark', () {
    final text = doc([raw(1085), raw(1086)]);
    final marked = setRainbowMark(text, recordOf(text, 1085), true, now);
    expect(recordOf(marked, 1085).rainbow, isTrue);
    expect(recordOf(marked, 1086).rainbow, isFalse);
    final body = jsonDecode(sharedRainbowBody(marked)) as Map;
    expect(body['file'], 'rainbow');
    expect((body['marks'] as List).single, {
      'store': 'nagamachiminami',
      'day': '2026-10-10',
      'rack': 1085,
      'on': true,
      'updated_at': '2026-10-11T13:00:00.000Z',
    });
    final cleared = setRainbowMark(marked, recordOf(marked, 1085), false, now);
    expect(recordOf(cleared, 1085).rainbow, isFalse);
    expect(
      (jsonDecode(sharedRainbowBody(cleared))['marks'] as List).single['on'],
      isFalse,
    );
  });

  test('the newer of the phone mark and the PC change wins', () {
    // PCで外した（rainbow_at が印より後）→ 外れたまま。PCで付けた時刻が前なら、印の方が勝つ。
    final pcLater = doc([
      raw(1085, extra: {'rainbow_at': '2026-10-11T23:00:00+09:00'}),
    ]);
    final mark = {
      'rainbow_marks': [
        {
          'store': 'nagamachiminami',
          'day': '2026-10-10',
          'rack': 1085,
          'on': true,
          'updated_at': '2026-10-11T13:00:00.000Z',
        },
      ],
    };
    expect(
      recordOf(
        jsonEncode({...jsonDecode(pcLater) as Map, ...mark}),
        1085,
      ).rainbow,
      isFalse,
    );
    final pcEarlier = doc([
      raw(
        1085,
        extra: {'rainbow': true, 'rainbow_at': '2026-10-11T12:00:00+09:00'},
      ),
    ]);
    final off = {
      'rainbow_marks': [
        {
          'store': 'nagamachiminami',
          'day': '2026-10-10',
          'rack': 1085,
          'on': false,
          'updated_at': '2026-10-11T13:00:00.000Z',
        },
      ],
    };
    expect(
      recordOf(
        jsonEncode({...jsonDecode(pcEarlier) as Map, ...off}),
        1085,
      ).rainbow,
      isFalse,
    );
    // 新しく付け直すときは、PCの時刻より必ず後の時刻にする（端末の時計が遅れていても勝つ）。
    final again = setRainbowMark(pcLater, recordOf(pcLater, 1085), true, now);
    expect(recordOf(again, 1085).rainbow, isTrue);
  });

  test(
    'marks survive a Drive refresh, and other devices\' marks are pulled in',
    () {
      final stored = setRainbowMark(
        doc([raw(1085)]),
        recordOf(doc([raw(1085)]), 1085),
        true,
        now,
      );
      final fresh = doc([
        raw(1085),
        raw(1086),
      ], exported: '2026-10-11T23:00:00+09:00');
      final merged = ViewerData.merge(stored, fresh).text;
      expect(
        recordOf(merged, 1085).rainbow,
        isTrue,
        reason: 'Driveの内容に置き換えても端末の🌈は残る',
      );
      final shared = jsonEncode({
        'format': 'database-rainbow',
        'marks': [
          {
            'store': 'nagamachiminami',
            'day': '2026-10-10',
            'rack': 1086,
            'on': true,
            'updated_at': '2026-10-11T14:00:00.000Z',
          },
          {
            'store': 'bad',
            'day': '2026-10-10',
            'rack': 1,
            'on': true,
            'updated_at': '2026-10-11T14:00:00.000Z',
          },
        ],
      });
      final pulled = withSharedRainbow(merged, shared)!;
      expect(recordOf(pulled, 1086).rainbow, isTrue);
      expect(
        withSharedRainbow(pulled, shared),
        isNull,
        reason: '変わらなければ書き直さない',
      );
      expect(
        withSharedRainbow(pulled, '{"error":"指定できないファイルです。"}'),
        isNull,
        reason: '古いスクリプト',
      );
    },
  );

  test('send result explains an old script', () {
    expect(rainbowSendResult('{"ok":true,"marks":1,"changed":1}').ok, isTrue);
    expect(
      rainbowSendResult('{"error":"指定できないファイルです。"}').message,
      contains('新しい版に更新'),
    );
    expect(rainbowSendResult('not json').ok, isFalse);
  });

  testWidgets('rack page shows the toggle only when the viewer can edit', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(393, 852));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    addTearDown(() => viewerRainbowEditor = null);
    final data = ViewerData.parse(doc([raw(1085)]));
    viewerRainbowEditor = null;
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: ViewerRecordPage(data: data, record: data.records.single),
      ),
    );
    await tester.pumpAndSettle();
    expect(
      find.byKey(const ValueKey('rainbow-toggle')),
      findsNothing,
      reason: 'Android版・P’s CUBEでは出さない',
    );
    final asked = <bool>[];
    viewerRainbowEditor = (record, on) async {
      asked.add(on);
      final text = setRainbowMark(doc([raw(1085)]), record, on, now);
      return ViewerData.parse(text);
    };
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: ViewerRecordPage(
          key: const ValueKey('editable'),
          data: data,
          record: data.records.single,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('🌈 付ける'));
    await tester.pumpAndSettle();
    expect(asked, [true]);
    expect(find.text('1085番台 🌈'), findsOneWidget);
    expect(find.text('🌈 外す'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
