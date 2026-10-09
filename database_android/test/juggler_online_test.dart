// ジャグラーオンラインの取り込み（お試し、JUGGLER_ONLINE.md）。端末の画面は実データなので使わず、
// 数字のお手本の形で描いた合成の画面で、読み取り・左右の見分け・まとめ・保存・差枚の優先を確かめる。
import 'package:database_android/app_controller.dart';
import 'package:database_android/database_service.dart';
import 'package:database_android/juggler_digit_templates.dart';
import 'package:database_android/juggler_online.dart';
import 'package:database_android/models.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as imglib;

import 'support/real_database.dart';

final _pinkColor = imglib.ColorRgb8(230, 40, 140);
final _white = imglib.ColorRgb8(255, 255, 255);

/// お手本の形（20×28）を、[x],[y] から実物と同じくらいの大きさで描く（濃さ0.5以上の点）。
int _drawDigit(
  imglib.Image image,
  String digit,
  int x,
  int y,
  imglib.Color color,
) {
  final t = joDigitTemplates.firstWhere((t) => t.digit == digit);
  for (var j = 0; j < joGlyphHeight; j++) {
    for (var i = 0; i < joGlyphWidth; i++) {
      if (t.pixels[j * joGlyphWidth + i] >= 0.5)
        image.setPixel(x + i, y + j, color);
    }
  }
  return x + joGlyphWidth + 4;
}

void _drawNumber(
  imglib.Image image,
  int value,
  int x0,
  int x1,
  int center,
  imglib.Color color,
) {
  final text = '$value';
  final width =
      text.replaceAll('-', '').length * (joGlyphWidth + 4) +
      (value < 0 ? 22 : 0);
  var x = x0 + ((x1 - x0) - width) ~/ 2;
  for (final ch in text.split('')) {
    if (ch == '-') {
      imglib.fillRect(
        image,
        x1: x,
        y1: center - 2,
        x2: x + 16,
        y2: center + 2,
        color: color,
      );
      x += 22;
    } else {
      x = _drawDigit(image, ch, x, center - joGlyphHeight ~/ 2, color);
    }
  }
}

/// 合成の画面。[rows] は（台番号, 列名→値）。上の「ON」スイッチ（中までピンク）と、下で切れた枠も描く。
imglib.Image _screen(List<(int, Map<String, int>)> rows, {bool right = false}) {
  final image = imglib.Image(width: joScreenWidth, height: 2340);
  imglib.fill(image, color: imglib.ColorRgb8(40, 40, 40));
  imglib.fillRect(
    image,
    x1: 95,
    y1: 182,
    x2: 225,
    y2: 228,
    color: _pinkColor,
  ); // ON スイッチ
  final columns = right ? joRightColumns : joLeftColumns;
  for (var r = 0; r < rows.length; r++) {
    final top = 988 + r * 100, bottom = top + 58;
    imglib.drawRect(
      image,
      x1: 94,
      y1: top,
      x2: 223,
      y2: bottom,
      color: _pinkColor,
      thickness: 3,
    );
    final (rack, values) = rows[r];
    _drawNumber(image, rack, 110, 208, (top + bottom) ~/ 2, _pinkColor);
    for (final entry in values.entries) {
      final (x0, x1) = columns[entry.key]!;
      _drawNumber(image, entry.value, x0, x1, (top + bottom) ~/ 2, _white);
    }
  }
  // 下のメニューで切れた枠（上の線だけ）。
  final cut = 988 + rows.length * 100;
  imglib.drawLine(
    image,
    x1: 94,
    y1: cut,
    x2: 223,
    y2: cut,
    color: _pinkColor,
    thickness: 3,
  );
  return image;
}

const _lines = [
  JoTextLine('スーパーメルヘンワールド幸町店'),
  JoTextLine('データ更新：10/9 23:00'),
  JoTextLine('本日 10/9(金)'),
  JoTextLine('20スロ ネオアイムジャグラーEX'),
];

