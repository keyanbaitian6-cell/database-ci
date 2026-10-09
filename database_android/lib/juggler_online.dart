/// ジャグラーオンライン（北電子のアプリ。Unityで描かれ、画面の文字はアクセシビリティから読めない）の
/// 「データ一覧」を撮った画像から、台番号・BB・RB・AT/ART・スタート・総回転数・差枚を読む
/// （お試し、2026-10-09から最長2週間。`JUGGLER_ONLINE.md`）。
///
/// 表の数字は、数字の形のお手本（`juggler_digit_templates.dart`、このアプリの画面の書体）と見比べて読む
/// （汎用の文字読み取りは1桁の数字を読み落とすため）。店名・日付・機種名は ML Kit の文字読み取りの結果
/// （[JoTextLine]）から読む。画面の大きさは、お手本を作った端末（横1080px）だけに対応する。
library;

import 'dart:math' as math;

import 'package:image/image.dart' as imglib;

import 'juggler_digit_templates.dart';
import 'models.dart';
import 'setting_estimate.dart' show foldHalfWidthKana;

/// お手本を作った端末の画面の横幅（px）。違う大きさの画面は読まない。
const joScreenWidth = 1080;

/// 文字の形を比べる大きさ（横×縦）。
const joGlyphWidth = 20, joGlyphHeight = 28;

/// お手本との違いがこれより大きい形は、数字として読まない（読めないマスにする）。
const joGlyphMaxDistance = 0.22;

/// 列の位置（横1080pxの画面、左右の端は列の区切り線の内側）。左の画面と、右へスクロールした画面。
const joLeftColumns = <String, (int, int)>{
  'bb': (240, 384),
  'rb': (390, 536),
  'art': (544, 690),
  'start': (696, 842),
  'total': (848, 996),
};
const joRightColumns = <String, (int, int)>{'net': (240, 386)};

/// 台番号の枠（ピンク）を探す横の範囲。
const joRackColumn = (88, 232);

/// ML Kit が読んだ1行。
class JoTextLine {
  const JoTextLine(this.text, {this.top = 0});
  final String text;
  final int top;
}

/// 画面の見出し：店舗（`saiwaichou`・`nagamachiminami`）・営業日・機種名・貸玉。
class JoHeader {
  const JoHeader({this.store, this.day, this.machine, this.rate});
  final String? store, day, machine, rate;
}

/// 読み取った1台（その画面に出ていた項目だけ。読めなかったマスは null で、[unreadable] に入る）。
class JoRack {
  JoRack(this.rack, {this.machine, this.rate});
  final int rack;

  /// その台の機種名と貸玉（すぐ上の「20スロ 機種名」の見出しから。全機種表示では台ごとに違う）。
  String? machine, rate;
  final values = <String, int>{};
  final unreadable = <String>{};
}

/// 1枚の画面の読み取り結果。
class JoScreen {
  const JoScreen({
    required this.header,
    required this.side,
    required this.racks,
    this.problem,
  });
  final JoHeader header;

  /// 'left'（BB〜総回転数）か 'right'（差枚）。読めなければ null。
  final String? side;
  final List<JoRack> racks;

  /// 読めなかった理由（画面の大きさが違う、表が無いなど）。
  final String? problem;
}

bool _white(imglib.Pixel p) => (p.r + p.g + p.b) / 3 > 150;

/// 横のページの印「«」「»」と、右下の「^」（いちばん上へ）ボタンの灰色（0x79〜0x7e）。
bool _uiGray(imglib.Pixel p) =>
    p.r >= 0x68 &&
    p.r <= 0x90 &&
    (p.r - p.g).abs() < 8 &&
    (p.r - p.b).abs() < 8;

/// 横のページの印（画面の左右の端、表の上下の位置に関係なく同じ高さ）。表は横に3ページ：
/// 1ページ目（BB〜総回転数）は「»」だけ、2ページ目（確率など）は両方、3ページ目（差枚）は「«」だけ。
({bool left, bool right}) joPageArrows(imglib.Image image) {
  final y0 = (image.height * 0.58).round(), y1 = (image.height * 0.66).round();
  int count(int x0, int x1) {
    var n = 0;
    for (var y = y0; y < y1 && y < image.height; y += 2) {
      for (var x = x0; x < x1 && x < image.width; x += 2) {
        if (_uiGray(image.getPixel(x, y))) n++;
      }
    }
    return n;
  }

  return (
    left: count(0, 86) >= 25,
    right: count(image.width - 80, image.width) >= 25,
  );
}

