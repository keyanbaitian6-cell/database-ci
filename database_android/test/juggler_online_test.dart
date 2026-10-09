// ジャグラーオンラインの取り込み（お試し、JUGGLER_ONLINE.md）。端末の画面は実データなので使わず、
// 数字のお手本の形で描いた合成の画面で、読み取り・左右の見分け・まとめ・保存・差枚の優先を確かめる。
import 'dart:convert';

import 'package:database_android/app_controller.dart';
import 'package:database_android/database_service.dart';
import 'package:database_android/import_service.dart';
import 'package:database_android/juggler_digit_templates.dart';
import 'package:database_android/juggler_online.dart';
import 'package:database_android/viewer_data.dart';
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
      if (t.pixels[j * joGlyphWidth + i] >= 0.5) {
        image.setPixel(x + i, y + j, color);
      }
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
/// ページの印「«」「»」（実物と同じく細い線の山形2つ）。
void _chevrons(imglib.Image image, imglib.Color color, {required bool left}) {
  for (final x in left ? [24, 46] : [1012, 1034]) {
    final (tip, base) = left ? (x, x + 16) : (x + 16, x);
    imglib.drawLine(
      image,
      x1: base,
      y1: 1424,
      x2: tip,
      y2: 1445,
      color: color,
      thickness: 6,
    );
    imglib.drawLine(
      image,
      x1: tip,
      y1: 1445,
      x2: base,
      y2: 1466,
      color: color,
      thickness: 6,
    );
  }
}