void main() {
  group('見出し', () {
    test('店舗・営業日・機種・貸玉。データ更新の日時は日付にしない', () {
      final h = parseJoHeader(_lines, DateTime(2026, 10, 9, 23));
      expect(
        (h.store, h.day, h.machine, h.rate),
        ('saiwaichou', '2026-10-09', 'ネオアイムジャグラーEX', '20'),
      );
      final past = parseJoHeader(const [
        JoTextLine('データ更新：10/9 23:00'),
        JoTextLine('3日前 10/6(火)'),
        JoTextLine('メルヘンワールド長町南店'),
      ], DateTime(2026, 10, 9));
      expect((past.store, past.day), ('nagamachiminami', '2026-10-06'));
      final newYear = parseJoHeader(const [
        JoTextLine('3日前 12/30（火）'),
      ], DateTime(2027, 1, 2));
      expect(newYear.day, '2026-12-30', reason: '1月に12月の画面を見たときは前の年');
      expect(
        parseJoHeader(const [JoTextLine('ほかの店')], DateTime(2026, 10, 9)).store,
        isNull,
      );
    });
  });

  group('画面の読み取り（合成の画面）', () {
    final left = [
      (779, {'bb': 15, 'rb': 10, 'art': 0, 'start': 288, 'total': 4957}),
      (780, {'bb': 22, 'rb': 20, 'art': 0, 'start': 213, 'total': 4678}),
      (781, {'bb': 7, 'rb': 1, 'art': 0, 'start': 0, 'total': 1404}),
    ];
    final right = [
      (779, {'net': -928}),
      (780, {'net': 1697}),
      (781, {'net': -36}),
    ];

    test('左の画面：台番号とBB〜総回転数（1桁・0も）。ONスイッチと切れた枠は台にしない', () {
      final screen = parseJoScreen(
        _screen(left),
        _lines,
        DateTime(2026, 10, 9),
      );
      expect(screen.problem, isNull);
      expect(screen.side, 'left');
      expect([for (final r in screen.racks) r.rack], [779, 780, 781]);
      for (var i = 0; i < left.length; i++) {
        expect(screen.racks[i].values, left[i].$2);
      }
    });

    test('右へスクロールした画面：差枚（マイナスも）', () {
      final image = _screen(right, right: true);
      final screen = parseJoScreen(image, _lines, DateTime(2026, 10, 9));
      expect(screen.side, 'right');
      expect(
        [for (final r in screen.racks) (r.rack, r.values['net'])],
        [(779, -928), (780, 1697), (781, -36)],
      );
    });

    test('大きさの違う画面・表の無い画面は読まない', () {
      final small = imglib.Image(width: 720, height: 1600);
      expect(
        parseJoScreen(small, _lines, DateTime(2026, 10, 9)).problem,
        contains('大きさ'),
      );
      final empty = imglib.Image(width: joScreenWidth, height: 2340);
      expect(
        parseJoScreen(empty, _lines, DateTime(2026, 10, 9)).problem,
        contains('見つかりません'),
      );
    });

    test('左右の画面を台番号でまとめ、同じ台の値が画面ごとに違えば印を付ける', () {
      final now = DateTime(2026, 10, 9);
      final days = mergeJoScreens([
        parseJoScreen(_screen(left), _lines, now),
        parseJoScreen(_screen(right, right: true), _lines, now),
        parseJoScreen(
          _screen([
            (781, {'net': -40}),
          ], right: true),
          _lines,
          now,
        ),
      ]);
      expect(days.single.store, 'saiwaichou');
      expect(days.single.day, '2026-10-09');
      expect(days.single.racks[779], {
        'bb': 15,
        'rb': 10,
        'art': 0,
        'start': 288,
        'total': 4957,
        'net': -928,
      });
      expect(days.single.conflicts, {
        781: {'net'},
      });
      // ⚠の項目（どちらが正しいか分からない）は保存に回さない。ほかの項目と台はそのまま。
      final save = joSaveValues(days.single);
      expect(save[781]!.containsKey('net'), isFalse);
      expect(save[781]!['total'], days.single.racks[781]!['total']);
      expect(save[779], days.single.racks[779]);
    });

    test('⚠の項目しか無い台は保存に回さない', () {
      final day = JoDay('saiwaichou', '2026-10-06')
        ..racks[790] = {'net': 526}
        ..conflicts[790] = {'net'};
      expect(joSaveValues(day), isEmpty);
    });
  });

  group('保存と差枚の優先', () {
    test('取り込み済みの台にだけ足し、メルヘンの数値は変えない。差枚はジャグラーオンラインを優先', () async {
      final path = await newDatabasePath();
      final db = realDatabase(path);
      SlotRecord rec(int rack) => SlotRecord(
        store: 'saiwaichou',
        day: '2026-10-09',
        machine: 'Sネオアイムジャグラー EX−KK',
        rack: rack,
        games: 4900,
        bb: 15,
        rb: 10,
        maxHold: 1500,
      );
      await db.applyChanges(ChangeSet(upserts: [rec(779), rec(780)]));
      final c = AppController(database: db);
      await c.initialize();
      final result = await c.attachJugglerOnline(
        store: 'saiwaichou',
        day: '2026-10-09',
        racks: {
          779: {'net': -928, 'bb': 15, 'rb': 10, 'start': 288, 'total': 4957},
          781: {'net': 238},
        },
        now: DateTime.utc(2026, 10, 9, 15),
      );
      expect(result.updated, 1);
      expect(result.missing, [781], reason: '取り込んでいない台は作らない');
      final saved = (await db.loadAll()).firstWhere((r) => r.rack == 779);
      expect(
        (saved.games, saved.bb, saved.rb),
        (4900, 15, 10),
        reason: 'メルヘンの数値はそのまま',
      );
      expect(saved.extra['jo_net'], -928);
      expect(saved.extra['jo_games'], 4957);
      expect(saved.extra['jo_start'], 288);
      expect(saved.extra['jo_captured_at'], isA<String>());
      expect(
        (saved.netValue, saved.netLabel, saved.netNeedsCheck),
        (-928, '差枚', false),
      );
      final other = (await db.loadAll()).firstWhere((r) => r.rack == 780);
      expect(other.netLabel, '推定差枚', reason: '足していない台は今までどおり');
      // 取り消しで元に戻る。
      await c.undoLastSave();
      expect(
        (await db.loadAll()).firstWhere((r) => r.rack == 779).extra['jo_net'],
        isNull,
      );
      await db.close();
    });

    test('P’s CUBEの台は jo_net を見ない（元グラフの差枚のまま）', () {
      final r = SlotRecord(
        store: 'pscube:c740601:20',
        day: '2026-10-09',
        machine: 'x',
        rack: 1,
        games: 1,
        bb: 0,
        rb: 0,
        extra: const {'source': 'pscube', 'net_medals': 100, 'jo_net': 5},
      );
      expect(r.netValue, 100);
    });
  });
}