/// 右下の「^」（いちばん上へ）ボタンが重なっている縦の範囲。表をスクロールすると出て、総回転数の
/// 列の数字を隠す（2026-10-10 に実機で確認）。無ければ null。
(int, int)? joScrollTopButton(imglib.Image image) {
  // 丸いボタンは横に広く（1行に40点以上）、縦にも続く（高さ約115px）。ページの印「»」や
  // 区切り線の1行だけのものは数えない（2026-10-10、実機の画面で印の1行をボタンと取り違えた）。
  (int, int)? best;
  int? start;
  for (var y = 0; y <= image.height; y++) {
    var n = 0;
    if (y < image.height) {
      for (var x = 900; x < image.width; x++) {
        if (_uiGray(image.getPixel(x, y))) n++;
      }
    }
    if (n >= 40) {
      start ??= y;
    } else if (start != null) {
      if (y - start >= 40 && (best == null || y - start > best.$2 - best.$1)) {
        best = (start, y - 1);
      }
      start = null;
    }
  }
  return best;
}

bool _pink(imglib.Pixel p) => p.r > 180 && p.g < 120;

/// 2値の形（[width]×[height]、行ごと）を、[joGlyphWidth]×[joGlyphHeight] の面積の平均に縮める。
List<double> normalizeGlyph(List<bool> mask, int width, int height) {
  final out = List<double>.filled(joGlyphWidth * joGlyphHeight, 0);
  for (var j = 0; j < joGlyphHeight; j++) {
    final y0 = j * height / joGlyphHeight,
        y1 = (j + 1) * height / joGlyphHeight;
    for (var i = 0; i < joGlyphWidth; i++) {
      final x0 = i * width / joGlyphWidth, x1 = (i + 1) * width / joGlyphWidth;
      var sum = 0.0, area = 0.0;
      for (var y = y0.floor(); y < y1.ceil() && y < height; y++) {
        final wy = math.min(y + 1, y1) - math.max(y.toDouble(), y0);
        if (wy <= 0) continue;
        for (var x = x0.floor(); x < x1.ceil() && x < width; x++) {
          final wx = math.min(x + 1, x1) - math.max(x.toDouble(), x0);
          if (wx <= 0) continue;
          area += wx * wy;
          if (mask[y * width + x]) sum += wx * wy;
        }
      }
      out[j * joGlyphWidth + i] = area == 0 ? 0 : sum / area;
    }
  }
  return out;
}

/// 1つのマス（[x0]〜[x1]・[y0]〜[y1]）の文字の形を左から順に返す。マイナスは '-'。
List<Object> cellGlyphs(
  imglib.Image image,
  int x0,
  int x1,
  int y0,
  int y1,
  bool Function(imglib.Pixel) on,
) {
  final width = x1 - x0, height = y1 - y0;
  final mask = List<bool>.filled(width * height, false);
  for (var y = 0; y < height; y++) {
    for (var x = 0; x < width; x++) {
      mask[y * width + x] = on(image.getPixel(x0 + x, y0 + y));
    }
  }
  final glyphs = <Object>[];
  int? start;
  for (var x = 0; x <= width; x++) {
    var any = false;
    if (x < width) {
      for (var y = 0; y < height && !any; y++) {
        any = mask[y * width + x];
      }
    }
    if (any) {
      start ??= x;
      continue;
    }
    if (start == null) continue;
    final a = start, b = x;
    start = null;
    if (b - a < 3) continue;
    var top = height, bottom = -1;
    for (var y = 0; y < height; y++) {
      for (var xx = a; xx < b; xx++) {
        if (mask[y * width + xx]) {
          top = math.min(top, y);
          bottom = math.max(bottom, y);
          break;
        }
      }
    }
    final h = bottom - top + 1;
    if (h <= 0) continue;
    if (h < 12 && (b - a) > h) {
      glyphs.add('-'); // 横長で背の低い形はマイナス
      continue;
    }
    if (h < 10) continue; // 点・線のかけら
    final w = b - a;
    final sub = List<bool>.generate(
      w * h,
      (i) => mask[(top + i ~/ w) * width + a + i % w],
    );
    glyphs.add(normalizeGlyph(sub, w, h));
  }
  return glyphs;
}

