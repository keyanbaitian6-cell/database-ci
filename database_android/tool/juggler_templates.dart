// ジャグラーオンラインの数字のお手本（lib/juggler_digit_templates.dart）を、端末で撮った画面から作る。
// 使い方（database_android/ で）：
//   dart --packages=.dart_tool/package_config.json tool/juggler_templates.dart <answers.json>
// answers.json（Gitに入れない。画面は実データなので）：
//   [{"image": "C:/.../screen.png", "racks": [779, 780, ...], "values": [[15,10,0,288,4957], ...]}, ...]
//   左の画面は values に [bb, rb, art, start, total]、右の画面は [net]。racks・values は上の行から順に。
// 出力には数字の形（20×28を0〜15に丸めた濃さ）だけを書き、台の値は書かない。
import 'dart:convert';
import 'dart:io';

import 'package:database_android/juggler_online.dart';
import 'package:image/image.dart' as imglib;

const perDigit = 6;

void main(List<String> args) {
  final answers = jsonDecode(File(args.single).readAsStringSync()) as List;
  final samples = <String, List<List<double>>>{};
  void add(String text, List<Object> glyphs, String where) {
    final shapes = glyphs.where((g) => g is! String).toList();
    final chars = text.replaceAll('-', '');
    if (shapes.length != chars.length) {
      stderr.writeln('合わない：$where 「$text」 形${shapes.length}個');
      return;
    }
    for (var i = 0; i < chars.length; i++) {
      final list = samples.putIfAbsent(chars[i], () => []);
      if (list.length < perDigit) list.add(shapes[i] as List<double>);
    }
  }

  for (final entry in answers) {
    final image = imglib.decodePng(
      File(entry['image'] as String).readAsBytesSync(),
    )!;
    final boxes = findRackBoxes(image);
    final racks = (entry['racks'] as List).cast<int>();
    final values = (entry['values'] as List)
        .map((v) => (v as List).cast<int>())
        .toList();
    if (boxes.length != racks.length) {
      stderr.writeln('${entry['image']}：枠${boxes.length}個、答え${racks.length}台');
      exit(1);
    }
    final columns = values.first.length == 1 ? joRightColumns : joLeftColumns;
    for (var r = 0; r < boxes.length; r++) {
      final (top, bottom) = boxes[r];
      final (rx0, rx1) = joRackColumn;
      add(
        '${racks[r]}',
        cellGlyphs(
          image,
          rx0 + 14,
          rx1 - 14,
          top + 7,
          bottom - 5,
          (p) => p.r > 180 && p.g < 120,
        ),
        'rack $r',
      );
      final center = (top + bottom) ~/ 2;
      var c = 0;
      for (final (x0, x1) in columns.values) {
        add(
          '${values[r][c]}',
          cellGlyphs(
            image,
            x0,
            x1,
            center - 36,
            center + 36,
            (p) => (p.r + p.g + p.b) / 3 > 150,
          ),
          'row $r col $c',
        );
        c++;
      }
    }
  }
  final out = StringBuffer()
    ..writeln(
      '/// ジャグラーオンラインの表の数字のお手本（tool/juggler_templates.dart で作る。形だけで、台の値は入っていない）。',
    )
    ..writeln('/// 濃さは20×28の各点を0〜15（16進1文字）に丸めたもの。')
    ..writeln('library;')
    ..writeln()
    ..writeln('class JoDigitTemplate {')
    ..writeln('  const JoDigitTemplate(this.digit, this.pixels);')
    ..writeln('  final String digit;')
    ..writeln('  final List<double> pixels;')
    ..writeln('}')
    ..writeln()
    ..writeln('const _shapes = <(String, String)>[');
  final digits = samples.keys.toList()..sort();
  for (final d in digits) {
    for (final s in samples[d]!) {
      final hex = s
          .map((v) => (v * 15).round().clamp(0, 15).toRadixString(16))
          .join();
      out.writeln("  ('$d', '$hex'),");
    }
  }
  out
    ..writeln('];')
    ..writeln()
    ..writeln('final List<JoDigitTemplate> joDigitTemplates = [')
    ..writeln('  for (final (digit, hex) in _shapes)')
    ..writeln(
      '    JoDigitTemplate(digit, [for (final c in hex.split(\'\')) int.parse(c, radix: 16) / 15]),',
    )
    ..writeln('];');
  File('lib/juggler_digit_templates.dart').writeAsStringSync(out.toString());
  stdout.writeln(
    '数字 ${digits.join()}：${digits.map((d) => samples[d]!.length).join('・')}個ずつ',
  );
}