/// [arrows]：ページの印（'first'＝「»」だけ、'middle'＝両方、'last'＝「«」だけ）。
/// [scrollTopAt]：右下の「^」ボタン（灰色の丸）を描く縦の中心。
imglib.Image _screen(
  List<(int, Map<String, int>)> rows, {
  bool right = false,
  String? arrows,
  int? scrollTopAt,
}) {
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
  final gray = imglib.ColorRgb8(0x79, 0x79, 0x79);
  if (arrows == 'middle' || arrows == 'last') {
    _chevrons(image, left: true, gray);
  }
  if (arrows == 'middle' || arrows == 'first') {
    _chevrons(image, left: false, gray);
  }
  if (scrollTopAt != null) {
    imglib.fillCircle(
      image,
      x: 992,
      y: scrollTopAt,
      radius: 57,
      color: imglib.ColorRgb8(0x7d, 0x7d, 0x7d),
    );
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
    test('文字読み取りの読み違い：「幸町」が崩れても「スーパーメルヘン」で幸町、かっこが落ちても曜日で日付', () {
      final h = parseJoHeader(const [
        JoTextLine('スーパーメルヘンワールド辛叮店'),
        JoTextLine('データ更新：10/9'),
        JoTextLine('23:30'),
        JoTextLine('2日前 10/7水)'),
      ], DateTime(2026, 10, 10));
      expect((h.store, h.day), ('saiwaichou', '2026-10-07'));
      // かっこも曜日も無い日付・時刻だけの行は日付にしない。
      final none = parseJoHeader(const [
        JoTextLine('10/9 23:30'),
        JoTextLine('メルヘンワールド長町南店'),
      ], DateTime(2026, 10, 10));
      expect((none.store, none.day), ('nagamachiminami', null));
    });

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

    test('ページの印で左右を決め、真ん中のページ（確率など）は読まない', () {
      final now = DateTime(2026, 10, 9);
      expect(
        parseJoScreen(_screen(left, arrows: 'first'), _lines, now).side,
        'left',
      );
      expect(
        parseJoScreen(
          _screen(right, right: true, arrows: 'last'),
          _lines,
          now,
        ).side,
        'right',
      );
      // 真ん中のページは総回転数の列にも数字があるが、1ページ目と取り違えない。
      final middle = parseJoScreen(
        _screen(left, arrows: 'middle'),
        _lines,
        now,
      );
      expect(middle.problem, contains('真ん中のページ'));
      expect(middle.racks, isEmpty);
    });

    test('「^」ボタンに隠れた総回転数は読まない（ほかのマスは読む）', () {
      final screen = parseJoScreen(
        _screen(left, arrows: 'first', scrollTopAt: 1117),
        _lines,
        DateTime(2026, 10, 9),
      );
      final r780 = screen.racks.firstWhere((r) => r.rack == 780);
      expect(r780.values.containsKey('total'), isFalse);
      expect(r780.unreadable, contains('total'));
      expect(r780.values['start'], 213);
      // ページの印や区切り線のような1行だけの灰色は「^」ボタンにしない（実機の画面で取り違えた）。
      final thin = _screen(left, arrows: 'first');
      imglib.drawLine(
        thin,
        x1: 930,
        y1: 1117,
        x2: 1070,
        y2: 1117,
        color: imglib.ColorRgb8(0x79, 0x79, 0x79),
      );
      expect(joScrollTopButton(thin), isNull);
      expect(
        screen.racks.firstWhere((r) => r.rack == 779).values['total'],
        4957,
      );
    });

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

    test('連続で撮った画面は、画面の外に出た店名・機種名を同じ組・同じ日の画面から補う', () {
      JoScreen screen(String? store, String day, {String? machine}) => JoScreen(
        header: JoHeader(
          store: store,
          day: day,
          machine: machine,
          rate: machine == null ? null : '20',
        ),
        side: 'left',
        racks: [JoRack(790)],
      );
      final filled = fillJoGroupHeaders([
        (
          '20261010003000',
          screen('saiwaichou', '2026-10-07', machine: 'ネオアイムジャグラーEX'),
        ),
        ('20261010003000', screen(null, '2026-10-07')),
        ('20261010003000', screen(null, '2026-10-08')),
        (null, screen(null, '2026-10-07')),
        ('20261010004000', screen(null, '2026-10-07')),
      ]);
      expect(
        (
          filled[1].header.store,
          filled[1].header.machine,
          filled[1].header.rate,
        ),
        ('saiwaichou', 'ネオアイムジャグラーEX', '20'),
      );
      expect(filled[2].header.store, isNull, reason: '違う日には補わない');
      expect(filled[3].header.store, isNull, reason: '組の無い（1枚ずつ撮った）画面には補わない');
      expect(filled[4].header.store, isNull, reason: '別の組からは補わない');
      expect(
        joCaptureGroup('/x/jo-20261010-003001-123-g20261010003000.png'),
        '20261010003000',
      );
      expect(joCaptureGroup('/x/jo-20261010-003001-123.png'), isNull);
    });

    test('全機種表示：台の機種は、枠より上のいちばん近い見出し（「20スロ」と機種名が別の行でも）', () {
      final lines = [
        ..._lines,
        const JoTextLine('20スロ ネオアイムジャグラーEX', top: 900),
        const JoTextLine('20スロ', top: 1060),
        const JoTextLine('マイジャグラーV', top: 1064),
      ];
      expect(joSectionHeaders(lines).map((h) => (h.$2, h.$3)), [
        ('ネオアイムジャグラーEX', '20'),
        ('ネオアイムジャグラーEX', '20'),
        ('マイジャグラーV', '20'),
      ]);
      final screen = parseJoScreen(
        _screen(left, arrows: 'first'),
        lines,
        DateTime(2026, 10, 9),
      );
      expect(
        {for (final r in screen.racks) r.rack: r.machine},
        {779: 'ネオアイムジャグラーEX', 780: 'マイジャグラーV', 781: 'マイジャグラーV'},
      );
    });

    test('全機種表示：見出しが画面の外の台は前の画面から、差枚のページの台は1ページ目から機種を補う', () {
      JoScreen screen(String side, List<JoRack> racks) => JoScreen(
        header: const JoHeader(store: 'saiwaichou', day: '2026-10-09'),
        side: side,
        racks: racks,
      );
      final first = screen('left', [
        JoRack(412, machine: 'ミリオンゴッド', rate: '20'),
        JoRack(421, machine: '沖ドキ', rate: '20'),
      ]);
      final second = screen('left', [JoRack(428), JoRack(429)]);
      final other = screen('left', [JoRack(430)]);
      final net = screen('right', [JoRack(412), JoRack(429), JoRack(999)]);
      fillJoRackMachines([
        ('g1', first),
        ('g1', second),
        ('g2', other),
        ('g1', net),
      ]);
      expect(second.racks.map((r) => r.machine), ['沖ドキ', '沖ドキ']);
      expect(other.racks.single.machine, isNull, reason: '別の組からは補わない');
      expect(net.racks.map((r) => r.machine), ['ミリオンゴッド', '沖ドキ', null]);
      final day = mergeJoScreens([first, second, net]).single;
      expect(day.rackMachines[429], '沖ドキ');
      expect(day.rackRates[412], '20');
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
      expect(result.missing, [781], reason: '作る計画に無い台は作らない');
      expect(result.created, 0);
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

    SlotRecord meruhen(
      String day,
      int rack, {
      String machine = 'Sネオアイムジャグラー EX−KK',
    }) => SlotRecord(
      store: 'saiwaichou',
      day: day,
      machine: machine,
      rack: rack,
      games: 4000,
      bb: 10,
      rb: 10,
      maxHold: 1000,
    );

    test('メルヘンで取り込めなかった台は、前の日の同じ台番号の機種名で作る計画にする', () {
      final day = JoDay('saiwaichou', '2026-10-07')
        ..machine = 'ネオアイムジャグラーEX'
        ..racks.addAll({
          779: {'bb': 1, 'rb': 1, 'total': 100, 'net': 5},
          780: {'bb': 2, 'rb': 3, 'total': 200, 'net': -40},
          781: {'bb': 1, 'rb': 1, 'total': 100},
          782: {'bb': 1, 'rb': 1, 'total': 100},
          783: {'net': 10},
          784: {'bb': 1, 'rb': 1, 'total': 300, 'net': 7},
        })
        ..conflicts[784] = {'total'};
      final records = [
        meruhen('2026-10-07', 779),
        meruhen('2026-10-05', 780, machine: 'SマイジャグラーV KK'),
        meruhen('2026-10-06', 780),
        meruhen('2026-10-08', 781),
        meruhen('2026-10-06', 782, machine: 'SマイジャグラーV KK'),
        meruhen('2026-10-06', 783),
        meruhen('2026-10-06', 784),
      ];
      final plan = planJoSave(day, records);
      expect(plan.add.keys, [779], reason: '取り込み済みの台には足す');
      expect(plan.create.keys, [780]);
      expect(
        plan.create[780]!.reference.day,
        '2026-10-06',
        reason: 'いちばん近い前の日の台',
      );
      expect(plan.skipped.keys.toSet(), {781, 782, 783, 784});
      expect(plan.skipped[781], contains('前の日'), reason: '後の日の台は使わない');
      expect(plan.skipped[782], contains('機種が違う'));
      expect(plan.skipped[783], contains('読めていない'));
      expect(plan.skipped[784], contains('読めていない'), reason: '⚠の総回転数では作らない');
    });

    test('全機種表示：台ごとの機種で比べ、20スロ以外の台は足さない・作らない', () {
      final day = JoDay('saiwaichou', '2026-10-07')
        ..machine = 'ネオアイムジャグラーEX'
        ..racks.addAll({
          779: {'bb': 1, 'rb': 1, 'total': 100},
          780: {'bb': 1, 'rb': 1, 'total': 100},
          5001: {'bb': 1, 'rb': 1, 'total': 100},
        })
        ..rackMachines.addAll({
          779: 'ネオアイムジャグラーEX',
          780: 'マイジャグラーV',
          5001: 'ネオアイムジャグラーEX',
        })
        ..rackRates.addAll({779: '20', 780: '20', 5001: '5'});
      final plan = planJoSave(day, [
        meruhen('2026-10-06', 779),
        meruhen('2026-10-06', 780, machine: 'SマイジャグラーV KK'),
        meruhen('2026-10-06', 5001),
      ]);
      expect(plan.create.keys.toSet(), {779, 780}, reason: '780は台の見出しの機種で比べる');
      expect(plan.skipped[5001], contains('5スロ'));
    });

    test('機種名は空白・記号・全角英数字の違いを見ずに比べる', () {
      expect(joMachineMatches('ネオアイムジャグラーEX', 'Sネオアイムジャグラー EX−KK'), isTrue);
      expect(joMachineMatches('ネオアイムジャグラーＥＸ', 'Sネオアイムジャグラー EX-KK'), isTrue);
      expect(joMachineMatches('マイジャグラーV', 'Sネオアイムジャグラー EX−KK'), isFalse);
      expect(joMachineMatches('', 'Sネオアイムジャグラー EX−KK'), isFalse);
    });

    test('作った台：数値はジャグラーオンライン、機種名は前の日、グラフ無し。取り消しで消える', () async {
      final path = await newDatabasePath();
      final db = realDatabase(path);
      await db.applyChanges(ChangeSet(upserts: [meruhen('2026-10-06', 780)]));
      final c = AppController(database: db);
      await c.initialize();
      final day = JoDay('saiwaichou', '2026-10-07')
        ..machine = 'ネオアイムジャグラーEX'
        ..racks[780] = {
          'bb': 11,
          'rb': 7,
          'start': 579,
          'total': 3299,
          'net': -844,
        }
        ..racks[790] = {'bb': 1, 'rb': 1, 'total': 10};
      final plan = planJoSave(day, c.records);
      final result = await c.attachJugglerOnline(
        store: day.store,
        day: day.day,
        racks: plan.add,
        create: plan.create,
        now: DateTime.utc(2026, 10, 9, 15),
      );
      expect((result.updated, result.created), (0, 1));
      expect(result.missing, isEmpty, reason: '作れない台は計画の時点で外している');
      final made = (await db.loadAll()).firstWhere(
        (r) => r.day == '2026-10-07' && r.rack == 780,
      );
      expect(made.machine, 'Sネオアイムジャグラー EX−KK');
      expect((made.games, made.bb, made.rb), (3299, 11, 7));
      expect((made.maxHold, made.graph), (null, null));
      expect(made.extra['jo_created'], isTrue);
      expect(made.firstCapturedAt, isA<String>());
      expect((made.netValue, made.netLabel), (-844, '差枚'));
      expect(made.toJson()['kind_code'], 21, reason: 'PCのバックアップの読み込みで受け付ける形');
      await c.undoLastSave();
      expect((await db.loadAll()).where((r) => r.day == '2026-10-07'), isEmpty);
      await db.close();
    });

    test('作った台をあとでサイトの表から取り込み直したら、作った台の印を外す（差枚は残す）', () async {
      final path = await newDatabasePath();
      final db = realDatabase(path);
      await db.applyChanges(ChangeSet(upserts: [meruhen('2026-10-06', 780)]));
      final c = AppController(database: db);
      await c.initialize();
      final day = JoDay('saiwaichou', '2026-10-07')
        ..machine = 'ネオアイムジャグラーEX'
        ..racks[780] = {'bb': 11, 'rb': 7, 'total': 3299, 'net': -844};
      final plan = planJoSave(day, c.records);
      await c.attachJugglerOnline(
        store: day.store,
        day: day.day,
        racks: plan.add,
        create: plan.create,
      );
      await c.saveTable('saiwaichou', '2026-10-07', 'Sネオアイムジャグラー EX−KK', [
        EditableRow(
          rack: 780,
          games: 3290,
          bb: 11,
          rb: 7,
          detailUrl: 'https://example.com/780',
        ),
      ]);
      final saved = (await db.loadAll()).firstWhere(
        (r) => r.day == '2026-10-07',
      );
      expect(saved.games, 3290, reason: 'サイトの表の数値');
      expect(saved.extra.containsKey('jo_created'), isFalse);
      expect(saved.extra['jo_net'], -844);
      await db.close();
    });

    test('作った台はPCの閲覧用ファイルを通ってiPhoneの閲覧ページでも「差枚」として読める', () {
      // PC core.export_viewer が書く形（VIEWER_KEYS の項目だけ。グラフ・最大持玉は無い）。
      final text = jsonEncode({
        'format': 'database-backup',
        'version': 1,
        'source': 'pc-viewer',
        'records': [
          {
            'store': 'saiwaichou',
            'kind_code': 21,
            'day': '2026-10-07',
            'machine': 'Sネオアイムジャグラー EX−KK',
            'rack': 780,
            'games': 3299,
            'bb': 11,
            'rb': 7,
            'captured_at': '2026-10-10T01:00:00',
            'jo_net': -844,
          },
        ],
      });
      final data = ViewerData.parse(text);
      expect(data.skipped, 0);
      final r = data.records.single;
      expect(
        (r.games, r.bb, r.rb, r.graph, r.maxHold),
        (3299, 11, 7, null, null),
      );
      expect((r.netValue, r.netLabel, r.netNeedsCheck), (-844, '差枚', false));
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