/// 形がどの数字か（お手本との平均の差が最も小さいもの）。どれとも遠ければ null。
String? matchDigit(List<double> glyph, List<JoDigitTemplate> templates) {
  String? best;
  var bestDistance = double.infinity;
  for (final t in templates) {
    var d = 0.0;
    for (var i = 0; i < glyph.length; i++) {
      d += (glyph[i] - t.pixels[i]).abs();
    }
    d /= glyph.length;
    if (d < bestDistance) {
      bestDistance = d;
      best = t.digit;
    }
  }
  return bestDistance <= joGlyphMaxDistance ? best : null;
}

/// マスの数字。空のマスは null、読めない形があれば [JoUnreadable]。
Object? readCell(
  imglib.Image image,
  int x0,
  int x1,
  int y0,
  int y1,
  bool Function(imglib.Pixel) on,
  List<JoDigitTemplate> templates,
) {
  final glyphs = cellGlyphs(image, x0, x1, y0, y1, on);
  if (glyphs.isEmpty) return null;
  var text = '';
  for (final g in glyphs) {
    if (g is String) {
      if (text.isNotEmpty) return const JoUnreadable();
      text = '-';
      continue;
    }
    final digit = matchDigit(g as List<double>, templates);
    if (digit == null) return const JoUnreadable();
    text += digit;
  }
  return int.tryParse(text) ?? const JoUnreadable();
}

class JoUnreadable {
  const JoUnreadable();
}

/// 台番号のピンクの枠（上下の線の組）を上から順に。画面の上下で切れている枠は入れない。
List<(int, int)> findRackBoxes(imglib.Image image) {
  final (left, right) = joRackColumn;
  final lines = <int>[];
  for (var y = 0; y < image.height; y++) {
    var count = 0, outside = 0;
    for (var x = left; x < right; x++) {
      if (_pink(image.getPixel(x, y))) count++;
    }
    // 枠の横線は台番号の列だけにある（タブやボタンは横に長く、列の外まで続く）。
    for (var x = right; x < math.min(right + 40, image.width); x++) {
      if (_pink(image.getPixel(x, y))) outside++;
    }
    if (count > 90 && outside < 4) lines.add(y);
  }
  // 続いた行を1本の線にまとめる。
  final merged = <int>[];
  for (final y in lines) {
    if (merged.isEmpty || y - merged.last > 3) merged.add(y);
  }
  final boxes = <(int, int)>[];
  for (var i = 0; i + 1 < merged.length; i++) {
    final gap = merged[i + 1] - merged[i];
    if (gap >= 40 && gap <= 75) {
      // 台番号の枠は中が暗い（ピンクの文字だけ）。上の「ON」スイッチなど、中までピンクのものは除く。
      var inside = 0, filled = 0;
      for (var y = merged[i] + 6; y < merged[i + 1] - 4; y += 2) {
        for (var x = left + 12; x < right - 12; x += 2) {
          inside++;
          if (_pink(image.getPixel(x, y))) filled++;
        }
      }
      if (inside > 0 && filled / inside < 0.3) {
        boxes.add((merged[i], merged[i + 1]));
      }
      i++;
    }
  }
  return boxes;
}

// 「10/6(火)」。文字読み取りがかっこを落としても、曜日が続けば日付とする（2026-10-10、幸町の画面で
// 店舗か日付を読めない画面があった）。「データ更新：10/9 23:30」は呼ぶ側で除く。
final _dayPattern = RegExp(
  r'(\d{1,2})\s*[/／]\s*(\d{1,2})\s*(?:[（(]|[日月火水木金土])',
);

/// 見出しを読む：店舗（幸町・長町南）、営業日（「本日 10/9(金)」「3日前 10/6(火)」。年は [now] から）、
/// 機種名と貸玉（「20スロ ネオアイムジャグラーEX」）。「データ更新：10/9 23:00」は日付にしない。
JoHeader parseJoHeader(List<JoTextLine> lines, DateTime now) {
  String? store, day, machine, rate;
  for (final line in lines) {
    final text = line.text.replaceAll(' ', '').replaceAll('　', '');
    if (store == null) {
      // 「スーパーメルヘンワールド幸町店」「メルヘンワールド長町南店」。「幸町」を読み違えても、
      // 「スーパーメルヘン」は幸町だけ。
      if (text.contains('幸町') || text.contains('スーパーメルヘン')) {
        store = 'saiwaichou';
      }
      if (text.contains('長町南')) store = 'nagamachiminami';
    }
    if (day == null && !text.contains('更新')) {
      final m = _dayPattern.firstMatch(text);
      if (m != null) {
        final month = int.parse(m.group(1)!), date = int.parse(m.group(2)!);
        if (month >= 1 && month <= 12 && date >= 1 && date <= 31) {
          var year = now.year;
          if (month > now.month + 1) year--; // 1月に12月の画面を見たとき
          day =
              '$year-${month.toString().padLeft(2, '0')}-${date.toString().padLeft(2, '0')}';
        }
      }
    }
    final slot = RegExp(r'^(\d+(?:\.\d+)?)スロ(.+)$').firstMatch(text);
    if (machine == null && slot != null) {
      rate = slot.group(1);
      machine = slot.group(2);
    }
  }
  return JoHeader(store: store, day: day, machine: machine, rate: rate);
}

/// 画面の中の機種の見出し（「20スロ ネオアイムジャグラーEX」）の位置。上から順。
/// 文字読み取りが「20スロ」と機種名を別の行に分けたときは、同じ高さの行をつなぐ。
List<(int, String, String)> joSectionHeaders(List<JoTextLine> lines) {
  final result = <(int, String, String)>[];
  for (final line in lines) {
    final text = line.text.replaceAll(' ', '').replaceAll('　', '');
    final m = RegExp(r'^(\d+(?:\.\d+)?)スロ(.*)$').firstMatch(text);
    if (m == null) continue;
    var machine = m.group(2)!;
    if (machine.isEmpty) {
      final beside = lines.where(
        (l) =>
            !identical(l, line) &&
            (l.top - line.top).abs() <= 30 &&
            !RegExp(r'^\d+(?:\.\d+)?スロ').hasMatch(l.text.trim()),
      );
      if (beside.isEmpty) continue;
      machine = beside.first.text.replaceAll(' ', '').replaceAll('　', '');
    }
    if (machine.isEmpty) continue;
    result.add((line.top, machine, m.group(1)!));
  }
  return result..sort((a, b) => a.$1.compareTo(b.$1));
}

/// 1枚の画面を読む。[lines] はその画面の ML Kit の結果。
JoScreen parseJoScreen(
  imglib.Image image,
  List<JoTextLine> lines,
  DateTime now, {
  List<JoDigitTemplate>? templates,
}) {
  final header = parseJoHeader(lines, now);
  final digits = templates ?? joDigitTemplates;
  if (image.width != joScreenWidth) {
    return JoScreen(
      header: header,
      side: null,
      racks: const [],
      problem:
          '画面の大きさ（横${image.width}px）が、読み取りを作った端末（横${joScreenWidth}px）と違います。',
    );
  }
  final boxes = findRackBoxes(image);
  if (boxes.isEmpty) {
    return JoScreen(
      header: header,
      side: null,
      racks: const [],
      problem: '台番号の表が見つかりません。「データ一覧」の画面で取り込んでください。',
    );
  }
  // 何ページ目かは「«」「»」の印で決める。2ページ目（確率など）は総回転数の列にも数字があり、
  // 1ページ目と取り違えると総回転数・スタートを誤って読むので読まない（2026-10-10）。
  final arrows = joPageArrows(image);
  if (arrows.left && arrows.right) {
    return JoScreen(
      header: header,
      side: null,
      racks: const [],
      problem: '真ん中のページ（確率など）なので読みません。左端（BB〜総回転数）と右端（差枚）のページを撮ってください。',
    );
  }
  final String side;
  if (arrows.right != arrows.left) {
    side = arrows.right ? 'left' : 'right';
  } else {
    // 印が無いとき：総回転数の列に数字があれば左の画面、無ければ右（差枚）の画面。
    final (tx0, tx1) = joLeftColumns['total']!;
    var leftRows = 0;
    for (final (top, bottom) in boxes) {
      final center = (top + bottom) ~/ 2;
      if (cellGlyphs(
        image,
        tx0,
        tx1,
        center - 36,
        center + 36,
        _white,
      ).isNotEmpty) {
        leftRows++;
      }
    }
    side = leftRows > 0 ? 'left' : 'right';
  }
  final scrollTop = joScrollTopButton(image);
  final columns = side == 'left' ? joLeftColumns : joRightColumns;
  final racks = <JoRack>[];
  final sections = joSectionHeaders(lines);
  final (rx0, rx1) = joRackColumn;
  for (final (top, bottom) in boxes) {
    final rackValue = readCell(
      image,
      rx0 + 14,
      rx1 - 14,
      top + 7,
      bottom - 5,
      _pink,
      digits,
    );
    if (rackValue is! int || rackValue <= 0) continue;
    // 機種は、枠より上にある見出しのうちいちばん近いもの（無ければ前の画面から補う、fillJoRackMachines）。
    (int, String, String)? section;
    for (final h in sections) {
      if (h.$1 < top) section = h;
    }
    final rack = JoRack(rackValue, machine: section?.$2, rate: section?.$3);
    final center = (top + bottom) ~/ 2;
    for (final entry in columns.entries) {
      final (x0, x1) = entry.value;
      // 「^」ボタンに隠れたマスは読まない（同じ台は、ほかの画面で隠れずに写る）。
      if (scrollTop != null &&
          x1 > 900 &&
          center + 36 >= scrollTop.$1 &&
          center - 36 <= scrollTop.$2) {
        rack.unreadable.add(entry.key);
        continue;
      }
      final value = readCell(
        image,
        x0,
        x1,
        center - 36,
        center + 36,
        _white,
        digits,
      );
      if (value is int) {
        rack.values[entry.key] = value;
      } else {
        rack.unreadable.add(entry.key);
      }
    }
    racks.add(rack);
  }
  return JoScreen(header: header, side: side, racks: racks);
}

/// 「取込」ボタンの連続撮影の組（ファイル名の `-g<組>`）。1回押して撮った画面は同じ組。
String? joCaptureGroup(String path) =>
    RegExp(r'-g(\d+)\.png$').firstMatch(path)?.group(1);

/// 連続で撮った画面の見出しを補う。表をスクロールすると店名・機種名が画面の外に出る（日付は残る）ため、
/// 同じ組・同じ日の画面で読めた店名・機種名・貸玉を使う。組の中で店名が割れていたら補わない。
List<JoScreen> fillJoGroupHeaders(List<(String?, JoScreen)> screens) {
  final stores = <String, Set<String>>{};
  final machines = <String, (String, String?)>{};
  for (final (group, screen) in screens) {
    final h = screen.header;
    if (group == null || h.day == null) continue;
    final key = '$group|${h.day}';
    if (h.store != null) stores.putIfAbsent(key, () => {}).add(h.store!);
    if (h.machine != null) {
      machines.putIfAbsent(key, () => (h.machine!, h.rate));
    }
  }
  return [
    for (final (group, screen) in screens)
      if (group == null || screen.header.day == null)
        screen
      else
        () {
          final h = screen.header, key = '$group|${h.day}';
          final store =
              h.store ??
              (stores[key]?.length == 1 ? stores[key]!.single : null);
          final machine = h.machine ?? machines[key]?.$1;
          final rate = h.machine == null ? machines[key]?.$2 : h.rate;
          return JoScreen(
            header: JoHeader(
              store: store,
              day: h.day,
              machine: machine,
              rate: rate,
            ),
            side: screen.side,
            racks: screen.racks,
            problem: screen.problem,
          );
        }(),
  ];
}

/// 見出しが画面の外に出ている台の機種名・貸玉を補う（[screens] は撮った順）。1ページ目（左）の画面は
/// 上から下へ撮るので、前の画面の最後の見出しを引き継ぐ。差枚のページ（右）の台は、同じ組・同じ日の
/// 1ページ目で決まった機種を台番号で引く。組の無い（1枚ずつ撮った）画面は、その画面の見出しだけ。
void fillJoRackMachines(List<(String?, JoScreen)> screens) {
  final byRack = <String, (String, String?)>{};
  final carry = <String, (String, String?)>{};
  for (final (group, screen) in screens) {
    final day = screen.header.day;
    if (group == null || day == null || screen.side != 'left') continue;
    final key = '$group|$day';
    for (final rack in screen.racks) {
      final last = carry[key];
      if (rack.machine == null && last != null) {
        rack.machine = last.$1;
        rack.rate = last.$2;
      }
      if (rack.machine != null) {
        carry[key] = (rack.machine!, rack.rate);
        byRack['$key|${rack.rack}'] = (rack.machine!, rack.rate);
      }
    }
  }
  for (final (group, screen) in screens) {
    final day = screen.header.day;
    if (group == null || day == null || screen.side != 'right') continue;
    for (final rack in screen.racks) {
      final known = byRack['$group|$day|${rack.rack}'];
      if (known != null) {
        rack.machine = known.$1;
        rack.rate = known.$2;
      }
    }
  }
}

/// 複数の画面を、店舗・営業日・台番号でまとめる。同じ台の同じ項目が画面ごとに違えば [conflicts] に入れる。
class JoDay {
  JoDay(this.store, this.day);
  final String store, day;
  String? machine;
  final racks = <int, Map<String, int>>{};

  /// 台ごとの機種名・貸玉（全機種表示）。
  final rackMachines = <int, String>{};
  final rackRates = <int, String>{};
  final conflicts = <int, Set<String>>{};
  final unreadable = <int, Set<String>>{};
}

List<JoDay> mergeJoScreens(Iterable<JoScreen> screens) {
  final days = <String, JoDay>{};
  for (final screen in screens) {
    final store = screen.header.store, day = screen.header.day;
    if (store == null || day == null || screen.side == null) continue;
    final merged = days.putIfAbsent('$store|$day', () => JoDay(store, day));
    merged.machine ??= screen.header.machine;
    for (final rack in screen.racks) {
      final values = merged.racks.putIfAbsent(rack.rack, () => {});
      if (rack.machine != null) {
        merged.rackMachines.putIfAbsent(rack.rack, () => rack.machine!);
      }
      if (rack.rate != null) {
        merged.rackRates.putIfAbsent(rack.rack, () => rack.rate!);
      }
      for (final entry in rack.values.entries) {
        final old = values[entry.key];
        if (old != null && old != entry.value) {
          merged.conflicts.putIfAbsent(rack.rack, () => {}).add(entry.key);
        }
        values[entry.key] = entry.value;
      }
      if (rack.unreadable.isNotEmpty) {
        merged.unreadable
            .putIfAbsent(rack.rack, () => {})
            .addAll(rack.unreadable);
      }
    }
  }
  return days.values.toList()
    ..sort((a, b) => '${a.store}${a.day}'.compareTo('${b.store}${b.day}'));
}

/// 保存する値：画面ごとに値が違った項目（⚠）は、どちらが正しいか分からないので足さない。
/// 足す項目が1つも残らない台は入れない。
Map<int, Map<String, int>> joSaveValues(JoDay day) => {
  for (final entry in day.racks.entries)
    if ({
          for (final field in entry.value.entries)
            if (!(day.conflicts[entry.key]?.contains(field.key) ?? false))
              field.key: field.value,
        }
        case final values when values.isNotEmpty)
      entry.key: values,
};

/// 保存の計画：取り込み済みの台に足す値と、新しく作る台（利用者 2026-10-10「7,8,9はデータサイトが死んでて
/// 取り込めなかったんだけど追加してくれるかな？ 6日から台番号は入れ替えなどで変わってないから」）。
class JoSavePlan {
  JoSavePlan(this.add, this.create, this.skipped);

  /// 取り込み済みの台（台番号 → 足す値）。
  final Map<int, Map<String, int>> add;

  /// 新しく作る台（台番号 → 前の日の同じ台番号の記録と、作る値）。
  final Map<int, ({SlotRecord reference, Map<String, int> values})> create;

  /// 足さない・作らない台と、その理由。
  final Map<int, String> skipped;
}

/// メルヘンで取り込めなかった台は、**前の日の同じ台番号** の機種名を引き継いで、ジャグラーオンラインの
/// BB・RB・総回転数で作る（グラフ・最大持玉は無い）。作るのは、前の日にその台があり、機種名が
/// ジャグラーオンラインの機種名と合い、BB・RB・総回転数が読めている台だけ。
JoSavePlan planJoSave(JoDay day, Iterable<SlotRecord> records) {
  final add = <int, Map<String, int>>{};
  final create = <int, ({SlotRecord reference, Map<String, int> values})>{};
  final skipped = <int, String>{};
  // 台番号ごとに、その日にあるか・いちばん近い前の日の台（全機種で数百台あるので先にまとめる）。
  final today = <int>{};
  final previous = <int, SlotRecord>{};
  for (final r in records) {
    if (r.isPscube || r.store != day.store) continue;
    if (r.day == day.day) {
      today.add(r.rack);
    } else if (r.day.compareTo(day.day) < 0 &&
        (previous[r.rack] == null ||
            r.day.compareTo(previous[r.rack]!.day) > 0)) {
      previous[r.rack] = r;
    }
  }
  // 台の並びでの確かめ：ジャグラーオンラインの1つの機種の台が、前の日もすべてメルヘンの同じ1つの機種なら、
  // 名前の書き方が違っても同じ機種とする（利用者「6日から台番号は入れ替えなどで変わってないから」）。
  final referencesOf = <String, Set<String>>{};
  for (final rack in day.racks.keys) {
    final machine = day.rackMachines[rack] ?? day.machine;
    final reference = previous[rack];
    if (machine != null && reference != null) {
      referencesOf.putIfAbsent(machine, () => {}).add(reference.machine);
    }
  }
  for (final MapEntry(key: rack, value: values) in joSaveValues(day).entries) {
    // メルヘンの記録は20円スロットだけ。ほかの貸玉の台は足さない・作らない。
    final rate = day.rackRates[rack];
    if (rate != null && rate != '20') {
      skipped[rack] = '$rateスロなので足さない';
      continue;
    }
    if (today.contains(rack)) {
      add[rack] = values;
      continue;
    }
    final reference = previous[rack];
    final machine = day.rackMachines[rack] ?? day.machine;
    if (reference == null) {
      skipped[rack] = '前の日に同じ台番号の台が無いので作らない';
    } else if (machine != null &&
        referencesOf[machine]?.length != 1 &&
        !joMachineMatches(machine, reference.machine)) {
      skipped[rack] =
          '機種が違うので作らない（${reference.day}：${reference.machine}、ジャグラーオンライン：$machine）';
    } else if (values['bb'] == null ||
        values['rb'] == null ||
        values['total'] == null) {
      skipped[rack] = 'BB・RB・総回転数が読めていないので作らない';
    } else {
      create[rack] = (reference: reference, values: values);
    }
  }
  return JoSavePlan(add, create, skipped);
}

/// 機種名を比べるための形：半角カナ・全角英数をそろえ、頭の「L」「S」「LB」「★」「スマスロ」「パチスロ」など、
/// 記号・空白・長音（ジャグラーオンラインの「－」とメルヘンの「ー」が入れ替わって読まれるため）を除く。
/// [meruhen] ならメルヘンの末尾の型番（「CX」「jG」「EX−KK」など、英数字6文字まで）も除く。
String joMachineKey(String name, {bool meruhen = false}) {
  final kana = foldHalfWidthKana(name);
  var text = String.fromCharCodes([
    for (final c in kana.runes)
      if (c >= 0xFF01 && c <= 0xFF5E) c - 0xFEE0 else c,
  ]).toUpperCase().replaceAll(RegExp(r'[^0-9A-Z぀-ヺヽ-ヿ一-鿿Ⅰ-ⅿ々★]'), '');
  final prefix = RegExp(r'^(★|LB|SB|L|S|スマスロ|パチスロ|スロット)');
  for (
    var m = prefix.firstMatch(text);
    m != null;
    m = prefix.firstMatch(text)
  ) {
    text = text.substring(m.end);
  }
  if (meruhen) {
    final trimmed = text.replaceFirst(RegExp(r'[0-9A-Z]{1,6}$'), '');
    if (trimmed.length >= 2) text = trimmed;
  }
  return text;
}

/// ジャグラーオンラインの機種名とメルヘンの機種名が同じ機種らしいか。メルヘンは略称と型番の
/// 独自の書き方（例「L／ミリオンゴッド／CX」「Lモンキーターン5CE」）なので、そろえた形の片方が
/// もう片方に含まれるか、メルヘンの形の2文字の並びの8割以上がジャグラーオンラインの形にあれば同じとする。
bool joMachineMatches(String juggler, String meruhen) {
  final j = joMachineKey(juggler), m = joMachineKey(meruhen, meruhen: true);
  if (j.isEmpty || m.isEmpty) return false;
  if (j.contains(m) || m.contains(j)) return true;
  if (m.length < 3) return false;
  var hit = 0;
  for (var i = 0; i + 1 < m.length; i++) {
    if (j.contains(m.substring(i, i + 2))) hit++;
  }
  return hit / (m.length - 1) >= 0.8;
}
